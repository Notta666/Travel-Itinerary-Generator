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
from utils.tips import _season

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
def step_1_init(city, days=2, preferences=None, manual_pois=None):
    """读取城市、天数、手动POI、偏好"""
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
                          people_count=prefs.get("people_count", 2))
            context["brochure_path"] = path
            print(f"  📖 手册: {path}")
        except Exception as e:
            print(f"  ⚠️ 手册生成跳过: {e}")

    print(f"\n  📄 HTML地图: {context.get('html_path','')}")
    print(f"  📄 MD报告:  {context.get('report_path','')}")
    if context.get("brochure_path"):
        print(f"  📖 图文手册: {context['brochure_path']}")
    print(f"  🐂🐻 对抗辩论: ✅")
    print(f"{'='*50}\n")
    return context


# ====================================================================
# Entry Point (with progress_callback)
# ====================================================================
def run_pipeline(city, days=2, use_research=False, manual_pois=None, prefs=None, progress_callback=None):
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

        enabled_steps = prefs.get("enabled_steps", ["research", "enrich", "distance", "tips"])

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

        _check_stop("Step 6")
        _report("plan_itinerary", "Step 6/9: 对抗辩论路线规划 🐂🐻", 50)
        with StepTimer("Step 6 对抗辩论规划"):
            context = step_6_plan_itinerary(context, amap=amap, progress_callback=progress_callback)

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
    season_name, season_desc = _season()
    prompt = f"""你是一个旅行规划助手。将用户的自然语言需求解析为结构化JSON。
自动补全所有缺失信息，做出合理默认选择。

【用户需求】
{goal_text}

【解析规则】
- city: 提取城市名。如果只给了省份，选该省最热门旅游城市。如果给了模糊描述(如"南方""看海")，推荐合适城市。
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
{{"city":"城市名","start_city":"出发城市","days":2,"start_date":"YYYY-MM-DD","pois":["景点1","景点2"],"transport":"方式","budget":"描述","preference":"描述","accommodation":"描述","people_count":2}}"""

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
            print(f"\n🎯 目标解析结果:")
            print(f"   出发城市: {start_city or '未指定(将通过IP定位)'}")
            print(f"   目的地: {city}")
            print(f"   出行日期: {start_date}")
            print(f"   天数: {days}")
            print(f"   人数: {people_count} 人")
            print(f"   交通: {transport or '未指定'}")
            print(f"   预算: {budget or '不限'}")
            print(f"   偏好: {preference or '无'}")
            print(f"   住宿: {accommodation}" if accommodation else "   住宿: 未指定")
            print(f"   POI: {', '.join(pois[:8])}")
            return city, days, pois, {
                "transport": transport,
                "budget": budget,
                "preference": preference,
                "accommodation": accommodation,
                "start_date": start_date,
                "start_city": start_city,
                "people_count": people_count,
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
