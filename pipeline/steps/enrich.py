import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

def step_4_enrich(context):
    """逆地理编码拿地址 → 小红书美食列表对接高德坐标验证 (批量并行)"""
    print(f"\n{'='*50}")
    print(f"Step 4/9: POI丰富 + 美食对接 🍽️ (批量并行)")
    print(f"{'='*50}")
    enriched = []
    city = context["city"]
    all_food = []

    from concurrent.futures import ThreadPoolExecutor, as_completed
    enrich_results = {}

    def _enrich_by_loc(poi):
        name = poi["name"]
        loc = poi["location"]
        regeo = amap.reverse_geocode(loc, radius=500, extensions="base")
        result = {"name": name, "location": loc}
        if regeo:
            ac = regeo.get("addressComponent", {})
            result["address"] = regeo.get("formatted_address", "")
            result["province"] = ac.get("province", "")
            result["district"] = ac.get("district", "")
            result["adcode"] = ac.get("adcode", "")
        return name, result

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_enrich_by_loc, poi): poi["name"] for poi in context["poi_geocoded"]}
        for f in as_completed(futures):
            name = futures[f]
            try:
                n, res = f.result()
                enrich_results[n] = res
            except Exception:
                enrich_results[name] = None

    sight_meta = {}
    xhs_sights = context.get("xhs_pois", {}).get("sights", [])
    for s in xhs_sights:
        sight_meta[s["name"]] = {
            "complaints": s.get("complaints", "无"),
            "highlights": s.get("highlights", "无")
        }

    for poi in context["poi_geocoded"]:
        name = poi["name"]
        loc = poi["location"]
        detail = enrich_results.get(name)
        poi_info = {
            "name": name,
            "location": list(loc),
            "address": detail.get("address", "") if detail else "",
            "district": detail.get("district", "") if detail else "",
            "nearby_food": [],
            "complaints": sight_meta.get(name, {}).get("complaints", "无"),
            "highlights": sight_meta.get(name, {}).get("highlights", "无")
        }
        enriched.append(poi_info)
        print(f"  ✅ {name:20s} | {poi_info.get('address','')[:30]}")

    xhs_foods = context.get("xhs_food_data", [])
    prefs = context.get("preferences", {})
    foods_to_geocode = []
    for f in xhs_foods:
        name = f.get("name", "")
        if name and name not in foods_to_geocode:
            budget_per = prefs.get("_budget_parsed", (None, None))
            daily_budget = budget_per[0]
            cuisines_price = {"小吃": 20, "面": 25, "咖啡": 30, "快餐": 35,
                           "川菜": 60, "湘菜": 55, "粤菜": 80, "杭帮": 70, "本帮": 65,
                           "日料": 120, "西餐": 150, "火锅": 100, "烧烤": 80}
            est_cost = cuisines_price.get(f.get("cuisine", "")[:2], 50)
            if daily_budget and est_cost > daily_budget * 1.5:
                continue
            foods_to_geocode.append(name)

    food_coords = {}
    if foods_to_geocode:
        food_city_map = context.setdefault("food_city_map", {})
        cities_list = [c.strip() for c in city.replace("，", ",").split(",") if c.strip()]

        missing_foods = [n for n in foods_to_geocode if n not in food_city_map]
        if missing_foods and len(cities_list) > 1:
            print(f"  🧠 检测到有 {len(missing_foods)} 家餐厅缺失城市归属信息，启动 LLM 快速识别...")
            map_prompt = f"""你是一个旅行美食专家。
请根据目的地城市列表 {cities_list}，判断以下餐厅名称分别属于哪一个目的地城市（必须只能是列表中的一个，如果餐厅不在任何一个城市，请选择最接近的目的城市）：
餐厅列表：{missing_foods}

输出格式（纯JSON，不要额外文字，键为餐厅名，值为对应的城市名）：
{{
  "餐厅1": "城市A",
  "餐厅2": "城市B"
}}"""
            try:
                from utils.llm import call_deepseek
                map_res = call_deepseek("美食专家。返回纯JSON。", map_prompt, temperature=0.1, max_tokens=1000)
                if isinstance(map_res, dict):
                    for k, v in map_res.items():
                        if k in missing_foods and v in cities_list:
                            food_city_map[k] = v
                    print(f"     ✅ 识别完成: {map_res}")
            except Exception as e:
                print(f"     ⚠️ LLM 城市识别失败: {e}")

        def _smart_geocode_food(name):
            f_city = food_city_map.get(name, "").strip()
            if f_city:
                for suffix in ["市", "区", "县"]:
                    if f_city.endswith(suffix) and len(f_city) > 2:
                        f_city = f_city[:-1]
            if f_city == "顺德":
                f_city = "佛山"
            candidate_cities = []
            if f_city:
                candidate_cities.append(f_city)
            for c in cities_list:
                if c not in candidate_cities:
                    candidate_cities.append(c)
                    if c == "顺德" and "佛山" not in candidate_cities:
                        candidate_cities.append("佛山")

            for c in candidate_cities:
                q_name = f"{c}{name}" if c not in name else name
                coord = amap.geocode(q_name, c)
                if coord:
                    c_coord = amap.geocode(c)
                    if c_coord:
                        dist = abs(coord[0] - c_coord[0]) * 111 + abs(coord[1] - c_coord[1]) * 111
                        if dist <= 50:
                            return name, coord

            for c in candidate_cities:
                try:
                    pois = amap.place_text(keywords=name, region=c, city_limit=True, page_size=1)
                    if pois:
                        loc = pois[0]["location"]
                        lng, lat = loc.split(",")
                        return name, (float(lng), float(lat))
                except Exception:
                    pass

            return name, amap.geocode(name)

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(_smart_geocode_food, n): n for n in foods_to_geocode}
            for f in as_completed(futures):
                try:
                    name, coord = f.result()
                    if coord:
                        food_coords[name] = coord
                except Exception:
                    pass

    for f in xhs_foods:
        name = f.get("name", "")
        if name in foods_to_geocode:
            coord = food_coords.get(name)
            all_food.append({
                "name": name,
                "cuisine": f.get("cuisine", ""),
                "reason": f.get("reason", ""),
                "rating": "",
                "location": list(coord) if coord else [121.47, 31.23],
                "complaints": f.get("complaints", "无"),
                "highlights": f.get("highlights", "无")
            })

    if all_food:
        print(f"  🍴 小红书推荐美食: {len(all_food)} 家")
        for f in all_food[:5]:
            print(f"     {f['name']} — {f.get('cuisine','')}")
    else:
        print(f"  ⚠️ 小红书无美食数据")

    context["poi_enriched"] = enriched
    context["food_recommendations"] = all_food[:15]
    print(f"  完成: {len(enriched)}个POI + {len(all_food[:15])}家推荐餐厅")
    return context
