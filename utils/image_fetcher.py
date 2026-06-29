"""
多引擎图片获取工具
==================
高德API(主) → 百度免Key(备) → Bing免Key(备)
带7天文件缓存
"""
import os, json, time, urllib.request, re, hashlib

try:
    from utils.amap_api import AMAP_KEY
except ImportError:
    try:
        from amap_api import AMAP_KEY
    except ImportError:
        import os
        AMAP_KEY = os.environ.get("AMAP_KEY", "")
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "image_cache")
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
        except:
            pass
    return None

def _save_cache(name, urls):
    try:
        with open(_cache_path(name), "w") as f:
            json.dump({"urls": urls, "ts": time.time()}, f)
    except:
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
        except:
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
    except:
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
    except:
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
            except: continue
        if not urls:
            murls = re.findall(r'"murl"\s*:\s*"([^"]+)"', html)
            for u in murls:
                if u.startswith("http"):
                    urls.append(u)
                    if len(urls) >= limit: break
        return urls
    except:
        return []

def _clean_name(name):
    import re
    # 移除括号及其中的分店信息，如（聚福楼店）或(大良店)
    return re.sub(r'[\uff08(].*?[\uff09)]', '', name).strip()

def get_photos(name, city="上海"):
    """高德→360图片→百度→Bing 降级，7天缓存"""
    cached = _load_cache(name)
    if cached is not None:
        return cached

    cleaned = _clean_name(name)
    search_name = f"{city}{cleaned}" if city and city not in cleaned else cleaned

    urls = _gaode(name, city) or _so(search_name) or _baidu(search_name) or _bing(search_name)
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
