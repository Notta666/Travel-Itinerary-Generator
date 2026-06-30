"""
多引擎图片获取工具
==================
高德API(主) → 百度免Key(备) → Bing免Key(备)
带7天文件缓存
"""
import os, json, time, urllib.request, re, hashlib
from utils.config import AMAP_KEY, BASE_DIR

CACHE_DIR = os.path.join(BASE_DIR, "data", "image_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

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

def _gaode(name, city="上海"):
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

def _so(name, limit=2):
    try:
        q = urllib.request.quote(name)
        url = f"https://image.so.com/j?q={q}&src=srp&sn=0&pn=10"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
    try:
        q = urllib.request.quote(name)
        url = f"https://image.baidu.com/search/acjson?tn=resultjson_com&word={q}&pn=0&rn=4"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://image.baidu.com/",
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", errors="replace")
        data = json.loads(text)
        urls = []
        for item in data.get("data", []):
            if len(urls) >= limit: break
            u = item.get("middleURL") or item.get("thumbURL") or item.get("objURL")
            if u and str(u).startswith("http"): urls.append(u)
        return urls
    except Exception:
        return []

def _bing(name, limit=2):
    try:
        q = urllib.request.quote(name)
        req = urllib.request.Request(f"https://www.bing.com/images/search?q={q}", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="replace")
        urls = []
        for m in re.finditer(r'class="iusc"[^>]*?m="({.*?})"', html):
            if len(urls) >= limit: break
            try:
                m_str = m.group(1).replace("&quot;", '"').replace("&amp;", "&")
                d = json.loads(m_str)
                u = d.get("murl", "")
                if u.startswith("http"): urls.append(u)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        if not urls:
            murls = re.findall(r'"murl"\s*:\s*"([^"]+)"', html)
            for u in murls:
                if u.startswith("http"):
                    urls.append(u)
                    if len(urls) >= limit: break
        return urls
    except Exception:
        return []

def _clean_name(name):
    # 移除括号及其中的分店信息，如（聚福楼店）或(大良店)
    return re.sub(r'[\uff08(].*?[\uff09)]', '', name).strip()


# 城市→省份映射，用于图片搜索时加入省份上下文物提高准确率
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


def _get_search_query(name, city="", category=""):
    """构建带省份上下文的高精度搜索关键词。
    景点: '上海市上海外滩'  美食: '广东省广州陶陶居'
    """
    cleaned = _clean_name(name)
    province = _CITY_PROVINCE.get(city, "")
    # 如果城市名已包含在名称中，不加前缀
    if city and city in cleaned:
        return cleaned
    # 如果是美食，加"美食"后缀提升搜图命中
    suffix = " 美食" if category == "food" else ""
    if province:
        return f"{province}{city}{cleaned}{suffix}"
    elif city:
        return f"{city}{cleaned}{suffix}"
    return cleaned

def get_photos(name, city="上海", category=""):
    """高德→360图片→百度→Bing 降级，7天缓存"""
    cached = _load_cache(name)
    if cached is not None:
        return cached

    cleaned = _clean_name(name)
    # 高德用 city+name（利用Gaode的region限制）
    gaode_query = f"{city}{cleaned}" if city and city not in cleaned else cleaned
    # Web图片搜索引擎用 省份+城市+名称（更高精度）
    web_query = _get_search_query(name, city, category)

    urls = _gaode(gaode_query, city) or _so(web_query) or _baidu(web_query) or _bing(web_query)
    if not urls and cleaned != name:
        urls = _so(cleaned) or _baidu(cleaned) or _bing(cleaned)

    _save_cache(name, urls)
    return urls

if __name__ == "__main__":
    for poi in ["杭州西湖", "武康大楼"]:
        urls = get_photos(poi, "上海")
        print(f"{poi}: {len(urls)} 张图")
        for u in urls[:2]:
            print(f"  {u}")
