"""
高德地图 Web 服务 API 封装模块
=================================
基于高德开放平台 Web 服务 API 文档:
  - 地理编码/逆地理编码: /v3/geocode/geo, /v3/geocode/regeo
  - 搜索POI 2.0: /v5/place/text, /v5/place/around, /v5/place/detail
  - 路径规划: /v3/direction/driving
  - 输入提示: /v3/assistant/inputtips
  - 行政区域: /v3/config/district

使用方式:
    from utils.amap_api import AMapClient
    client = AMapClient()
    result = client.geocode("上海外滩")
"""

import urllib.request, urllib.parse, json, os, time, threading
from utils.config import AMAP_KEY, BASE_DIR

# ---- POI 类型码速查 ----
def load_poi_types():
    """加载本地 POI 分类码表, 返回 {typecode: name}"""
    global _POI_TYPES
    if _POI_TYPES is not None:
        return _POI_TYPES
    path = os.path.join(BASE_DIR, "data", "references", "poi_typecode.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            _POI_TYPES = json.load(f)
    else:
        _POI_TYPES = {}
    return _POI_TYPES

def poi_type_name(typecode):
    """根据 6 位 typecode 返回中文分类名, 如 050000 → 餐饮"""
    types = load_poi_types()
    # 先精确匹配, 再逐级回退
    for length in [6, 5, 4, 3, 2]:
        key = typecode[:length]
        if key in types:
            return types[key]
    return typecode

# ---- 城市 Adcode 速查 ----
_ADCODES = None
def load_adcodes():
    global _ADCODES
    if _ADCODES is not None:
        return _ADCODES
    path = os.path.join(BASE_DIR, "data", "references", "city_adcode.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            _ADCODES = json.load(f)
    else:
        _ADCODES = []
    return _ADCODES

def get_city_adcode(city_name):
    """根据城市名查 adcode, 返回第一个匹配"""
    for c in load_adcodes():
        if city_name in c['name']:
            return c['adcode']
    return None

# ---- HTTP 请求封装 ----
def _request(url, timeout=10):
    """发起 GET 请求, 返回解析后的 JSON. 捕获异常以提升稳定性"""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "0":
                info = data.get("info", "")
                if "LIMIT" in info or "QPS" in info or "OVER_LIMIT" in info:
                    time.sleep(1.5)
                    continue
            return data
        except Exception as e:
            if attempt == 2:
                # 记录 warning 而不是使整个 pipeline 崩溃
                print(f"⚠️ 高德地图 API 请求失败: {e} | URL: {url.split('?')[0]}")
                return {}
            time.sleep(1.0)
    return {}

def _build_url(endpoint, key=None, **params):
    """构造高德 API URL, 自动注入 key 并 URL 编码参数"""
    params["key"] = key or AMAP_KEY
    qs = urllib.parse.urlencode(params, encoding="utf-8")
    return f"https://restapi.amap.com{endpoint}?{qs}"

class AMapClient:
    """高德地图 API 客户端"""

    def __init__(self, key=None):
        self.key = key or AMAP_KEY
        self._last_call = 0
        self._lock = threading.Lock()

    def _rate_limit(self, min_interval=0.3):
        """线程安全限流, 防止触发 QPS 限制"""
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_call = time.time()

    def geocode(self, address, city=""):
        """
        地理编码: 地址 → 坐标，带城市偏差检测+POI搜索兜底
        """
        if city == "顺德":
            city = "佛山"
        # 动态获取目标城市的中心坐标作为参考
        expected_center = None
        if city and "," not in city:
            try:
                city_url = _build_url("/v3/geocode/geo", key=self.key, address=city, city=city, output="JSON")
                city_data = _request(city_url)
                if city_data.get("status") == "1" and city_data.get("geocodes"):
                    loc = city_data["geocodes"][0]["location"]
                    lng, lat = loc.split(",")
                    expected_center = (float(lng), float(lat))
            except Exception:
                pass

        coord = None
        # 1. 尝试常规地理编码
        for attempt in range(2):
            self._rate_limit()
            params = {"address": address, "output": "JSON"}
            if city and "," not in city:
                params["city"] = city
            url = _build_url("/v3/geocode/geo", key=self.key, **params)
            data = _request(url)
            if data.get("status") == "1" and data.get("geocodes"):
                g = data["geocodes"][0]
                level = g.get("level", "")
                # 如果返回的级别是省、市、区、县，但查询的又不是城市本身，说明是高德因找不到而回退到了市中心，需要拒掉
                if level in ["省", "市", "区", "县", "区县", "国家", "开发区"]:
                    if address not in ["广州", "佛山", "顺德", "珠海", "澳门", "东莞", "深圳", "中山", "江门", "上海", "北京", "杭州"]:
                        continue
                loc = g["location"]
                lng, lat = loc.split(",")
                coord = (float(lng), float(lat))
                # 检查偏差
                if expected_center:
                    dist = abs(coord[0] - expected_center[0]) * 111 + abs(coord[1] - expected_center[1]) * 111
                    if dist > 200:
                        coord = None  # 偏离过载，视为无效，需要兜底
                        continue
                break
            if attempt == 0:
                time.sleep(0.3)

        # 2. 如果常规地理编码失败或偏离，使用关键词搜索 place_text 进行 POI 兜底
        if not coord:
            try:
                pois = self.place_text(keywords=address, region=city, city_limit=True, page_size=1)
                if pois:
                    loc = pois[0]["location"]
                    lng, lat = loc.split(",")
                    coord = (float(lng), float(lat))
            except Exception as e:
                print(f"⚠️ POI搜索兜底失败: {e}")

        return coord

    def geocode_batch(self, names, city="", max_workers=3):
        """批量并行地理编码"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = {}
        def _geocode_one(name):
            return name, self.geocode(name, city)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_geocode_one, n): n for n in names}
            for f in as_completed(futures):
                try:
                    name, coord = f.result()
                    results[name] = coord
                except Exception:
                    results[futures[f]] = None
        return results

    def reverse_geocode(self, location, radius=1000, extensions="base"):
        """
        逆地理编码: 坐标 → 地址
        GET /v3/geocode/regeo
        location: (经度, 纬度) 或 "经度,纬度"
        radius: 搜索半径(米)
        extensions: base(基本) / all(含POI)
        返回: {formatted_address, addressComponent, pois(可选), ...}
        """
        self._rate_limit()
        if isinstance(location, (tuple, list)):
            location = f"{location[0]},{location[1]}"
        params = {"location": location, "radius": radius, "extensions": extensions, "output": "JSON"}
        url = _build_url("/v3/geocode/regeo", key=self.key, **params)
        data = _request(url)
        if data.get("status") == "1":
            return data.get("regeocode")
        return None

    def place_text(self, keywords="", types="", region="", city_limit=False, page_size=10, page_num=1):
        """
        关键字搜索 POI 2.0
        GET /v5/place/text
        keywords: 搜索关键词 (与 types 二选一必填)
        types: POI 类型码 (与 keywords 二选一必填)
        region: 城市名/adcode
        city_limit: 仅限指定城市
        返回: POI 列表
        """
        self._rate_limit()
        if region == "顺德":
            region = "佛山"
        params = {"page_size": page_size, "page_num": page_num, "output": "JSON"}
        if keywords:
            params["keywords"] = keywords
        if types:
            params["types"] = types
        if region and "," not in region:
            params["region"] = region
            if city_limit:
                params["city_limit"] = "true"
        url = _build_url("/v5/place/text", key=self.key, **params)
        data = _request(url)
        if data.get("status") == "1":
            return data.get("pois", [])
        return []

    def place_around(self, location, radius=1000, types="", keywords="", sortrule="distance", page_size=10, show_fields=""):
        """
        周边搜索 POI 2.0
        GET /v5/place/around
        location: 中心点坐标 (经度,纬度)
        radius: 搜索半径(米)
        types: POI 类型码
        keywords: 关键词过滤
        sortrule: distance(按距离) / weight(综合)
        show_fields: business(评分/人均/电话/标签等)
        返回: POI 列表
        """
        self._rate_limit()
        if isinstance(location, (tuple, list)):
            location = f"{location[0]},{location[1]}"
        params = {"location": location, "radius": radius, "sortrule": sortrule, "page_size": page_size, "output": "JSON"}
        if types:
            params["types"] = types
        if keywords:
            params["keywords"] = keywords
        if show_fields:
            params["show_fields"] = show_fields
        url = _build_url("/v5/place/around", key=self.key, **params)
        data = _request(url)
        if data.get("status") == "1":
            return data.get("pois", [])
        return []

    def place_detail(self, poi_ids):
        """
        POI ID 查询
        GET /v5/place/detail
        poi_ids: 单个 ID 或 ID 列表 (最多10个)
        返回: POI 详情列表
        """
        self._rate_limit()
        if isinstance(poi_ids, list):
            poi_ids = "|".join(poi_ids)
        params = {"id": poi_ids, "output": "JSON"}
        url = _build_url("/v5/place/detail", key=self.key, **params)
        data = _request(url)
        if data.get("status") == "1":
            return data.get("pois", [])
        return []

    def direction_driving(self, origin, destination, strategy=0):
        """
        驾车路径规划
        GET /v3/direction/driving
        origin/destination: (经度,纬度) 或 "经度,纬度"
        strategy: 路线策略(0=速度优先)
        返回: {distance, duration, tolls, paths}
        """
        self._rate_limit()
        if isinstance(origin, (tuple, list)):
            origin = f"{origin[0]},{origin[1]}"
        if isinstance(destination, (tuple, list)):
            destination = f"{destination[0]},{destination[1]}"
        params = {"origin": origin, "destination": destination, "strategy": strategy, "output": "JSON"}
        url = _build_url("/v3/direction/driving", key=self.key, **params)
        data = _request(url)
        if data.get("status") == "1" and data.get("route"):
            route = data["route"]
            if route.get("paths"):
                p = route["paths"][0]
                return {
                    "distance": int(p.get("distance", 0)),
                    "duration": int(p.get("duration", 0)),
                    "tolls": float(p.get("tolls", 0)),
                    "strategy": p.get("strategy", ""),
                    "steps": p.get("steps", []),
                }
        return None

    def inputtips(self, keywords, city=""):
        """
        输入提示 (搜索建议)
        GET /v3/assistant/inputtips
        keywords: 关键词
        city: 城市
        返回: 建议列表 [{name, address, location, id}]
        """
        self._rate_limit()
        params = {"keywords": keywords, "output": "JSON"}
        if city:
            params["city"] = city
        url = _build_url("/v3/assistant/inputtips", key=self.key, **params)
        data = _request(url)
        if data.get("status") == "1":
            return data.get("tips", [])
        return []

    # ---- 高阶组合方法 ----

    def enrich_poi(self, poi_name, city=""):
        """
        对单个POI名称进行地理编码 + 搜索丰富
        返回: {name, location, address, type, district} 或 None
        """
        # 先地理编码
        coord = self.geocode(poi_name, city)
        if not coord:
            return None
        # 再逆地理编码拿详情
        regeo = self.reverse_geocode(coord, radius=200, extensions="base")
        result = {
            "name": poi_name,
            "location": coord,
        }
        if regeo:
            ac = regeo.get("addressComponent", {})
            result["address"] = regeo.get("formatted_address", "")
            result["province"] = ac.get("province", "")
            result["district"] = ac.get("district", "")
            result["adcode"] = ac.get("adcode", "")
        return result

    def search_nearby_food(self, location, radius=500):
        """
        搜索附近餐厅(高德综合排序 = 扫街榜逻辑, 评分/人均/电话)
        返回: [{name, rating, cost, tel, tag, location, distance}]
        """
        pois = self.place_around(
            location=location,
            radius=radius,
            types="050000",
            sortrule="weight",       # 综合排序 = 扫街榜
            page_size=15,
            show_fields="business,tel,rating,cost,tag",
        )
        results = []
        for p in pois:
            biz = p.get("business", {})
            results.append({
                "name": p["name"],
                "location": p.get("location", ""),
                "distance": int(p.get("distance", 0)),
                "type": p.get("type", ""),
                "address": p.get("address", ""),
                "rating": biz.get("rating", ""),
                "cost": biz.get("cost", ""),
                "tel": biz.get("tel", ""),
                "tag": biz.get("tag", ""),
                "adcode": p.get("adcode", ""),
            })
        return results

    def distance_matrix(self, pois, strategy=0):
        """
        计算 POI 间驾车距离矩阵
        pois: [(名称, 经度, 纬度)] 列表
        返回: {matrix: [[距离,时长],...],  labels: [名称,...]}
        """
        n = len(pois)
        matrix = [[None]*n for _ in range(n)]
        labels = [p[0] for p in pois]
        coords = [(p[1], p[2]) for p in pois]
        for i in range(n):
            for j in range(i+1, n):
                r = self.direction_driving(coords[i], coords[j], strategy)
                dist = r["distance"] if r else None
                dur = r["duration"] if r else None
                matrix[i][j] = {"distance": dist, "duration": dur}
                matrix[j][i] = {"distance": dist, "duration": dur}
            matrix[i][i] = {"distance": 0, "duration": 0}
        return {"matrix": matrix, "labels": labels}

    def distance_matrix_parallel(self, pois, strategy=0, max_workers=4):
        """并行计算 POI 间驾车距离矩阵"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        n = len(pois)
        matrix = [[None]*n for _ in range(n)]
        labels = [p[0] for p in pois]
        coords = [(p[1], p[2]) for p in pois]
        pairs = [(i, j) for i in range(n) for j in range(i+1, n)]

        def _calc_pair(pair):
            i, j = pair
            r = self.direction_driving(coords[i], coords[j], strategy)
            dist = r["distance"] if r else None
            dur = r["duration"] if r else None
            return i, j, dist, dur

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_calc_pair, p) for p in pairs]
            for f in as_completed(futures):
                try:
                    i, j, dist, dur = f.result()
                    matrix[i][j] = {"distance": dist, "duration": dur}
                    matrix[j][i] = {"distance": dist, "duration": dur}
                except Exception:
                    pass
        for i in range(n):
            matrix[i][i] = {"distance": 0, "duration": 0}
        return {"matrix": matrix, "labels": labels}

    def enrich_poi_batch(self, poi_names, city="", max_workers=4):
        """批量并行POI数据丰富"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(self.enrich_poi, name, city): name for name in poi_names}
            for f in as_completed(futures):
                name = futures[f]
                try:
                    results[name] = f.result()
                except Exception:
                    results[name] = None
        return results


    def get_ip_location(self):
        """
        通过 IP 定位获取用户当前所在城市
        """
        self._rate_limit()
        try:
            url = f"https://restapi.amap.com/v3/ip?key={self.key}"
            data = _request(url)
            if data.get("status") == "1" and data.get("city"):
                city = data["city"]
                if isinstance(city, str):
                    city = city.replace("市", "").replace("省", "")
                return city
        except Exception as e:
            print(f"⚠️ IP定位失败: {e}")
        return None


# ---- 独立测试 ----
if __name__ == "__main__":
    c = AMapClient()
    print("=== 地理编码 ===")
    loc = c.geocode("上海外滩")
    print(f"  外滩 → {loc}")

    print("\n=== 逆地理编码 ===")
    re = c.reverse_geocode(loc, extensions="all")
    print(f"  {re['formatted_address']}")
    if re.get("pois"):
        for p in re["pois"][:3]:
            print(f"  附近: {p['name']} | {p.get('distance','')}m")

    print("\n=== V5关键字搜索 ===")
    pois = c.place_text(keywords="东方明珠", region="上海", city_limit=True, page_size=3)
    for p in pois:
        print(f"  {p['name']} | {p['location']}")

    print("\n=== 周边搜索(带评分) ===")
    foods = c.search_nearby_food(loc, radius=500)
    for f in foods[:5]:
        print(f"  {f['name']:20s} 评分{f['rating']:4s} 人均¥{f['cost']:5s}  {f['distance']}m")

    print("\n=== 路径规划 ===")
    r = c.direction_driving((121.473701,31.230416), (121.499718,31.239703))
    print(f"  人民广场→东方明珠: {r['distance']}m / {r['duration']//60}min")

    print("\n=== POI类型码查表 ===")
    print(f"  050000 → {poi_type_name('050000')}")
    print(f"  110000 → {poi_type_name('110000')}")
    print(f"  050300 → {poi_type_name('050300')}")
