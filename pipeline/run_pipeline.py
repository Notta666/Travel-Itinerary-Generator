"""
Travel-Itinerary-Generator · Pipeline 固定流程
================================================
Usage:
    python pipeline/run_pipeline.py --city 上海 --days 2
    python pipeline/run_pipeline.py --city 上海 --days 2 --pois "外滩,豫园"
    python pipeline/run_pipeline.py --city 上海 --days 2 --research

步骤列表（9步工序链）:
"""
import sys, os, json, argparse, time, copy, threading, signal, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient, poi_type_name
from utils.research import XiaoHongShu
from utils.llm import call_deepseek
BASE = PROJECT_ROOT
BROCHURE_ENABLED = True  # 生成图文手册

amap = AMapClient()
xhs = XiaoHongShu()

# ====================================================================
# 已提取的步骤模块
# ====================================================================
from pipeline.steps.research import step_2_research
from pipeline.steps.planner import step_6_plan_itinerary

# ====================================================================
# 性能计时器 + 停止控制
# ====================================================================
_stop_requested = False
_step_timings = []  # [(step_name, elapsed_seconds), ...]


class StepTimer:
    """上下文管理器：自动计时每个步骤并记录耗时"""
    def __init__(self, name):
        self.name = name
    def __enter__(self):
        self.t0 = time.time()
        return self
    def __exit__(self, *_):
        elapsed = time.time() - self.t0
        _step_timings.append((self.name, elapsed))
        print(f"  ⏱️  {self.name} 耗时: {elapsed:.1f}s")


class PipelineStoppedError(Exception):
    """用户确认停止时抛出"""
    pass


def _check_stop(step_name=""):
    """每步执行前检查是否需要停止"""
    global _stop_requested
    if _stop_requested:
        raise PipelineStoppedError(f"用户在 {step_name} 前确认停止")


def _signal_handler(signum, frame):
    """Ctrl+C 信号处理器：二次确认交互"""
    global _stop_requested
    print(f"\n\n{'='*50}")
    print("⚠️  检测到中断请求！")
    print(f"{'='*50}")
    try:
        answer = input("确认要停止生成吗？已完成的步骤将保留。(y/n): ").strip().lower()
        if answer in ('y', 'yes', '是'):
            _stop_requested = True
            print("🛑 已确认停止，正在保存已有成果...")
        else:
            print("▶️  继续生成中...")
    except (EOFError, KeyboardInterrupt):
        _stop_requested = True
        print("\n🛑 强制停止")


def _print_timing_summary():
    """打印各步骤耗时汇总表"""
    if not _step_timings:
        return
    total = sum(t for _, t in _step_timings)
    print(f"\n{'='*55}")
    print(f"⏱️  各步骤耗时汇总")
    print(f"{'='*55}")
    print(f"{'步骤':<25s} {'耗时':>8s} {'占比':>6s}")
    print(f"{'-'*25} {'-'*8} {'-'*6}")
    for name, elapsed in _step_timings:
        pct = elapsed / total * 100 if total > 0 else 0
        bar = '█' * int(pct / 5) + '░' * (20 - int(pct / 5))
        print(f"  {name:<23s} {elapsed:>6.1f}s {pct:>5.1f}%  {bar}")
    print(f"{'-'*25} {'-'*8} {'-'*6}")
    print(f"  {'总计':<23s} {total:>6.1f}s  100%")
    print(f"{'='*55}")


# ====================================================================
# Step 1: 参数初始化
# ====================================================================
def step_1_init(city, days=2, preferences=None, manual_pois=None, multi_cities=None):
    """读取城市、天数、手动POI、偏好"""
    m_cities = multi_cities or (preferences.get("multi_cities") if preferences else None)
    if m_cities:
        city = m_cities[0]

    print(f"\n{'='*50}")
    print(f"Step 1/9: 初始化  — 城市={city}, 天数={days}")
    print(f"{'='*50}")

    start_date = None
    if preferences:
        start_date = preferences.get("start_date")
    if not start_date:
        start_date = datetime.date.today().strftime("%Y-%m-%d")

    context = {
        "city": city,
        "days": days,
        "start_date": start_date,
        "preferences": preferences or {},
        "manual_pois": manual_pois or [],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "poi_raw": [],
        "poi_geocoded": [],
        "poi_enriched": [],
        "food_recommendations": [],
        "distance_matrix": {},
        "itinerary": None,
        "html_path": None,
        "report_path": None,
        "brochure_path": None,
        "multi_cities": m_cities or [],
    }
    n = len(manual_pois) if manual_pois else 0
    print(f"  城市: {city} | 天数: {days} | 出行日期: {start_date}")
    print(f"  手动POI: {n} 个" if n else "  POI来源: 小红书调研")

    # 更新用户偏好记忆
    try:
        from utils.user_prefs import update_from_goal, get_suggestions
        update_from_goal(city, preferences or {})
        if preferences:
            suggestions = get_suggestions(city)
            for key in ("transport", "preference", "budget"):
                if not preferences.get(key) and suggestions.get(key):
                    preferences[key] = suggestions[key]
    except Exception:
        pass

    return context


# ====================================================================
# Step 3: POI地理编码（小红书景点 → 高德坐标）
# ====================================================================
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
        print("  ⚠️ 无可编码POI，使用默认景点")
        default_pois = {
            "上海": ["上海外滩", "东方明珠广播电视塔", "豫园", "南京路步行街", "武康大楼", "上海新天地", "田子坊", "上海博物馆"],
            "北京": ["故宫博物院", "天坛", "颐和园", "长城", "南锣鼓巷", "三里屯", "国家博物馆"],
            "杭州": ["西湖", "灵隐寺", "雷峰塔", "河坊街", "西溪湿地", "杭州博物馆"],
        }
        pois_to_code = default_pois.get(city, default_pois["上海"])

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


# ====================================================================
# Step 4: POI数据丰富 + 美食对接（小红书→高德验证）
# ====================================================================
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


# ====================================================================
# Step 5: 距离矩阵（驾车路线规划）
# ====================================================================
def step_5_distance_matrix(context):
    """高德驾车路径规划API: 计算POI间距离/时长"""
    print(f"\n{'='*50}")
    print(f"Step 5/9: 距离矩阵 📏")
    print(f"{'='*50}")
    pois = context["poi_enriched"]
    if len(pois) < 2:
        print("  ⚠️ POI不足, 跳过")
        return context
    tuples = [(p["name"], p["location"][0], p["location"][1]) for p in pois]
    if hasattr(amap, 'distance_matrix_parallel'):
        matrix = amap.distance_matrix_parallel(tuples, max_workers=4)
    else:
        matrix = amap.distance_matrix(tuples)
    context["distance_matrix"] = matrix
    labels, mat = matrix["labels"], matrix["matrix"]
    print(f"  矩阵: {len(labels)}x{len(labels)}")
    for i in range(len(labels)):
        for j in range(i+1, min(i+3, len(labels))):
            d = mat[i][j]
            if d and d.get("distance"):
                print(f"    {labels[i][:12]:12s} -> {labels[j][:12]:12s}  {d['distance']/1000:.1f}km / {d['duration']//60}min")
    return context


# ====================================================================
# Step 5.5: 飞猪 FlyAI 实时物价查询（可选）
# ====================================================================
def step_55_flyai_pricing(context):
    """飞猪 FlyAI 实时机票/高铁/酒店价格查询（并行）

    数据写入 context["flyai_prices"]:
      flight/train/hotel: {items, source, cheapest}
      available: True/False

    如果 FlyAI 不可用或查询失败，静默降级（当前固定百分比算法不受影响）。
    """
    print(f"\n{'='*50}")
    print(f"Step 5.5/9: 飞猪 FlyAI 实时物价查询 ✈️🚄🏨")
    print(f"{'='*50}")

    try:
        from utils.flyai_api import FlyAIApiClient
        client = FlyAIApiClient()
        if not client.check_environment():
            print("  ⚠️ FlyAI CLI 不可用，跳过实时物价查询")
            context["flyai_prices"] = {"available": False}
            return context
    except ImportError:
        print("  ⚠️ utils.flyai_api 未安装，跳过实时物价查询")
        context["flyai_prices"] = {"available": False}
        return context
    except Exception as e:
        print(f"  ⚠️ FlyAI 初始化失败: {e}")
        context["flyai_prices"] = {"available": False}
        return context

    city = context["city"]
    prefs = context.get("preferences", {})
    start_city = prefs.get("start_city", "")
    start_date = context.get("start_date", "")
    days = context.get("days", 2)
    transport = prefs.get("transport", "")
    people = prefs.get("people_count", 2)
    hotel_budget_min = prefs.get("hotel_budget_min", 300)
    hotel_budget_max = prefs.get("hotel_budget_max", 500)

    if not start_city or not start_date:
        print("  ⚠️ 缺少出发城市或日期，跳过实时物价查询")
        context["flyai_prices"] = {"available": False}
        return context

    from datetime import datetime, timedelta
    try:
        dep_date = datetime.strptime(start_date, "%Y-%m-%d")
        ret_date = (dep_date + timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        ret_date = ""

    results = {}

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {}

        if transport and dep_date:
            if transport in ("飞机", "flight"):
                futures["flight"] = ex.submit(
                    client.query_flight, start_city, city, start_date
                )
            elif transport in ("高铁", "train", "动车"):
                futures["train"] = ex.submit(
                    client.query_train, start_city, city, start_date
                )

        futures["hotel"] = ex.submit(
            client.query_hotel, city, start_date,
            ret_date or start_date, None, hotel_budget_max if hotel_budget_max else None, people
        )

        src_labels = {"live": "飞猪实时", "cache": "缓存"}
        for key, future in futures.items():
            try:
                items, source = future.result()
                if items:
                    # 酒店按用户选择的预算区间过滤
                    if key == "hotel" and (hotel_budget_min or hotel_budget_max):
                        filtered = []
                        for item in items:
                            p = item.get("price", 0)
                            if hotel_budget_min and p < hotel_budget_min:
                                continue
                            if hotel_budget_max and p > hotel_budget_max:
                                continue
                            filtered.append(item)
                        if filtered:
                            items = filtered
                            print(f"  🏨 预算过滤: {len(items)}/{len(filtered)} 家在 ¥{hotel_budget_min}~{hotel_budget_max}/晚")
                        else:
                            print(f"  ⚠️ 无 ¥{hotel_budget_min}~{hotel_budget_max} 酒店，显示全部")
                    cheapest = min(items, key=lambda x: x["price"])
                    results[key] = {
                        "items": items, "source": source,
                        "cheapest": cheapest["price"], "count": len(items),
                    }
                    unit = {"flight": "/人", "train": "/人"}.get(key, "")
                    label = src_labels.get(source, source)
                    # 调试：记录酒店 API 返回的可选字段质量
                    if key == "hotel" and items:
                        h0 = items[0]
                        debug_fields = {k: h0.get(k, "❌缺失") for k in ("star", "decoration_time", "main_pic", "jump_url", "rating")}
                        print(f"  🔍 酒店字段样例: {debug_fields}")
                else:
                    results[key] = {"items": [], "source": "fail", "cheapest": None, "count": 0}
                    print(f"  ⚠️ {key}: 查询失败")
            except Exception as e:
                results[key] = {"items": [], "source": "error", "cheapest": None, "count": 0}
                print(f"  ⚠️ {key}: 异常: {e}")

    results["available"] = bool(results)
    context["flyai_prices"] = results
    n = sum(1 for v in results.values() if isinstance(v, dict) and v.get("cheapest"))
    print(f"  ✅ FlyAI 物价查询完成: {n} 品类有数据")
    return context


# ====================================================================
# Step 5.6: 交通方式重评估（基于实际距离 + 实时票价）
# ====================================================================
def step_56_transport_decision(context, amap=None):
    """基于实际地理位置和实时票价，用 LLM 综合决策最佳交通方式。

    覆盖 Step 0 Goal解析中 LLM 凭常识猜测的 transport 值。
    决策因素（按权重）：
      1. start_city → city 的实际驾车距离
      2. 机票/高铁实时最低价（FlyAI 数据）
      3. 预算约束
      4. 出行人数
    """
    print(f"\n{'='*50}")
    print(f"Step 5.6/9: 交通方式重评估 🚗✈️🚄")
    print(f"{'='*50}")

    prefs = context.get("preferences", {})
    current_transport = prefs.get("transport", "").strip()
    start_city = prefs.get("start_city", "")
    city = context.get("city", "")
    people_count = prefs.get("people_count", 2)
    budget = prefs.get("budget", "")
    flyai = context.get("flyai_prices", {})

    if not start_city or not city:
        print("  ⏭️  缺出发城市或目标城市，跳过交通重评估")
        return context

    if not amap:
        from utils.amap_api import AMapClient
        amap = AMapClient()

    # 1. 计算实际距离
    start_coord = amap.geocode(start_city)
    dest_coord = amap.geocode(city)
    if not start_coord or not dest_coord:
        print("  ⚠️  地理编码失败，跳过交通重评估")
        return context

    # Haversine 直线距离
    import math
    R = 6371
    lng1, lat1 = math.radians(start_coord[0]), math.radians(start_coord[1])
    lng2, lat2 = math.radians(dest_coord[0]), math.radians(dest_coord[1])
    dlng, dlat = lng2 - lng1, lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    line_dist = R * 2 * math.asin(math.sqrt(a))

    # 驾车距离（高德 API 更准）
    drive_dist, drive_dur = line_dist, line_dist / 80 * 60  # 默认80km/h
    try:
        route = amap.direction_driving(start_coord, dest_coord)
        if route:
            drive_dist = route.get("distance", drive_dist * 1000) / 1000
            drive_dur = route.get("duration", drive_dur * 60) / 60
    except Exception:
        pass

    print(f"  📏 直线距离: {line_dist:.0f}km")
    print(f"  🚗 驾车距离: {drive_dist:.0f}km / {drive_dur:.0f}min")

    # 2. 提取实时票价信息
    flight_price = None
    train_price = None
    if flyai.get("available"):
        fd = flyai.get("flight", {})
        if fd.get("cheapest"):
            flight_price = fd["cheapest"]
        td = flyai.get("train", {})
        if td.get("cheapest"):
            train_price = td["cheapest"]

    # 3. LLM 综合决策
    from utils.llm import call_deepseek
    prompt = f"""你是一个交通规划专家。根据以下信息，为本次旅行推荐最佳交通方式。

【出发地】{start_city}
【目的地】{city}
【驾车距离】{drive_dist:.0f}km（约 {drive_dur:.0f} 分钟）
【出行人数】{people_count} 人
【预算】{budget or '未指定'}
【机票最低价】{'¥' + str(flight_price) + '/人' if flight_price else '无数据'}
【高铁最低价】{'¥' + str(train_price) + '/人' if train_price else '无数据'}
【原定方式】{current_transport or '未指定'}

决策规则：
1. < 150km：推荐自驾（最灵活）
2. 150-400km：推荐高铁（省时省力），也可自驾（有车的话）
3. 400-900km：推荐高铁（性价比最高），如果机票特别便宜且机场方便可坐飞机
4. > 900km：推荐飞机（否则太累），如果价格过高也可考虑高铁卧铺
5. 有实时票价数据时，优先选择性价比最高的方式：
   - 机票¥{flight_price or '?'}/人 vs 高铁¥{train_price or '?'}/人，算总价（×{people_count}人）
6. 预算有限时，优先选最省钱的合理方式

输出格式（纯JSON，无需多余文字）：
{{"transport": "自驾|高铁|飞机", "reason": "不超过30字的原因说明"}}"""

    try:
        result = call_deepseek("交通规划专家。返回纯JSON。", prompt, temperature=0.2, max_tokens=500)
        if isinstance(result, dict):
            new_transport = result.get("transport", "").strip()
            reason = result.get("reason", "")
            if new_transport in ("自驾", "高铁", "飞机"):
                old = current_transport or "未指定"
                print(f"  🚗 原定: {old} → 🎯 推荐: {new_transport}（{reason}）")
                if current_transport and new_transport != current_transport:
                    print(f"  🔄 覆盖原定交通方式: {old} → {new_transport}")
                elif not current_transport:
                    print(f"  ✅ 自动决策交通方式: {new_transport}")
                prefs["transport"] = new_transport
                context["preferences"] = prefs
                # 更新 flyai 查询：如果决策变了，重新查询正确的品类
                if flyai.get("available"):
                    if new_transport == "飞机" and not flyai.get("flight", {}).get("items"):
                        print(f"  🔄 追加查询机票价格...")
                        from utils.flyai_api import FlyAIApiClient
                        fc = FlyAIApiClient()
                        items, src = fc.query_flight(start_city, city, context.get("start_date", ""))
                        if items:
                            flyai["flight"] = {"items": items, "source": src, "cheapest": items[0]["price"], "count": len(items)}
                            context["flyai_prices"] = flyai
                    elif new_transport == "高铁" and not flyai.get("train", {}).get("items"):
                        print(f"  🔄 追加查询高铁价格...")
                        from utils.flyai_api import FlyAIApiClient
                        fc = FlyAIApiClient()
                        items, src = fc.query_train(start_city, city, context.get("start_date", ""))
                        if items:
                            flyai["train"] = {"items": items, "source": src, "cheapest": items[0]["price"], "count": len(items)}
                            context["flyai_prices"] = flyai
            else:
                print(f"  ⚠️ LLM 返回异常交通方式: {new_transport}，保留原值")
        else:
            print(f"  ⚠️ LLM 返回非 dict: {result}")
    except Exception as e:
        print(f"  ⚠️ LLM 交通决策失败: {e}，保留原方式")

    print(f"  ✅ 最终交通方式: {prefs.get('transport', '未指定')}")
    return context


# ====================================================================
# Step 7: 景点门票价格查询（FlyAI 级联提取）
# ====================================================================
def step_7_query_tickets(context):
    """对已经规划好的行程中的每个景点，调用 FlyAI 查询门票价格

    级联路径：POI描述正则 → ai-search语义搜索 → 百分比估算降级
    结果写入 context["flyai_prices"]["tickets"]:

        {"西湖": {"price_min": 60, "price_max": 60, "source": "regex"},
         "灵隐寺": {"price_min": 45, "price_max": 75, "source": "ai_search"},
         ...}

    FlyAI 不可用或失败时静默跳过，不影响其他步骤。
    """
    print(f"\n{'='*50}")
    print(f"Step 7/9: 景点门票价格查询 🎫")
    print(f"{'='*50}")

    flyai = context.get("flyai_prices", {})
    if not flyai.get("available"):
        print("  ⏭️  跳过门票查询（FlyAI 不可用或无数据）")
        return context

    from utils.flyai_api import FlyAIApiClient
    client = FlyAIApiClient()

    itinerary = context.get("itinerary", [])
    city = context["city"]
    if not itinerary:
        print("  ⏭️  无行程数据，跳过门票查询")
        return context

    # 收集所有景点名称（去重）
    poi_names = []
    seen = set()
    for day in itinerary:
        for poi in day.get("pois", []):
            name = poi["name"]
            if name not in seen:
                seen.add(name)
                poi_names.append({"name": name, "city": city})

    if not poi_names:
        print("  ⏭️  无景点数据，跳过门票查询")
        return context

    from concurrent.futures import ThreadPoolExecutor, as_completed
    ticket_data = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_map = {ex.submit(client.query_poi_ticket, p["name"], p["city"]): p["name"] for p in poi_names}
        for fut in as_completed(fut_map):
            name = fut_map[fut]
            try:
                ticket_data[name] = fut.result()
            except Exception as e:
                ticket_data[name] = {"price_min": None, "price_max": None, "source": "fail"}

    # 第3级降级: Gaode POI 搜索获取门票价格（为 FlyAI 失败的 POI 兜底）
    fail_names = [n for n, td in ticket_data.items() if not td or td.get("source") == "fail"]
    if fail_names and itinerary:
        print(f"  🔄 尝试 Gaode 兜底门票: {len(fail_names)} 个景点")
        # 建立 POI 名称→location 的映射（从 itinerary 取）
        name_to_loc = {}
        for day in itinerary:
            for poi in day.get("pois", []):
                loc = poi.get("location")
                if loc and poi["name"] in fail_names:
                    name_to_loc[poi["name"]] = loc
        for n in fail_names:
            loc = name_to_loc.get(n)
            try:
                pois = amap.place_around(
                    location=loc,
                    radius=500, keywords=n,
                    show_fields="cost",
                    page_size=3,
                ) if loc else []
                if pois:
                    for p in pois:
                        cost_str = p.get("business", {}).get("cost", "") or p.get("cost", "")
                        if cost_str:
                            try:
                                cost_val = float(re.sub(r"[¥￥,，\s]", "", str(cost_str)))
                                if 10 <= cost_val <= 9999:
                                    ticket_data[n] = {"price_min": cost_val, "price_max": cost_val, "source": "gaode"}
                                    print(f"  🎫 {n}: ¥{cost_val:.0f}/人 (Gaode)")
                                    break
                            except ValueError:
                                continue
            except Exception:
                continue
        gaode_ok = sum(1 for td in ticket_data.values() if td and td.get("source") == "gaode")
        if gaode_ok:
            print(f"  ✅ Gaode 门票兜底成功: {gaode_ok}/{len(fail_names)}")

    flyai["tickets"] = ticket_data
    context["flyai_prices"] = flyai

    found = sum(1 for v in ticket_data.values() if v and v.get("source") != "fail")
    for name, td in ticket_data.items():
        if td and td.get("source") != "fail":
            src_tag = {"regex": "📋", "ai_search": "🔍"}.get(td.get("source", ""), "❓")
            print(f"  🎫 {name}: ¥{td['price_min']}~{td['price_max']}/人 {src_tag}")
        else:
            print(f"  ⚪ {name}: 价格未知（按百分比估算）")

    print(f"  ✅ 门票查询完成: {found}/{len(ticket_data)} 个景点有价格")
    return context


# ====================================================================
# Step 8: 攻略报告（Markdown）
# ====================================================================
def step_8_generate_report(context):
    """Markdown报告: 行程安排 + 推荐餐厅 + 必吃推荐 + 规划说明"""
    print(f"\n{'='*50}")
    print(f"Step 8/9: 攻略报告 📝")
    print(f"{'='*50}")
    city = context["city"]
    itinerary = context.get("itinerary", [])
    notes = context.get("research_notes", [])

    start_city = context.get("preferences", {}).get("start_city", "")
    report = f"# {city}旅行攻略\n> {context['timestamp']}\n\n"
    if start_city:
        report += f"> 📍 **出发地**：{start_city}  |  🎯 **目的地**：{city}\n\n"
    if context.get("overall_note"):
        report += f"> 💡 {context['overall_note']}\n\n"
    if notes:
        report += "## 📕 小红书推荐\n" + "".join(f"- **{n.get('title','')}** — {n.get('author','')} (👍{n.get('likes','')})\n" for n in notes[:5]) + "\n"

    if itinerary:
        report += "## 🗺️ 行程安排\n\n"
        for d in itinerary:
            report += f"### Day {d['day']}: {d['label']}\n"
            if d.get("summary"):
                report += f"> {d['summary']}\n\n"
            for i, p in enumerate(d['pois'], 1):
                report += f"{i}. **{p['name']}**"
                if p.get("time_slot"): report += f" — {p['time_slot']}"
                report += "\n"
                if p.get("address"): report += f"   📍 {p['address']}\n"
                parts = []
                if p.get("rating"): parts.append(f"⭐ {p['rating']}")
                if p.get("cost"): parts.append(f"💰 ¥{p['cost']}")
                if parts: report += f"   {' | '.join(parts)}\n"
                if p.get("transit"):
                    tt = p["transit"]
                    if "步行" in tt or "走" in tt: ti = "🚶"
                    elif "地铁" in tt: ti = "🚇"
                    elif "公交" in tt or "巴士" in tt: ti = "🚌"
                    elif "出发" in tt: ti = "🏁"
                    else: ti = "🚗"
                    report += f"   {ti} {tt}\n"
                if p.get("note"): report += f"   💬 {p['note']}\n"
                report += "\n"
            if d.get("foods"):
                report += "**🍽️ 推荐餐厅**\n\n"
                for j, f in enumerate(d['foods'], 1):
                    report += f"{j}. **{f['name']}**"
                    if f.get("time_slot"): report += f" — {f['time_slot']}"
                    report += "\n"
                    parts = []
                    if f.get("cuisine"): parts.append(f"🍳 {f['cuisine']}")
                    if f.get("cost"): parts.append(f"💰 {f['cost']}")
                    if f.get("rating"): parts.append(f"⭐ {f['rating']}")
                    if parts: report += f"   {' | '.join(parts)}\n"
                    if f.get("note"): report += f"   💬 {f['note']}\n"
                    report += "\n"

    if context.get("food_highlights"):
        report += "## 🏆 必吃推荐\n" + "".join(f"- {h}\n" for h in context["food_highlights"]) + "\n"

    report += "---\n*由 Hermes AI 生成*\n"
    safe_city = re.sub(r'[^\w\u4e00-\u9fa5\-\.]', '_', city)
    ts = time.strftime("%Y%m%d_%H%M%S")
    outputs_dir = os.path.join(PROJECT_ROOT, "outputs")
    path = os.path.join(outputs_dir, f"{safe_city}_travel_{ts}.md")
    os.makedirs(outputs_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    context["report_path"] = path
    print(f"  ✅ 报告: {path}")
    return context


# ====================================================================
# Step 8.5: 出行建议与注意事项
# ====================================================================
def step_85_tips(context):
    """基于目的地/季节/偏好/交通，生成出行建议"""
    print(f"\n{'='*50}")
    print(f"Step 8.5/9: 出行建议与注意事项 💡")
    print(f"{'='*50}")
    city = context["city"]
    days = context["days"]
    prefs = context.get("preferences", {})
    transport = prefs.get("transport", "")
    preference = prefs.get("preference", "")
    budget = prefs.get("budget", "")
    start_city = prefs.get("start_city", "")

    try:
        sys.path.insert(0, PROJECT_ROOT)
        from utils.tips import generate_tips
        tips = generate_tips(city, days, transport, preference, budget, start_city)
        context["travel_tips"] = tips
        print(f"  ✅ 通用建议: {len(tips.get('general',[]))}条")
        print(f"  ✅ 偏好建议: {len(tips.get('preference_tips',[]))}条")
        print(f"  ✅ 每日提醒: {len(tips.get('daily_tips',[]))}条")
    except Exception as e:
        print(f"  ⚠️ 出行建议跳过: {e}")

    # 天气信息
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from utils.weather import get_weather_for_dates
        start_date_str = context.get("start_date")
        days = context.get("days", 2)
        wx = get_weather_for_dates(city, start_date_str, days)
        if wx.get("success"):
            context["weather"] = wx
            today_wx = wx.get("today") or (wx["forecast"][0] if wx.get("forecast") else None)
            today_desc = (today_wx.get("weather") or today_wx.get("day_weather")) if today_wx else "未知"
            today_temp = today_wx.get("temp_range") if today_wx else "未知"
            print(f"  🌤️ 天气: {wx['city']} {today_desc} {today_temp}")
        else:
            print(f"  ⚠️ 天气查询: {wx.get('error','')}")
    except Exception as e:
        print(f"  ⚠️ 天气跳过: {e}")

    return context


# ====================================================================
# Step 9: 交付（归档 + 生成图文手册）
# ====================================================================
def step_9_deliver(context):
    """归档 + 生成图文手册（含出行建议）"""
    print(f"\n{'='*50}")
    print(f"Step 9/9: 交付完成 ✅")
    print(f"{'='*50}")

    if BROCHURE_ENABLED and context.get("itinerary"):
        try:
            sys.path.insert(0, BASE)
            from utils.brochure import generate
            city = context["city"]
            itinerary = context["itinerary"]
            highlights = context.get("food_highlights", [])
            prefs = context.get("preferences", {})
            tips = context.get("travel_tips", {})
            wx = context.get("weather", {})
            path = generate(city=city, itinerary=itinerary, food_highlights=highlights,
                          overall_note=context.get("overall_note", ""),
                          transport=prefs.get("transport", ""),
                          accommodation=prefs.get("accommodation", ""),
                          budget=prefs.get("budget", ""),
                          preference=prefs.get("preference", ""),
                          tips=tips, weather=wx,
                          start_city=prefs.get("start_city", ""),
                          people_count=prefs.get("people_count", 2),
                          flyai_prices=context.get("flyai_prices", {}))
            context["brochure_path"] = path
            print(f"  📖 手册: {path}")
        except Exception as e:
            print(f"  ⚠️ 手册生成跳过: {e}")

    print(f"\n  📄 HTML地图: {context.get('html_path','')}")
    print(f"  📄 MD报告:  {context.get('report_path','')}")
    if context.get("brochure_path"):
        print(f"  📖 图文手册: {context['brochure_path']}")
    print(f"  ✨ 多方案辩论: ✅")
    print(f"{'='*50}\n")
    return context


# ====================================================================
# Entry Point (with progress_callback)
# ====================================================================
def run_pipeline(city, days=2, use_research=False, manual_pois=None, prefs=None, progress_callback=None, multi_cities=None):
    global _stop_requested, _step_timings
    _stop_requested = False
    _step_timings = []
    pipeline_t0 = time.time()

    _report = lambda step, msg, pct: progress_callback and progress_callback(step, msg, pct)

    # 注册 Ctrl+C 信号处理器（二次确认），仅主线程可用
    original_handler = None
    if threading.current_thread() is threading.main_thread():
        original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _signal_handler)

    if not prefs:
        prefs = {}

    multi_cities_list = multi_cities or prefs.get("multi_cities", [])

    if multi_cities_list and len(multi_cities_list) > 1:
        try:
            _check_stop("Step 1")
            _report("init", "Step 1/9: 初始化 (多城市模式)", 5)
            with StepTimer("Step 1 初始化"):
                context = step_1_init(city, days, preferences=prefs, manual_pois=manual_pois, multi_cities=multi_cities_list)

            days_per_city = days // len(multi_cities_list)
            rem = days % len(multi_cities_list)

            city_contexts = {}
            combined_itinerary = []
            combined_food_highlights = []
            combined_overall_note = "【多城市串联路线规划】\n"
            
            current_date = context.get("start_date") or datetime.date.today().strftime("%Y-%m-%d")

            for idx, c in enumerate(multi_cities_list):
                c_days = days_per_city + (rem if idx == 0 else 0)
                c_prefs = copy.deepcopy(prefs)
                c_prefs["multi_cities"] = []
                c_prefs["start_date"] = current_date
                
                if idx > 0:
                    c_prefs["start_city"] = ""
                
                print(f"\n🗺️ [多城市模式] 正在为城市 {c} ({idx+1}/{len(multi_cities_list)}) 生成行程，天数: {c_days}天，开始日期: {current_date}")
                
                sub_ctx = run_pipeline(
                    city=c, days=c_days, use_research=use_research,
                    manual_pois=None, prefs=c_prefs,
                    progress_callback=progress_callback, multi_cities=[]
                )
                
                city_contexts[c] = sub_ctx
                
                try:
                    from datetime import datetime, timedelta
                    dt = datetime.strptime(current_date, "%Y-%m-%d")
                    current_date = (dt + timedelta(days=c_days)).strftime("%Y-%m-%d")
                except Exception:
                    pass

            total_days_accumulated = 0
            for idx, c in enumerate(multi_cities_list):
                sub_ctx = city_contexts[c]
                sub_itinerary = sub_ctx.get("itinerary") or []
                c_days = days_per_city + (rem if idx == 0 else 0)
                
                for item in sub_itinerary:
                    new_item = copy.deepcopy(item)
                    old_day = new_item.get("day", 1)
                    new_day = total_days_accumulated + old_day
                    new_item["day"] = new_day
                    
                    if "label" in new_item:
                        label_clean = re.sub(r"^Day \d+:\s*", "", new_item["label"])
                        label_clean = re.sub(r"^Day \d+\s*", "", label_clean)
                        new_item["label"] = f"Day {new_day}: {label_clean}"
                    
                    combined_itinerary.append(new_item)
                
                total_days_accumulated += c_days

                for fh in sub_ctx.get("food_highlights", []):
                    if fh not in combined_food_highlights:
                        combined_food_highlights.append(fh)
                
                if sub_ctx.get("overall_note"):
                    combined_overall_note += f"\n### {c} 规划说明\n{sub_ctx['overall_note']}\n"

            combined_flyai = {"available": False, "tickets": {}}
            for idx, c in enumerate(multi_cities_list):
                sub_flyai = city_contexts[c].get("flyai_prices", {})
                if sub_flyai.get("available"):
                    combined_flyai["available"] = True
                    if "tickets" in sub_flyai:
                        combined_flyai["tickets"].update(sub_flyai["tickets"])
                    if idx == 0:
                        for key in ("flight", "train", "hotel"):
                            if key in sub_flyai:
                                combined_flyai[key] = sub_flyai[key]
                    else:
                        if "hotel" in sub_flyai and sub_flyai["hotel"].get("items"):
                            if "hotel" not in combined_flyai:
                                combined_flyai["hotel"] = {"items": [], "source": "live", "cheapest": None, "count": 0}
                            combined_flyai["hotel"]["items"].extend(sub_flyai["hotel"]["items"])
                            all_hotels = combined_flyai["hotel"]["items"]
                            if all_hotels:
                                combined_flyai["hotel"]["cheapest"] = min(all_hotels, key=lambda x: x["price"])["price"]
                                combined_flyai["hotel"]["count"] = len(all_hotels)
            
            context["flyai_prices"] = combined_flyai
            context["itinerary"] = combined_itinerary
            context["food_highlights"] = combined_food_highlights
            context["overall_note"] = combined_overall_note
            context["city_itineraries"] = {c: city_contexts[c].get("itinerary") for c in multi_cities_list}

            _check_stop("Step 8")
            _report("report", "Step 8/9: 攻略报告 📝", 65)
            enabled_steps = prefs.get("enabled_steps", ["research", "enrich", "distance", "flyai", "tips"])
            if "tips" in enabled_steps:
                with StepTimer("Step 8+8.5 报告+建议"):
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        f8 = ex.submit(step_8_generate_report, copy.deepcopy(context))
                        f85 = ex.submit(step_85_tips, copy.deepcopy(context))
                        ctx8 = f8.result()
                        ctx85 = f85.result()
                    context["report_path"] = ctx8.get("report_path")
                    context["travel_tips"] = ctx85.get("travel_tips", {})
                    context["weather"] = ctx85.get("weather", {})
            else:
                with StepTimer("Step 8 报告"):
                    context = step_8_generate_report(context)
                    context["travel_tips"] = {}
                    context["weather"] = {}

            main_city = multi_cities_list[0]
            sub_cities = multi_cities_list[1:]
            context['city'] = f"{main_city}+{'+'.join(sub_cities)}"

            _check_stop("Step 9")
            _report("deliver", "Step 9/9: 交付完成 ✅", 80)
            with StepTimer("Step 9 图文手册"):
                context = step_9_deliver(context)

        except PipelineStoppedError as e:
            print(f"\n🛑 Pipeline 已停止: {e}")
            print("  已完成的步骤成果已保留。")
        finally:
            if original_handler is not None and threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, original_handler)
            total_elapsed = time.time() - pipeline_t0
            print(f"\n⏱️  Pipeline 总耗时: {total_elapsed:.1f}s")
            _print_timing_summary()

        _report("done", "✅ 全部完成", 100)
        return context

    try:
        start_city = prefs.get("start_city", "")
        if not start_city:
            print("🔍 检测到未指定出发地，正在获取您的实时位置...")
            start_city = amap.get_ip_location()
            if start_city:
                print(f"📍 成功获取您的实时位置为起点: {start_city}")
            else:
                print("⚠️ 实时位置获取失败，默认不设置起点")
                start_city = ""
            prefs["start_city"] = start_city

        enabled_steps = prefs.get("enabled_steps", ["research", "enrich", "distance", "flyai", "tips"])

        _check_stop("Step 1")
        _report("init", "Step 1/9: 初始化", 5)
        with StepTimer("Step 1 初始化"):
            context = step_1_init(city, days, preferences=prefs, manual_pois=manual_pois)

        _check_stop("Step 2")
        _report("research", "Step 2/9: 小红书调研 🔍", 10)
        if "research" in enabled_steps:
            with StepTimer("Step 2 小红书调研"):
                context = step_2_research(context, xhs=xhs, progress_callback=progress_callback)
        else:
            print("⏭️  跳过 Step 2 小红书调研 (用户配置禁用)")
            context["research_notes"] = []
            context["note_contents"] = []
            context["xhs_pois"] = {"sights": [], "foods": []}
            context["xhs_sight_names"] = []
            context["xhs_food_data"] = []

        _check_stop("Step 3")
        _report("geocode", "Step 3/9: POI地理编码 🗺️", 25)
        with StepTimer("Step 3 POI地理编码"):
            context = step_3_geocode(context, manual_pois)

        _check_stop("Step 4")
        _report("enrich", "Step 4/9: POI丰富+美食 🍽️", 35)
        if "enrich" in enabled_steps:
            with StepTimer("Step 4 POI丰富+美食"):
                context = step_4_enrich(context)
        else:
            print("⏭️  跳过 Step 4 POI丰富+美食 (用户配置禁用)")
            enriched = []
            for poi in context["poi_geocoded"]:
                enriched.append({
                    "name": poi["name"],
                    "location": list(poi["location"]),
                    "address": "",
                    "district": "",
                    "nearby_food": []
                })
            context["poi_enriched"] = enriched
            context["food_recommendations"] = []

        _check_stop("Step 5")
        _report("distance", "Step 5/9: 距离矩阵 📏", 45)
        if "distance" in enabled_steps:
            with StepTimer("Step 5 距离矩阵"):
                context = step_5_distance_matrix(context)
        else:
            print("⏭️  跳过 Step 5 距离矩阵 (用户配置禁用)")
            context["distance_matrix"] = {"matrix": [], "labels": []}

        _check_stop("Step 5.5")
        if "flyai" in enabled_steps:
            with StepTimer("Step 5.5 FlyAI实时物价"):
                context = step_55_flyai_pricing(context)
        else:
            context.setdefault("flyai_prices", {"available": False})

        _check_stop("Step 5.6")
        _report("transport_decision", "Step 5.6/9: 交通方式重评估 🚗✈️🚄", 48)
        with StepTimer("Step 5.6 交通决策"):
            context = step_56_transport_decision(context, amap=amap)

        _check_stop("Step 6")
        _report("plan_itinerary", "多方案路线辩论规划 ✨", 50)
        with StepTimer("Step 6 路线辩论规划"):
            context = step_6_plan_itinerary(context, amap=amap, progress_callback=progress_callback)

        _check_stop("Step 7")
        _report("pricing", "Step 7/9: 景点门票查询 🎫", 55)
        with StepTimer("Step 7 门票查询"):
            context = step_7_query_tickets(context)

        _check_stop("Step 8")
        _report("report", "Step 8/9: 攻略报告 📝", 65)
        if "tips" in enabled_steps:
            with StepTimer("Step 8+8.5 报告+建议"):
                with ThreadPoolExecutor(max_workers=2) as ex:
                    f8 = ex.submit(step_8_generate_report, copy.deepcopy(context))
                    f85 = ex.submit(step_85_tips, copy.deepcopy(context))
                    ctx8 = f8.result()
                    ctx85 = f85.result()
                context["report_path"] = ctx8.get("report_path")
                context["travel_tips"] = ctx85.get("travel_tips", {})
                context["weather"] = ctx85.get("weather", {})
        else:
            with StepTimer("Step 8 报告"):
                context = step_8_generate_report(context)
                context["travel_tips"] = {}
                context["weather"] = {}

        _check_stop("Step 9")
        _report("deliver", "Step 9/9: 交付完成 ✅", 80)
        with StepTimer("Step 9 图文手册"):
            context = step_9_deliver(context)

    except PipelineStoppedError as e:
        print(f"\n🛑 Pipeline 已停止: {e}")
        print("  已完成的步骤成果已保留。")
    finally:
        if original_handler is not None and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, original_handler)
        total_elapsed = time.time() - pipeline_t0
        print(f"\n⏱️  Pipeline 总耗时: {total_elapsed:.1f}s")
        _print_timing_summary()

    _report("done", "✅ 全部完成", 100)
    return context


# ====================================================================
# Goal Parser: 自然语言 → 结构化参数
# ====================================================================
def _parse_budget(budget_str, days=2, people_count=2):
    """解析预算字符串，返回(每人每天预算, 总预算)"""
    if not budget_str:
        return (None, None)
    nums = re.findall(r'\d+', budget_str.replace(',', ''))
    if not nums:
        return (None, None)
    budget_vals = [int(n) for n in nums if int(n) >= 100]
    if not budget_vals:
        return (None, None)
    total = max(budget_vals)

    is_daily = any(x in budget_str for x in ['天', '日', 'daily', '每天', '每日'])
    is_per_person = any(x in budget_str for x in ['人均', '每人', '每人每天', '人均每天', '单人', '/人'])

    specified_people = people_count
    match_people = re.search(r'(\d+|两|三|四|五|六)人', budget_str)
    if match_people:
        p_word = match_people.group(1)
        if p_word == '两':
            specified_people = 2
        elif p_word == '三':
            specified_people = 3
        elif p_word == '四':
            specified_people = 4
        elif p_word.isdigit():
            specified_people = int(p_word)

    if is_daily:
        if is_per_person:
            daily_per_person = total
        else:
            daily_per_person = total // max(specified_people, 1)
    else:
        if is_per_person:
            daily_per_person = total // max(days, 1)
        else:
            daily_per_person = total // (max(specified_people, 1) * max(days, 1))

    total_trip_budget = daily_per_person * max(days, 1) * people_count
    return (max(daily_per_person, 1), total_trip_budget)


def _parse_goal(goal_text):
    """用LLM将自然语言目标解析为结构化参数，自动补全缺省信息"""
    from utils.tips import _season
    season_name, season_desc = _season()
    prompt = f"""你是一个旅行规划助手。将用户的自然语言需求解析为结构化JSON。
自动补全所有缺失信息，做出合理默认选择。

【用户需求】
{goal_text}

【解析规则】
- city: 提取城市名。如果只给了省份，选该省最热门旅游城市。如果给了模糊描述(如"南方""看海")，推荐合适城市。
- multi_cities: 【重要】如果 days >= 5 或目的地是省份/区域名（如"浙江""云南""四川"），输出多城市列表，按地理位置顺路排列，每个城市停留 1-3 天。如果 days < 5 且目的地是具体城市，输出空数组 []。
- start_city: 提取出发城市/起点城市。如果用户没有规定出发地点或未提及，输出空字符串 ""。
- days: 提取天数。如果给了"周末"→2，如果给了模糊时间→推荐天数，默认2。
- start_date: 出行日期(格式: YYYY-MM-DD)。如果用户提到了具体日期(如'7/5-7/6'或'7月5日')，请结合当前日期所在的年份(当前为2026年)解析出开始日期(例如'2026-07-05')。如果未提供，默认写今天({time.strftime("%Y-%m-%d")})。
- pois: 提取或推荐该城市最值得去的景点/地标(3-8个)，只要景点名不要餐厅。如果用户没指定，根据目的地自动推荐。
- transport: 提取交通方式("自驾"/"高铁"/"飞机")。如果没给,<200km默认自驾,200-800km高铁,>800km飞机。
- budget: 预算描述。如果用户没给，默认"两人共3000/天（含住宿/交通/饮食/门票）"
- preference: 偏好描述(如"亲子","情侣","美食","休闲"),空字符串表示无特殊偏好。
- accommodation: 住宿区域或酒店名，根据行程路线推荐顺路区域，少绕路。如果没给，根据行程路线推荐合适区域.
- people_count: 提取出行人数。例如"我们四个人" -> 4，"三口之家" -> 3。如果未明示，默认输出 2。

【当前季节】{season_name}（{season_desc}），推荐相应季节的景点与活动。

输出纯JSON，严格按以下格式，不要多余文字：
{{"city":"城市名","multi_cities":["城市1","城市2"],"start_city":"出发城市","days":2,"start_date":"YYYY-MM-DD","pois":["景点1","景点2"],"transport":"方式","budget":"描述","preference":"描述","accommodation":"描述","people_count":2}}"""

    try:
        from utils.llm import call_deepseek
        result = call_deepseek("你是一个旅行规划助手。返回纯JSON。", prompt, temperature=0.3, max_tokens=2000)
        if isinstance(result, dict):
            city = result.get("city", "上海")
            start_city = result.get("start_city", "")
            days = int(result.get("days", 2))
            pois = result.get("pois", [])
            transport = result.get("transport", "")
            budget = result.get("budget", "")
            preference = result.get("preference", "")
            accommodation = result.get("accommodation", "")
            start_date = result.get("start_date", "")
            people_count = int(result.get("people_count", 2))
            multi_cities = result.get("multi_cities", [])
            print(f"\n🎯 目标解析结果:")
            print(f"   出发城市: {start_city or '未指定(将通过IP定位)'}")
            print(f"   目的地: {city}")
            if multi_cities:
                print(f"   多城市: {' → '.join(multi_cities)}")
            print(f"   出行日期: {start_date}")
            print(f"   天数: {days}")
            print(f"   人数: {people_count} 人")
            print(f"   交通: {transport or '未指定'}")
            print(f"   预算: {budget or '不限'}")
            print(f"   偏好: {preference or '无'}")
            print(f"   住宿: {accommodation}" if accommodation else "   住宿: 未指定")
            print(f"   POI: {', '.join(pois[:8])}")
            print(f"   多城市: {' → '.join(multi_cities)}" if multi_cities else "")
            return city, days, pois, {
                "transport": transport,
                "budget": budget,
                "preference": preference,
                "accommodation": accommodation,
                "start_date": start_date,
                "start_city": start_city,
                "people_count": people_count,
                "multi_cities": multi_cities,
                "_budget_parsed": _parse_budget(budget, days, people_count),
            }
    except Exception as e:
        print(f"  ⚠️ 目标解析失败: {e}，使用默认参数")
    return "上海", 2, [], {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="旅游攻略生成 Pipeline")
    parser.add_argument("--city", default="", help="目的地城市")
    parser.add_argument("--days", type=int, default=0, help="行程天数")
    parser.add_argument("--research", action="store_true", help="开启小红书调研")
    parser.add_argument("--pois", default="", help="手动POI,逗号分隔")
    parser.add_argument("--goal", default="", help="自然语言目标描述(如'浙江周末自驾')")
    parser.add_argument("--start-city", default="", help="出发城市")
    args = parser.parse_args()

    if args.goal:
        city, days, pois, prefs = _parse_goal(args.goal)
        if args.city: city = args.city
        if args.days: days = args.days
        if args.pois: pois = [p.strip() for p in args.pois.split(",") if p.strip()]
        if args.start_city: prefs["start_city"] = args.start_city
        print(f"\n{'='*50}")
        print(f"🎯 目标: {args.goal}")
        print(f"{'='*50}")
        run_pipeline(city, days, args.research, pois, prefs)
    else:
        city = args.city or "上海"
        days = args.days or 2
        pois = [p.strip() for p in args.pois.split(",") if p.strip()] if args.pois else None
        prefs = {"start_city": args.start_city} if args.start_city else None
        run_pipeline(city, days, args.research, pois, prefs)
