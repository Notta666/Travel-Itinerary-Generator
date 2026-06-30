"""
多引擎图片获取工具 v3.0
======================
引擎链：本地图片 → 高德API(主) → Wikimedia(免Key) → 360图片(免Key) → 百度(免Key) → Bing(免Key) → Pixabay/Unsplash(可选Key)
核心改进：
  - 渐进式关键词退避（同一引擎内多查询词迭代）
  - 随机Jitter限流防WAF
  - URL连通性预检（HEAD请求过滤死链/403）
  - 本地自定义图片覆盖（data/custom_images/）
  - 无水印源：Wikimedia Commons / Unsplash / Pixabay
"""
import os, json, time, urllib.request, re, hashlib, random, logging
from utils.config import AMAP_KEY, BASE_DIR, UNSPLASH_ACCESS_KEY, PIXABAY_API_KEY

logger = logging.getLogger("travel_pipeline")

CACHE_DIR = os.path.join(BASE_DIR, "data", "image_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
CUSTOM_IMG_DIR = os.path.join(BASE_DIR, "data", "custom_images")
os.makedirs(CUSTOM_IMG_DIR, exist_ok=True)

_REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def _cache_path(name):
    h = hashlib.md5(name.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")


def _load_cache(name):
    p = _cache_path(name)
    if os.path.exists(p):
        try:
            d = json.load(open(p, "r"))
            if time.time() - d["ts"] < 7 * 86400:
                return d["urls"]
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_cache(name, urls):
    try:
        with open(_cache_path(name), "w") as f:
            json.dump({"urls": urls, "ts": time.time()}, f)
    except (OSError, TypeError):
        pass


def _clean_name(name):
    """移除括号及分店信息"""
    return re.sub(r'[\uff08(].*?[\uff09)]', '', name).strip()


def _get_fallback_queries(name, city="", category=""):
    """生成渐进式关键词退避列表，从高精度到低精度。
    同一搜索词在引擎内部自动迭代，避免无结果的'穿模'。
    分类关键词强化：美食和景点用不同语义标签，防止混淆。
    性能优化(v3.5.2)：基础查询优先（高命中率），关键词退避靠后（降级时再用）。
    """
    cleaned = _clean_name(name)
    queries = []

    # 1. 城市 + POI名（最常用，定位最准）
    if city and city not in cleaned:
        queries.append(f"{city} {cleaned}")
    else:
        queries.append(cleaned)

    # 2. 纯POI名（对著名景点更友好，如"西湖"）
    if cleaned not in queries:
        queries.append(cleaned)

    # 3. 省+城市+POI名（高精度兜底）
    province = _CITY_PROVINCE.get(city, "")
    if province:
        full = f"{province}{city}{cleaned}"
        if full not in queries:
            queries.append(full)

    # ---- 分类关键词兜底（放基础查询之后，作为退路而非首选） ----
    if category == "food":
        food_keywords = ["美食", "餐厅"]
        for q in queries[:3]:  # 只用前3个基础查询
            for kw in food_keywords:
                kw_q = f"{q} {kw}"
                if kw_q not in queries:
                    queries.append(kw_q)
    elif category == "sight":
        sight_keywords = ["景点", "风光"]
        for q in queries[:3]:
            for kw in sight_keywords:
                kw_q = f"{q} {kw}"
                if kw_q not in queries:
                    queries.append(kw_q)

    return queries


# 城市→省份映射
_CITY_PROVINCE = {
    "上海": "上海市", "北京": "北京市", "天津": "天津市", "重庆": "重庆市",
    "广州": "广东省", "深圳": "广东省", "珠海": "广东省", "佛山": "广东省",
    "顺德": "广东省", "东莞": "广东省", "中山": "广东省", "江门": "广东省",
    "惠州": "广东省", "汕头": "广东省", "湛江": "广东省",
    "杭州": "浙江省", "宁波": "浙江省", "温州": "浙江省", "嘉兴": "浙江省",
    "湖州": "浙江省", "绍兴": "浙江省", "金华": "浙江省", "安吉": "浙江省",
    "莫干山": "浙江省", "千岛湖": "浙江省", "乌镇": "浙江省", "西塘": "浙江省",
    "舟山": "浙江省", "普陀山": "浙江省",
    "南京": "江苏省", "苏州": "江苏省", "无锡": "江苏省", "常州": "江苏省",
    "扬州": "江苏省", "镇江": "江苏省",
    "成都": "四川省", "乐山": "四川省", "九寨沟": "四川省", "峨眉山": "四川省",
    "大理": "云南省", "丽江": "云南省", "昆明": "云南省",
    "桂林": "广西壮族自治区", "阳朔": "广西壮族自治区",
    "厦门": "福建省", "福州": "福建省", "泉州": "福建省", "武夷山": "福建省",
    "青岛": "山东省", "济南": "山东省", "威海": "山东省", "烟台": "山东省",
    "三亚": "海南省", "海口": "海南省",
    "西安": "陕西省", "武汉": "湖北省", "长沙": "湖南省",
    "黄山": "安徽省", "合肥": "安徽省", "宏村": "安徽省",
    "洛阳": "河南省", "开封": "河南省",
    "大连": "辽宁省", "沈阳": "辽宁省",
    "哈尔滨": "黑龙江省", "长春": "吉林省",
    "兰州": "甘肃省", "西宁": "青海省", "乌鲁木齐": "新疆维吾尔自治区",
    "澳门": "澳门特别行政区", "香港": "香港特别行政区",
}


def _is_url_accessible(url, timeout=1.5):
    """快速HEAD请求检测URL是否可访问（过滤403/404/死链）"""
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_REQ_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 301, 302, 304)
    except Exception:
        return False


def _check_custom_image(name):
    """检查本地自定义图片 data/custom_images/{name}.{ext}，返回base64 data URI"""
    cleaned = _clean_name(name)
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = os.path.join(CUSTOM_IMG_DIR, f"{cleaned}.{ext}")
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    data = f.read()
                mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
                b64 = __import__("base64").b64encode(data).decode()
                logger.info(f"  🖼️ 使用本地图片: {cleaned}.{ext}")
                return [f"data:{mime};base64,{b64}"]
            except Exception as e:
                logger.warning(f"  ⚠️ 本地图片读取失败 {path}: {e}")
    return None


# ─── 各引擎 ────────────────────────────────────────

def _gaode(name, city="上海"):
    """高德V5 POI图片（官方API，最可靠）"""
    for _ in range(2):
        try:
            kw = urllib.request.quote(name)
            ct = urllib.request.quote(city)
            url = f"https://restapi.amap.com/v5/place/text?key={AMAP_KEY}&keywords={kw}&region={ct}&city_limit=true&page_size=1&show_fields=photos"
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
            if data.get("status") == "1" and data.get("pois"):
                photos = data["pois"][0].get("photos", [])
                if photos:
                    return [p["url"] for p in photos[:2]]
        except Exception:
            time.sleep(1)
    return []


def _wikimedia(name, limit=2):
    """Wikimedia Commons API — 免费、免Key、无水印，适合人文古迹/自然风光"""
    try:
        q = urllib.request.quote(name)
        url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={q}&gsrlimit={limit}&gsrnamespace=6&prop=imageinfo&iiprop=url&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Travel-Itinerary-Generator/3.0 (hermes-agent)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        pages = data.get("query", {}).get("pages", {})
        urls = []
        for pid, page in pages.items():
            info = page.get("imageinfo", [])
            if info and info[0].get("url", "").startswith("http"):
                u = info[0]["url"]
                # 过滤掉图标、地图等
                if not any(x in u.lower() for x in ["map", "icon", "logo", "qrcode"]):
                    urls.append(u)
                    if len(urls) >= limit:
                        break
        return urls
    except Exception as e:
        logger.debug(f"  Wikimedia搜索失败: {e}")
        return []


def _unsplash(name, limit=2):
    """Unsplash API — 免费额度、无水印、高质量摄影图。
    需要配置 UNSPLASH_ACCESS_KEY。
    """
    key = UNSPLASH_ACCESS_KEY
    if not key:
        return []
    try:
        q = urllib.request.quote(name)
        url = f"https://api.unsplash.com/search/photos?query={q}&per_page={limit}&client_id={key}"
        req = urllib.request.Request(url, headers=_REQ_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        urls = []
        for item in data.get("results", []):
            u = item.get("urls", {}).get("regular", "")
            if u:
                urls.append(u)
                if len(urls) >= limit:
                    break
        return urls
    except Exception as e:
        logger.debug(f"  Unsplash搜索失败: {e}")
        return []


def _pixabay(name, limit=2):
    """Pixabay API — 免费额度、无水印、大量高质量免费图片。
    需要配置 PIXABAY_API_KEY。
    """
    key = PIXABAY_API_KEY
    if not key:
        return []
    try:
        q = urllib.request.quote(name)
        url = f"https://pixabay.com/api/?key={key}&q={q}&per_page={limit}&safesearch=true"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        urls = []
        for item in data.get("hits", []):
            u = item.get("webformatURL", "")
            if u:
                urls.append(u)
                if len(urls) >= limit:
                    break
        return urls
    except Exception as e:
        logger.debug(f"  Pixabay搜索失败: {e}")
        return []


def _so(name, limit=2):
    """360图片搜索 — 免Key JSON接口"""
    try:
        q = urllib.request.quote(name)
        url = f"https://image.so.com/j?q={q}&src=srp&sn=0&pn=10"
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA_LIST[0],
            "Referer": "https://image.so.com/"
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            res = json.loads(r.read().decode("utf-8", errors="replace"))
        list_data = res.get("list", [])
        urls = []
        for item in list_data:
            u = item.get("img") or item.get("thumb")
            if u and str(u).startswith("http"):
                urls.append(u)
                if len(urls) >= limit:
                    break
        return urls
    except Exception:
        return []


def _baidu(name, limit=2):
    """百度图片搜索 — 免Key JSON接口，尝试多种URL字段"""
    try:
        q = urllib.request.quote(name)
        url = f"https://image.baidu.com/search/acjson?tn=resultjson_com&word={q}&pn=0&rn=6"
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA_LIST[0],
            "Referer": "https://image.baidu.com/",
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", errors="replace")
        data = json.loads(text)
        urls = []
        for item in data.get("data", []):
            if len(urls) >= limit:
                break
            # 尝试多个URL字段，优先thumbURL（最稳定）
            u = item.get("thumbURL") or item.get("middleURL") or item.get("objURL")
            if u and str(u).startswith("http"):
                urls.append(u)
        return urls
    except Exception:
        return []


def _bing(name, limit=2):
    """Bing图片搜索 — HTML解析"""
    try:
        q = urllib.request.quote(name)
        req = urllib.request.Request(f"https://www.bing.com/images/search?q={q}", headers={
            "User-Agent": _UA_LIST[0],
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="replace")
        urls = []
        # 方法1: iusc JSON
        for m in re.finditer(r'class="iusc"[^>]*?m="({.*?})"', html):
            if len(urls) >= limit:
                break
            try:
                m_str = m.group(1).replace("&quot;", '"').replace("&amp;", "&")
                d = json.loads(m_str)
                u = d.get("murl", "")
                if u.startswith("http"):
                    urls.append(u)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        # 方法2: murl JSON
        if not urls:
            murls = re.findall(r'"murl"\s*:\s*"([^"]+)"', html)
            for u in murls:
                if u.startswith("http"):
                    urls.append(u)
                    if len(urls) >= limit:
                        break
        return urls
    except Exception:
        return []


# ─── 引擎链编排 ─────────────────────────────────────

def get_photos(name, city="上海", category=""):
    """增强版图片获取：
       [本地图片] → [查询词列表] × [高德 → Wikimedia → 360 → 百度 → Bing → Pixabay → Unsplash]
       带连通性预检 + 7天缓存
    """
    # 0. 检查缓存
    cached = _load_cache(name)
    if cached is not None:
        return cached

    # 1. 本地自定义图片优先
    custom = _check_custom_image(name)
    if custom:
        return custom

    # 2. 生成渐进式查询列表
    queries = _get_fallback_queries(name, city, category)
    cleaned = _clean_name(name)
    # 确保最简名也在列表中
    if cleaned and cleaned not in queries:
        queries.append(cleaned)

    # 3. 引擎链定义（顺序执行）
    engine_chain = [
        ("Gaode", _gaode),
        ("Wikimedia", _wikimedia),
        ("360", _so),
        ("Baidu", _baidu),
        ("Bing", _bing),
        ("Pixabay", _pixabay),
        ("Unsplash", _unsplash),
    ]

    # ---- 分类URL特征过滤（防止美食景点图片混淆） ----
    _FOOD_URL_PATTERNS = ["meituan", "dianping", "restaurant", "menu", "food",
                          "ele.me", "koubei", "trip.com/restaurant", "openrice",
                          "ctrip.com/restaurant", "catering", "dish"]
    _SIGHT_URL_PATTERNS = ["mafengwo", "qunar", "tuniu", "ly.com", "ctrip.com/attraction",
                           "ctrip.com/html5/you", "travel", "sight", "scenic",
                           "trip.com/attraction", "aoyou", "booking.com/attraction"]

    def _url_matches_category(url, cat):
        """判断URL是否符合目标分类的特征"""
        url_lower = url.lower()
        if cat == "food":
            # 美食：优先匹配美食类URL特征
            is_food = any(p in url_lower for p in _FOOD_URL_PATTERNS)
            is_sight = any(p in url_lower for p in _SIGHT_URL_PATTERNS)
            if is_food:
                return 2  # 强匹配
            if is_sight:
                return -1  # 反匹配（排除）
            return 0  # 中性
        elif cat == "sight":
            is_food = any(p in url_lower for p in _FOOD_URL_PATTERNS)
            is_sight = any(p in url_lower for p in _SIGHT_URL_PATTERNS)
            if is_sight:
                return 2
            if is_food:
                return -1
            return 0
        return 0

    seen_urls = set()
    all_urls = []
    # 按category分桶存储结果，category匹配的优先
    cat_good_urls = []
    cat_neutral_urls = []

    for engine_name, engine_fn in engine_chain:
        if len(all_urls) >= 2:
            break
        for qi, query in enumerate(queries):
            if len(all_urls) >= 2:
                break
            # 分级抖动延迟：前2条查询(基础)用0.15-0.35s，后续退避查询用0.05-0.15s
            # v3.5.2: 从固定0.3-0.8s降至此，避免15条查询累积~8s纯等待
            _jitter_range = (0.15, 0.35) if qi <= 1 else (0.05, 0.15)
            time.sleep(random.uniform(*_jitter_range))

            try:
                result = engine_fn(query, city)
            except Exception:
                continue

            if result:
                for url in result:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        # 统一转HTTPS（高德store.is.autonavi.com不支持HTTPS）
                        if url.startswith("http://") and "is.autonavi.com" not in url and "store.is" not in url:
                            url = "https://" + url[7:]
                        # URL连通性预检
                        if _is_url_accessible(url):
                            # 分类匹配度检查（防止美食景点混淆）
                            cat_score = _url_matches_category(url, category)
                            if cat_score >= 2:
                                cat_good_urls.append(url)
                            elif cat_score >= 0:
                                cat_neutral_urls.append(url)
                            # cat_score < 0: 反匹配，丢弃
                            all_urls = cat_good_urls + cat_neutral_urls
                            if len(all_urls) >= 2:
                                break
                        else:
                            logger.debug(f"  🚫 URL不可达，跳过: {url[:60]}...")

            # 如果当前引擎对首个查询词返回了结果但校验后全部无效，继续换查询词
            if qi == 0 and result and not all_urls:
                logger.debug(f"  {engine_name}: 查询词'{query}'返回{len(result)}个URL但均不可达，换查询词重试")

    # 4. 保存缓存
    if all_urls:
        _save_cache(name, all_urls)

    return all_urls
