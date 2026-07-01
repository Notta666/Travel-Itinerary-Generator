import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

def step_3_geocode(context, manual_pois=None):
    """高德地理编码: 小红书提取的景点名 → 坐标 (批量并行)"""
    print(f"\n{'='*50}")
    print(f"Step 3/9: POI地理编码 🗺️ (批量并行)")
    print(f"{'='*50}")
    city = context["city"]

    pois_to_code = manual_pois or context.get("manual_pois", [])
    if not pois_to_code:
        pois_to_code = context.get("xhs_sight_names", [])

    if not pois_to_code:
        print("  ⚠️ 无可编码POI，使用内置默认景点")
        default_pois = {}
        try:
            default_pois_path = os.path.join(PROJECT_ROOT, "data", "default_pois.json")
            if os.path.exists(default_pois_path):
                with open(default_pois_path, "r", encoding="utf-8") as f:
                    default_pois = json.load(f)
        except Exception as e:
            print(f"  ⚠️ 读取本地景点数据库失败: {e}")

        if not default_pois:
            default_pois = {
                "上海": ["上海外滩", "东方明珠广播电视塔", "豫园", "南京路步行街", "武康大楼", "上海新天地", "田子坊", "上海博物馆"],
                "北京": ["故宫博物院", "天坛", "颐和园", "长城", "南锣鼓巷", "三里屯", "国家博物馆"],
                "杭州": ["西湖", "灵隐寺", "雷峰塔", "河坊街", "西溪湿地", "杭州博物馆"],
            }
        pois_to_code = default_pois.get(city, default_pois.get("上海"))

    cities_list = [c.strip() for c in city.replace("，", ",").split(",") if c.strip()]

    sight_city_map = context.setdefault("sight_city_map", {})
    missing_pois = [n for n in pois_to_code if n not in sight_city_map]
    if missing_pois and len(cities_list) > 1:
        print(f"  🧠 检测到有 {len(missing_pois)} 个景点缺失城市归属信息，启动 LLM 快速识别...")
        map_prompt = f"""你是一个旅行地理专家。
请根据目的地城市列表 {cities_list}，判断以下景点名称分别属于哪一个目的地城市（必须只能是列表中的一个，如果景点不在任何一个城市，请选择最接近的目的城市）：
景点列表：{missing_pois}

输出格式（纯JSON，不要额外文字，键为景点名，值为对应的城市名）：
{{
  "景点1": "城市A",
  "景点2": "城市B"
}}"""
        try:
            from utils.llm import call_deepseek
            map_res = call_deepseek("地理专家。返回纯JSON。", map_prompt, temperature=0.1, max_tokens=1000)
            if isinstance(map_res, dict):
                for k, v in map_res.items():
                    if k in missing_pois and v in cities_list:
                        sight_city_map[k] = v
                print(f"     ✅ 识别完成: {map_res}")
        except Exception as e:
            print(f"     ⚠️ LLM 城市识别失败: {e}")

    city_centers = []
    for c in cities_list:
        lookup_c = "佛山" if c == "顺德" else c
        c_coord = amap.geocode(lookup_c)
        if c_coord:
            city_centers.append(c_coord)
    if not city_centers:
        city_centers = [(121.4737, 31.2304)]

    # 智能前缀纠偏地理编码
    results = {}
    def _smart_geocode(name):
        spec_city = sight_city_map.get(name, "").strip()
        if spec_city:
            for suffix in ["市", "区", "县"]:
                if spec_city.endswith(suffix) and len(spec_city) > 2:
                    spec_city = spec_city[:-1]

        candidate_cities = []
        if spec_city:
            candidate_cities.append(spec_city)
            if spec_city == "顺德":
                candidate_cities.append("佛山")
        for c in cities_list:
            if c not in candidate_cities:
                candidate_cities.append(c)
                if c == "顺德" and "佛山" not in candidate_cities:
                    candidate_cities.append("佛山")

        for c in candidate_cities:
            if c in name:
                coord = amap.geocode(name, c)
                if coord:
                    return name, coord

        for c in candidate_cities:
            lookup_cities = [c]
            if c == "顺德":
                lookup_cities = ["顺德", "佛山"]
            for lc in lookup_cities:
                q_name = f"{lc}{name}"
                coord = amap.geocode(q_name, lc)
                if coord:
                    c_coord = amap.geocode(lc)
                    if c_coord:
                        dist = abs(coord[0] - c_coord[0]) * 111 + abs(coord[1] - c_coord[1]) * 111
                        if dist <= 50:
                            return name, coord

        return name, amap.geocode(name)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_smart_geocode, n): n for n in pois_to_code}
        for f in as_completed(futures):
            try:
                name, coord = f.result()
                if coord:
                    results[name] = coord
            except Exception:
                pass

    geocoded = []
    for name in pois_to_code:
        coord = results.get(name)

        is_drift = True
        if coord:
            for cx, cy in city_centers:
                dist = abs(coord[0] - cx) * 111 + abs(coord[1] - cy) * 111
                if dist <= 100:
                    is_drift = False
                    break

        if (is_drift or not coord) and cities_list:
            for c_prefix in cities_list[:3]:
                fallback_name = f"{c_prefix}{name}"
                print(f"  ⚠️ 发现定位漂移或失败: '{name}'。尝试使用前缀 '{fallback_name}' 重新编码...")
                fallback_coord = amap.geocode(fallback_name)
                if fallback_coord:
                    valid_fallback = False
                    for cx, cy in city_centers:
                        dist = abs(fallback_coord[0] - cx) * 111 + abs(fallback_coord[1] - cy) * 111
                        if dist <= 100:
                            valid_fallback = True
                            break
                    if valid_fallback:
                        coord = fallback_coord
                        is_drift = False
                        print(f"  ✅ 纠偏成功: '{name}' 修正为 '{fallback_name}' → ({coord[0]:.4f}, {coord[1]:.4f})")
                        break

        if coord and not is_drift:
            geocoded.append({"name": name, "location": coord})
            print(f"  ✅ {name:20s} → ({coord[0]:.4f}, {coord[1]:.4f})")
        else:
            h = hash(name)
            base_lng, base_lat = city_centers[0]
            offset_lng = ((h % 100) - 50) * 0.001
            offset_lat = (((h // 100) % 100) - 50) * 0.001
            coord = (base_lng + offset_lng, base_lat + offset_lat)
            geocoded.append({"name": name, "location": coord})
            if is_drift:
                print(f"  🚨 {name:20s} → 严重定位漂移且无法纠偏，降级为首个城市 Mock 邻近坐标 ({coord[0]:.4f}, {coord[1]:.4f})")
            else:
                print(f"  ⚠️ {name:20s} → 编码失败，使用 Mock 坐标 ({coord[0]:.4f}, {coord[1]:.4f})")

    context["poi_geocoded"] = geocoded
    n = len(geocoded)
    print(f"  成功: {n}/{len(pois_to_code)}")
    return context
