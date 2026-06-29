"""
Travel-Itinerary-Generator · Pipeline 固定流程
================================================
Usage:
    python pipeline/run_pipeline.py --city 上海 --days 2
    python pipeline/run_pipeline.py --city 上海 --days 2 --pois "外滩,豫园"
    python pipeline/run_pipeline.py --city 上海 --days 2 --research

步骤列表（9步工序链）:
"""

import sys, os, json, argparse, time, copy, threading, signal
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient, poi_type_name
from utils.research import XiaoHongShu
from utils.llm import call_deepseek

BASE = PROJECT_ROOT
OUTPUTS_DIR = os.path.join(BASE, "outputs")
DATA_DIR = os.path.join(BASE, "data")
TEMPLATE_PATH = os.path.join(BASE, "web", "template.html")
BROCHURE_ENABLED = True  # 生成图文手册

amap = AMapClient()
xhs = XiaoHongShu()


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
        # 连续两次 Ctrl+C 直接停止
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
        import datetime
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
    return context


# ====================================================================
# Step 2: 小红书调研 + 笔记精读 + LLM提取景点+美食
# ====================================================================
def step_2_research(context):
    """Agent-Reach 小红书搜索 → 精读笔记 → LLM提取景点+美食"""
    print(f"\n{'='*50}")
    print(f"Step 2/9: 小红书调研 🔍（景点+美食双通道）")
    print(f"{'='*50}")
    city = context["city"]
    all_notes = []
    note_contents = []

    # 双通道搜索
    queries = [
        (f"{city}美食推荐 必吃", "美食"),
        (f"{city}旅游攻略 景点", "景点"),
    ]
    for query, label in queries:
        print(f"  📕 搜索{label}: {query}")
        try:
            notes = xhs.search(query, limit=5)
            all_notes.extend(notes)
            print(f"     → {len(notes)} 篇")
        except Exception as e:
            print(f"     ⚠️ {e}")
        time.sleep(0.5)

    # 去重
    seen = set()
    unique_notes = []
    for n in all_notes:
        t = n.get("title", "")
        if t and t not in seen:
            seen.add(t)
            unique_notes.append(n)
    all_notes = unique_notes[:10]

    # 并行精读前 5 篇笔记并抓取其评论
    if all_notes:
        print(f"  📖 并行精读 {min(5, len(all_notes))} 篇笔记与精彩评论...")
        active_notes = all_notes[:5]
        
        def _fetch_note_and_comments(note):
            url = note.get("url", "")
            if not url:
                return None
            content = xhs.read_note_content(url)
            if not content:
                return None
            # 并行抓取评论
            comments = xhs.get_comments(url, limit=5)
            if comments:
                c_lines = []
                for c in comments:
                    txt = c.get("text", "").strip()
                    if txt:
                        c_lines.append(f"    - {c.get('author','匿名')}: {txt} (👍{c.get('likes',0)})")
                if c_lines:
                    content["content"] += "\n【精彩评论与用户避雷反馈】:\n" + "\n".join(c_lines)
            return content

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(_fetch_note_and_comments, note) for note in active_notes]
            for f in futures:
                try:
                    res = f.result()
                    if res:
                        note_contents.append(res)
                        title = next((an.get("title", "") for an in active_notes if an.get("url") == res.get("url")), "")
                        print(f"     ✅ {title[:30]}")
                except Exception as e:
                    pass

    # LLM提取结构化景点+美食（含避雷/赞点）
    xhs_pois = {"sights": [], "foods": []}
    if note_contents:
        notes_text = "\n\n".join(
            f"【笔记{i+1}】\n{n.get('content','')[:2500]}"
            for i, n in enumerate(note_contents)
        )
        extract_prompt = f"""你是一名旅行信息整理专家。从以下{city}的小红书笔记及用户真实评论中，提取所有提到的【景点】和【餐厅/美食】。
特别注意：评论中往往包含真实的排队时长、避雷吐槽或极力推荐，请务必从正文 and 评论中提炼每个景点的“真实避雷点”与“赞点”。

要求：
1. 景点包括：自然风光、地标建筑、公园、博物馆、古镇等
2. 餐厅包括：餐馆、小吃店、咖啡馆、茶室等
3. 每个条目给出名称和简短描述（为什么值得去）
4. 从评论和正文中搜集关于该景点的避雷吐槽（排队久、门票贵、虚假宣传等）和强烈推荐点，整理填入 complaints 和 highlights 中。如果没有则写“无”
5. 按推荐热度排序，最多各取10个
6. 【关键】请根据笔记内容或常识，判断该景点/餐厅【所属的具体城市名】（例如“广州”、“顺德”、“珠海”、“澳门”等），并在 JSON 中填入 "city" 字段。

笔记与评论内容：
{notes_text}

输出格式（纯JSON，不要额外文字）：
{{"sights": [{{"name":"名称","city":"该景点所在的具体城市(如 广州/顺德/珠海/澳门等)","reason":"推荐理由","complaints":"避雷点/真实排队或踩雷吐槽","highlights":"绝美机位/赞点"}}], 
 "foods": [{{"name":"名称","city":"该餐厅所在的具体城市(如 广州/顺德/珠海/澳门等)","reason":"推荐理由","cuisine":"菜系类型","complaints":"避雷点/口味吐槽","highlights":"必点菜/赞点"}}]}}"""

        try:
            result = call_deepseek("提取POI。返回纯JSON。", extract_prompt, temperature=0.1, max_tokens=3000)
            if isinstance(result, dict):
                xhs_pois["sights"] = result.get("sights", [])
                xhs_pois["foods"] = result.get("foods", [])
                
                # 保存景点与美食对应的具体城市映射
                sight_city_map = {}
                for s in xhs_pois["sights"]:
                    if "name" in s and "city" in s:
                        sight_city_map[s["name"]] = s["city"]
                context["sight_city_map"] = sight_city_map

                food_city_map = {}
                for f in xhs_pois["foods"]:
                    if "name" in f and "city" in f:
                        food_city_map[f["name"]] = f["city"]
                context["food_city_map"] = food_city_map

                print(f"  🤖 LLM提取: {len(xhs_pois['sights'])}个景点 + {len(xhs_pois['foods'])}家餐厅")
                for s in xhs_pois["sights"][:3]:
                    print(f"     🏛️ {s['name']} [{s.get('city','')}] (避雷: {s.get('complaints','无')})")
                for f in xhs_pois["foods"][:3]:
                    print(f"     🍴 {f['name']} [{f.get('city','')}] (避雷: {f.get('complaints','无')})")
        except Exception as e:
            print(f"  ⚠️ LLM提取失败: {e}")
    else:
        print("  ⚠️ 未获取到小红书笔记内容")

    # 默认值兜底
    context.setdefault("sight_city_map", {})
    context.setdefault("food_city_map", {})

    context["research_notes"] = all_notes
    context["note_contents"] = note_contents
    context["xhs_pois"] = xhs_pois
    # 从xhs提取的景点名列表（供step3地理编码用）
    context["xhs_sight_names"] = [s["name"] for s in xhs_pois["sights"]]
    context["xhs_food_data"] = xhs_pois["foods"]
    print(f"  完成: {len(all_notes)}篇笔记 → {len(xhs_pois['sights'])}个景点 + {len(xhs_pois['foods'])}家餐厅")
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

    # POI来源优先级：手动指定 > 小红书提取 > 默认
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

    # 预先获取所有目的城市的中心点，用于漂移审计和智能匹配
    cities_list = [c.strip() for c in city.replace("，", ",").split(",") if c.strip()]

    # 针对缺失城市归属信息的 POI 启动 LLM 快速识别
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
    sight_city_map = context.get("sight_city_map", {})
    def _smart_geocode(name):
        spec_city = sight_city_map.get(name, "").strip()
        if spec_city:
            for suffix in ["市", "区", "县"]:
                if spec_city.endswith(suffix) and len(spec_city) > 2:
                    spec_city = spec_city[:-1]

        # 整理候选城市列表：优先使用 Step 2 提取的特定城市
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

        # 1. 如果名字里已经有城市名，直接用
        for c in candidate_cities:
            if c in name:
                coord = amap.geocode(name, c)
                if coord:
                    return name, coord
                    
        # 2. 如果名字里没有城市名，依次拼装城市名前缀尝试地理编码
        for c in candidate_cities:
            lookup_cities = [c]
            if c == "顺德":
                lookup_cities = ["顺德", "佛山"]
                
            for lc in lookup_cities:
                q_name = f"{lc}{name}"
                coord = amap.geocode(q_name, lc)
                if coord:
                    # 必须在这个城市中心 50km 范围内才算匹配成功
                    c_coord = amap.geocode(lc)
                    if c_coord:
                        dist = abs(coord[0] - c_coord[0]) * 111 + abs(coord[1] - c_coord[1]) * 111
                        if dist <= 50:
                            return name, coord
                            
        # 3. 实在找不到，再全局地码
        return name, amap.geocode(name)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_smart_geocode, n): n for n in pois_to_code}
        for f in as_completed(futures):
            try:
                name, coord = f.result()
                if coord:
                    results[name] = coord
            except:
                pass

    geocoded = []
    for name in pois_to_code:
        coord = results.get(name)
        
        # 审计校验：检查坐标是否偏离所有目的城市超过 100km
        is_drift = True
        if coord:
            for cx, cy in city_centers:
                dist = abs(coord[0] - cx) * 111 + abs(coord[1] - cy) * 111
                if dist <= 100:  # 只要距离任意一个目的城市在 100km 内，即为合规
                    is_drift = False
                    break
        
        # 如果判定为偏离或失败，尝试用目的地城市群中的前缀重新地理编码纠偏
        if (is_drift or not coord) and cities_list:
            for c_prefix in cities_list[:3]:  # 最多试前三个城市
                fallback_name = f"{c_prefix}{name}"
                print(f"  ⚠️ 发现定位漂移或失败: '{name}'。尝试使用前缀 '{fallback_name}' 重新编码...")
                fallback_coord = amap.geocode(fallback_name)
                if fallback_coord:
                    # 重新检验新坐标是否满足 100km 距离限制
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
            # 降级 Mock 坐标方案
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

    # 1. 批量并行丰富景点POI信息（直接根据纠偏后的坐标做逆地理编码，防止重名导致拉取异地详情）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    enrich_results = {}
    
    def _enrich_by_loc(poi):
        name = poi["name"]
        loc = poi["location"]
        regeo = amap.reverse_geocode(loc, radius=500, extensions="base")
        result = {
            "name": name,
            "location": loc,
        }
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

    # 建立景点 complaints/highlights 映射
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

    # 2. 过滤并批量并行验证美食坐标
    xhs_foods = context.get("xhs_food_data", [])
    prefs = context.get("preferences", {})
    
    foods_to_geocode = []
    for f in xhs_foods:
        name = f.get("name", "")
        if name and name not in foods_to_geocode:
            # 预算过滤
            budget_per = prefs.get("_budget_parsed", (None, None))
            daily_budget = budget_per[0]
            cuisines_price = {"小吃": 20, "面": 25, "咖啡": 30, "快餐": 35,
                           "川菜": 60, "湘菜": 55, "粤菜": 80, "杭帮": 70, "本帮": 65,
                           "日料": 120, "西餐": 150, "火锅": 100, "烧烤": 80}
            est_cost = cuisines_price.get(f.get("cuisine", "")[:2], 50)
            if daily_budget and est_cost > daily_budget * 1.5:
                continue  # 超出预算，跳过
            foods_to_geocode.append(name)
            
    # 批量编码美食，结合特定所属城市进行精准检索与校准
    food_coords = {}
    if foods_to_geocode:
        food_city_map = context.setdefault("food_city_map", {})
        cities_list = [c.strip() for c in city.replace("，", ",").split(",") if c.strip()]

        # 针对缺失城市归属信息的美食启动 LLM 快速识别
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

            # 整理候选城市列表：优先使用 Step 2 提取的美食特定城市
            candidate_cities = []
            if f_city:
                candidate_cities.append(f_city)
            for c in cities_list:
                if c not in candidate_cities:
                    candidate_cities.append(c)
                    if c == "顺德" and "佛山" not in candidate_cities:
                        candidate_cities.append("佛山")

            # 1. 尝试直接以候选城市的前缀拼装进行地理编码
            for c in candidate_cities:
                q_name = f"{c}{name}" if c not in name else name
                coord = amap.geocode(q_name, c)
                if coord:
                    # 必须在这个城市中心 50km 范围内才算匹配成功
                    c_coord = amap.geocode(c)
                    if c_coord:
                        dist = abs(coord[0] - c_coord[0]) * 111 + abs(coord[1] - c_coord[1]) * 111
                        if dist <= 50:
                            return name, coord

            # 2. 如果失败，使用 keywords 搜索 place_text 兜底限制在城市内
            for c in candidate_cities:
                try:
                    pois = amap.place_text(keywords=name, region=c, city_limit=True, page_size=1)
                    if pois:
                        loc = pois[0]["location"]
                        lng, lat = loc.split(",")
                        return name, (float(lng), float(lat))
                except:
                    pass

            # 3. 实在找不到，全局地码
            return name, amap.geocode(name)

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(_smart_geocode_food, n): n for n in foods_to_geocode}
            for f in as_completed(futures):
                try:
                    name, coord = f.result()
                    if coord:
                        food_coords[name] = coord
                except:
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
    # 使用并行版本（如果可用），否则降级到串行
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
# Step 6: 对抗性辩论路线规划 (Bull / Bear / Fusion)
# ====================================================================
def step_6_plan_itinerary(context):
    """三段式DeepSeek API:
       Bull(高效派) → 密集景点+就近配餐厅
       Bear(悠闲派) → 品质体验+用餐推荐
       Fusion(综合) → 最终行程(景点+餐厅交替)
    """
    print(f"\n{'='*50}")
    print(f"Step 6/9: 对抗性辩论路线规划 🐂🐻⚖️")
    print(f"{'='*50}")
    city = context["city"]
    days = context["days"]
    pois = context["poi_enriched"]
    dist_matrix = context.get("distance_matrix", {})
    food_list = context.get("food_recommendations", [])

    if not pois:
        print("  ⚠️ 无POI, 跳过")
        return context

    # --- 构建输入数据 ---
    pois_data = []
    for p in pois:
        loc = p["location"]
        pois_data.append({
            "name": p["name"],
            "lng": loc[0], "lat": loc[1],
            "address": p.get("address", ""),
            "district": p.get("district", ""),
            "complaints": p.get("complaints", "无"),
            "highlights": p.get("highlights", "无")
        })

    food_json = json.dumps([{"name": f["name"], "rating": f.get("rating",""), "cost": f.get("cost",""),
                             "tag": f.get("tag",""), "address": f.get("address",""),
                             "complaints": f.get("complaints", "无"),
                             "highlights": f.get("highlights", "无")} for f in food_list],
                           ensure_ascii=False, indent=2)
    input_json = json.dumps({"city": city, "days": days, "pois": pois_data,
                             "distance_matrix_km": dist_matrix.get("matrix", []),
                             "labels": dist_matrix.get("labels", [])}, ensure_ascii=False, indent=2)

    lodging_instruction = """
【特别住宿与时间限制规则（必须严格遵守）】:
1. 这是一次 5天4晚 的春节旅程（2026年2月18日~22日）。
2. 第一天（2月18日）晚上机场落地广州后必须安排广州住宿（住广州第1晚）。
3. 第二天（2月19日）游玩广州，晚上安排广州住宿（住广州第2晚，即广州共2晚，广州不安排其他过夜）。
4. 第三天（2月20日）上午/下午游玩顺德，傍晚必须出发前往珠海，晚上落地珠海安顿并吃宵夜，安排珠海住宿（住珠海第1晚）。
5. 第四天（2月21日）过关前往澳门游玩，当天晚上必须返回珠海入住（住珠海第2晚，即珠海共2晚，珠海不安排其他过夜）。
6. 第五天（2月22日）游玩珠海，并在傍晚/晚上从珠海站搭乘动卧返回上海（即第五天所有活动、景点和返回交通的所在城市city必须为珠海，绝不能标注为广州）。第五天晚上绝不能安排任何在广州、珠海或澳门的住宿，晚上全部在动卧火车上度过。
"""

    format_instruction = '输出JSON: {"days":[{"day":1,"label":"区域","summary":"","accommodation_city":"该天晚上入住城市(如广州/珠海，不留宿为空)","slots":[{"type":"sight/food","name":"名称","city":"该景点或餐厅所在的具体城市(如广州/佛山/珠海/澳门)","time":"时段","transit":"","note":"","cuisine":"","cost":"","rating":""}]}]}'

    # ---- Bull Prompt ----
    bull_prompt = f"""你是一名高效派旅行规划师（Bull）。根据用户要求的每日安排和交通动线，规划【景点+美食】一体的高效行程。
【用户特别行程与动线要求】
{context.get("goal", "无")}
{lodging_instruction}

【景点数据（含真实用户避雷/赞点）】{input_json}
【城市推荐餐厅（含避雷/赞点）】{food_json}

要求：
1. 严格遵守【用户特别行程与动线要求】与【特别住宿与时间限制规则】（例如第几天在哪个城市、在哪里住宿、怎么往返等）。
2. 每个景点配附近餐厅，时间合理。
3. 结合赞点（highlights）和避雷吐槽（complaints），合理编排路线。
4. 【餐饮推荐规则】：每天原则上必须推荐早、中、晚三顿正餐（早餐、午餐、晚餐，类型均为food，并在 time_slot 或 note 中标明），在正餐之间的空闲时段，可以穿插推荐当地特色小吃或甜点（如双皮奶、蛋挞、双皮奶等），并明确标注为小吃或甜点。
{format_instruction}"""

    # ---- Bear Prompt ----
    bear_prompt = f"""你是一名品质悠闲派旅行规划师（Bear）。针对所有推荐的景点与美食，你需要根据用户评论中的避雷/吐槽进行品质把关。
【用户特别行程与动线要求】
{context.get("goal", "无")}
{lodging_instruction}

【景点数据（含真实用户避雷/赞点）】{input_json}
【城市推荐餐厅（含避雷/赞点）】{food_json}

辩论与筛选要求：
1. 严格遵守【用户特别行程与动线要求】与【特别住宿与时间限制规则】中的跨城交通、天数和住宿点分配。
2. **【景点与美食辩论】**：针对每一个包含避雷/吐槽（complaints）的景点或餐厅进行评估。如果避雷点严重（例如：排队超过2小时、虚假宣传、口味难吃/宰客等），你必须在规划时**果断舍弃/替换**该地。
3. 【餐饮推荐规则】：每天原则上必须包含早、中、晚三顿正餐（早餐、午餐、晚餐，类型为food），每餐安排充足时间，重点推荐赞点（highlights）口碑佳的地点。在正餐之间的空余时段，可以合理安排推荐特色小吃或甜品（如双皮奶、蛋挞等），但必须标明为小吃/甜点，不要与正餐时间冲突。
{format_instruction}"""

    try:
        # Bull + Bear 并行调用
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_bull = ex.submit(call_deepseek, "返回纯JSON。", bull_prompt, 0.3, 3000)
            f_bear = ex.submit(call_deepseek, "返回纯JSON。", bear_prompt, 0.3, 3000)
            bull_raw = f_bull.result()
            bear_raw = f_bear.result()
        bull_result = bull_raw if isinstance(bull_raw, dict) else {}
        bear_result = bear_raw if isinstance(bear_raw, dict) else {}
        # Bear返回0天时重试一次
        if isinstance(bear_result, dict) and len(bear_result.get('days',[]) or []) == 0:
            print("  ⚠️ Bear返回0天，重试一次...")
            bear_retry = call_deepseek("返回纯JSON。", bear_prompt, temperature=0.4, max_tokens=3000)
            bear_result = bear_retry if isinstance(bear_retry, dict) else bear_result
        print(f"  🐂 Bull → {len(bull_result.get('days',[]) or [])} 天 | 🐻 Bear → {len(bear_result.get('days',[]) or [])} 天")

        # ---- Fusion Prompt ----
        fusion_prompt = f"""首席旅行规划官。综合两位分析师（高效派 Bull 与 悠闲避雷派 Bear）的辩论方案做出最终融合。

【用户特别行程与动线要求】
{context.get("goal", "无")}

Bull高效方案: {json.dumps(bull_result, ensure_ascii=False)}
Bear悠闲避雷方案: {json.dumps(bear_result, ensure_ascii=False)}

【原始景点与避雷/赞点数据】{input_json}
【原始餐厅与避雷/赞点数据】{food_json}

裁决辩论原则：
1. 必须完全符合【用户特别行程与动线要求】（例如：各天所在的城市定位、第几天吃夜宵、住宿地点、飞机出发与动卧返回等）。
2. 评估 Bull 方案的路线效率和 Bear 方案针对避雷点的剔除理由。
3. 如果某个景点或餐厅在小红书评论中吐槽严重（如虚假宣传、性价比极低），采纳 Bear 的建议，予以替换或在 note 中加入特别警示。
4. 在最终输出的 `overall_note` 中，必须包含一段 **【景点与美食辩论纪要】**：列出对于争议景点分析师们的不同看法以及你的最终裁决理由。
5. 必须严格落实【一日三餐+小吃甜点】规则：最终方案里，每一天原则上都要推荐早餐、午餐、晚餐三顿正餐（标注在时段或note中），其它闲暇时段（下午或夜间）可穿插推荐特色小吃/甜品/夜宵，不能遗漏正餐。

输出JSON:
{{"days":[{{"day":1,"label":"主题","summary":"概要","accommodation_city":"该天晚上入住城市(如广州/珠海，不留宿为空)",
    "slots":[{{"type":"sight","name":"","city":"该景点所在的具体城市(如广州/佛山/珠海/澳门)","time_slot":"","transit":"","note":"游览贴士/避雷提醒"}},
             {{"type":"food","name":"","city":"该餐厅所在的具体城市(如广州/佛山/珠海/澳门)","time_slot":"","cuisine":"","cost":"","rating":"","note":"推荐菜/避雷吐槽"}}]}}],
  "overall_note":"【景点与美食辩论纪要】... \\n【总体行程说明】...",
  "food_highlights":["必吃1","必吃2"]}}"""

        print("  ⚖️ Fusion 综合裁决中...")
        fusion_result = call_deepseek("首席规划官。返回纯JSON。", fusion_prompt, temperature=0.3, max_tokens=4000)
        days_out = fusion_result.get("days", [])
    except Exception as e:
        print(f"  ⚠️ LLM 路线规划规划失败: {e}，将启动规则引擎降级规划方案。")
        # 降级方案：按天平均分配 POI，并关联最近的美食
        days_out = []
        overall_note = "本地降级规则引擎生成的行程规划，暂未经过 LLM 优化。"
        food_highlights = [f["name"] for f in food_list[:3]] if food_list else []
        
        # 简单均分景点到每一天
        pois_per_day = max(1, len(pois) // days)
        for d in range(1, days + 1):
            day_slots = []
            start_idx = (d - 1) * pois_per_day
            end_idx = start_idx + pois_per_day if d < days else len(pois)
            day_pois = pois[start_idx:end_idx]
            
            for idx, p in enumerate(day_pois):
                # 添加景点
                day_slots.append({
                    "type": "sight",
                    "name": p["name"],
                    "time_slot": f"{9 + idx * 3:02d}:00-{11 + idx * 3:02d}:00",
                    "transit": "步行或打车" if idx > 0 else "出发",
                    "note": "经典游览地标"
                })
                # 添加就近餐厅（如果有的话）
                if p.get("nearby_food"):
                    f = p["nearby_food"][0]
                    day_slots.append({
                        "type": "food",
                        "name": f["name"],
                        "time_slot": f"{12 + idx * 5:02d}:00-{13 + idx * 5:02d}:00",
                        "cuisine": f.get("tag", "特色美食"),
                        "cost": f.get("cost", "不限"),
                        "rating": f.get("rating", "4.0"),
                        "note": "景点附近高口碑餐厅"
                    })
            days_out.append({
                "day": d,
                "label": f"Day {d} 经典地标打卡",
                "summary": f"本日游览 {len(day_pois)} 个主要景点",
                "slots": day_slots
            })
        fusion_result = {
            "days": days_out,
            "overall_note": overall_note,
            "food_highlights": food_highlights
        }

    # --- 坐标匹配（防大西洋Bug）---
    food_coord_map = {}
    for fr in food_list:
        loc = fr.get("location", "")
        if isinstance(loc, (list, tuple)) and len(loc) >= 2:
            food_coord_map[fr["name"]] = [float(loc[0]), float(loc[1])]
        elif isinstance(loc, str) and "," in loc:
            lng, lat = loc.split(",")
            food_coord_map[fr["name"]] = [float(lng), float(lat)]
    for ep in pois:
        for nf in ep.get("nearby_food", []):
            nf_loc = nf.get("location", "")
            if isinstance(nf_loc, (list, tuple)) and len(nf_loc) >= 2:
                food_coord_map[nf["name"]] = [float(nf_loc[0]), float(nf_loc[1])]
            elif isinstance(nf_loc, str) and "," in nf_loc:
                lng, lat = nf_loc.split(",")
                food_coord_map[nf["name"]] = [float(lng), float(lat)]

    # 城市中心坐标（用于验证合理性，支持多城）
    cities_list = [c.strip() for c in city.replace("，", ",").split(",") if c.strip()]
    city_centers = []
    for c in cities_list:
        c_coord = amap.geocode(c)
        if c_coord:
            city_centers.append(list(c_coord))
    if not city_centers:
        city_centers = [[121.47, 31.23]]

    itinerary = []
    for d in days_out:
        day_pois, day_foods = [], []
        
        # 先收集当天所有景点的坐标，用于餐厅坐标失败或偏离时的就近 fallback
        day_sight_coords = []
        for s in d.get("slots", []):
            if s.get("type", "sight") != "food":
                for ep in pois:
                    if ep["name"] == s["name"]:
                        day_sight_coords.append(ep["location"])
                        break
        fallback_coord = day_sight_coords[0] if day_sight_coords else city_centers[0]

        for s in d.get("slots", []):
            s_type = s.get("type", "sight")
            name = s["name"]
            slot_city = s.get("city", "").strip()
            
            matched = None
            if s_type == "food":
                if name in food_coord_map:
                    matched = {"location": food_coord_map[name]}
            else:
                for ep in pois:
                    if ep["name"] == name:
                        matched = ep
                        break
                        
            if not matched:
                try:
                    q_city = slot_city or (cities_list[0] if cities_list else "")
                    q_name = f"{q_city}{name}" if q_city and q_city not in name else name
                    coord = amap.geocode(q_name, q_city)
                    if coord:
                        c_coord = amap.geocode(q_city)
                        if c_coord:
                            _dist = abs(coord[0]-c_coord[0])*111 + abs(coord[1]-c_coord[1])*111
                            if _dist < 50:
                                matched = {"location": list(coord)}
                except:
                    pass
                    
            entry = {
                "name": name,
                "location": matched["location"] if matched else list(fallback_coord),
                "address": s.get("address","") or (matched.get("address","") if matched else ""),
                "rating": s.get("rating","") or (matched.get("rating","") if matched else ""),
                "cost": s.get("cost","") or (matched.get("cost","") if matched else ""),
                "time_slot": s.get("time_slot",""),
                "transit": s.get("transit",""),
                "note": s.get("note",""),
                "type": s_type,
                "city": slot_city,
            }
            if s_type == "food":
                entry["cuisine"] = s.get("cuisine", "")
                day_foods.append(entry)
            else:
                day_pois.append(entry)
                
        itinerary.append({
            "day": d.get("day", len(itinerary)+1),
            "label": d.get("label", f"Day {len(itinerary)+1}"),
            "summary": d.get("summary", ""),
            "accommodation_city": d.get("accommodation_city", ""),
            "pois": day_pois, "foods": day_foods,
        })

    context["itinerary"] = itinerary
    context["food_highlights"] = fusion_result.get("food_highlights", [])
    context["overall_note"] = fusion_result.get("overall_note", "")
    print(f"  ✅ Fusion完成: {len(itinerary)} 天")
    for d in itinerary:
        print(f"    Day {d['day']} [{d['label']}]: {len(d['pois'])}景点 + {len(d.get('foods',[]))}餐厅")
    return context


# ====================================================================
# Step 7: (合并至Brochure — 不再生成独立HTML地图)
# ====================================================================
def step_7_render_html(context):
    """已合并至Step 9 brochure，此步跳过"""
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
    import re
    safe_city = re.sub(r'[^\w\u4e00-\u9fa5\-\.]', '_', city)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUTS_DIR, f"{safe_city}_travel_{ts}.md")
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

    # 生成图文手册
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
# Entry Point
# ====================================================================
def run_pipeline(city, days=2, use_research=False, manual_pois=None, prefs=None):
    global _stop_requested, _step_timings
    _stop_requested = False
    _step_timings = []
    pipeline_t0 = time.time()

    # 注册 Ctrl+C 信号处理器（二次确认）
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

        # 获取定制启用的步骤列表，默认全开启
        enabled_steps = prefs.get("enabled_steps", ["research", "enrich", "distance", "tips"])

        _check_stop("Step 1")
        with StepTimer("Step 1 初始化"):
            context = step_1_init(city, days, preferences=prefs, manual_pois=manual_pois)

        _check_stop("Step 2")
        if "research" in enabled_steps:
            with StepTimer("Step 2 小红书调研"):
                context = step_2_research(context)
        else:
            print("⏭️  跳过 Step 2 小红书调研 (用户配置禁用)")
            context["research_notes"] = []
            context["note_contents"] = []
            context["xhs_pois"] = {"sights": [], "foods": []}
            context["xhs_sight_names"] = []
            context["xhs_food_data"] = []

        _check_stop("Step 3")
        with StepTimer("Step 3 POI地理编码"):
            context = step_3_geocode(context, manual_pois)

        _check_stop("Step 4")
        if "enrich" in enabled_steps:
            with StepTimer("Step 4 POI丰富+美食"):
                context = step_4_enrich(context)
        else:
            print("⏭️  跳过 Step 4 POI丰富+美食 (用户配置禁用)")
            # 降级：直接将 step_3_geocode 的坐标和名称放到 enriched 中
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
        if "distance" in enabled_steps:
            with StepTimer("Step 5 距离矩阵"):
                context = step_5_distance_matrix(context)
        else:
            print("⏭️  跳过 Step 5 距离矩阵 (用户配置禁用)")
            context["distance_matrix"] = {"matrix": [], "labels": []}

        _check_stop("Step 6")
        with StepTimer("Step 6 对抗辩论规划"):
            context = step_6_plan_itinerary(context)

        _check_stop("Step 7")
        context = step_7_render_html(context)

        # Step 8 + Step 8.5 并行/串行执行
        _check_stop("Step 8")
        if "tips" in enabled_steps:
            with StepTimer("Step 8+8.5 报告+建议"):
                with ThreadPoolExecutor(max_workers=2) as ex:
                    f8 = ex.submit(step_8_generate_report, copy.deepcopy(context))
                    f85 = ex.submit(step_85_tips, copy.deepcopy(context))
                    ctx8 = f8.result()
                    ctx85 = f85.result()
                # 合并两个并行步骤的输出
                context["report_path"] = ctx8.get("report_path")
                context["travel_tips"] = ctx85.get("travel_tips", {})
                context["weather"] = ctx85.get("weather", {})
        else:
            with StepTimer("Step 8 报告"):
                context = step_8_generate_report(context)
                context["travel_tips"] = {}
                context["weather"] = {}

        _check_stop("Step 9")
        with StepTimer("Step 9 图文手册"):
            context = step_9_deliver(context)

    except PipelineStoppedError as e:
        print(f"\n🛑 Pipeline 已停止: {e}")
        print("  已完成的步骤成果已保留。")
    finally:
        # 恢复原始信号处理器
        signal.signal(signal.SIGINT, original_handler)
        # 打印耗时汇总
        total_elapsed = time.time() - pipeline_t0
        print(f"\n⏱️  Pipeline 总耗时: {total_elapsed:.1f}s")
        _print_timing_summary()

    return context


# ====================================================================
# Goal Parser: 自然语言 → 结构化参数
# ====================================================================
def _parse_budget(budget_str, days=2, people_count=2):
    """解析预算字符串，返回(每人每天预算, 总预算)"""
    if not budget_str:
        return (None, None)
    import re
    nums = re.findall(r'\d+', budget_str.replace(',', ''))
    if not nums:
        return (None, None)
    # 取最大的数字作为预算值（排除人数、天数等小数字）
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
    import time
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
- people_count: 提取出行人数。例如“我们四个人” -> 4，“三口之家” -> 3。如果未明示，默认输出 2。

【当前季节】6月底夏季，推荐避暑/玩水/室内景点。

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
        # 自然语言模式
        city, days, pois, prefs = _parse_goal(args.goal)
        if args.city: city = args.city  # --city可覆盖
        if args.days: days = args.days  # --days可覆盖
        if args.pois: pois = [p.strip() for p in args.pois.split(",") if p.strip()]
        if args.start_city: prefs["start_city"] = args.start_city  # --start-city可覆盖
        print(f"\n{'='*50}")
        print(f"🎯 目标: {args.goal}")
        print(f"{'='*50}")
        run_pipeline(city, days, args.research, pois, prefs)
    else:
        # 传统参数模式
        city = args.city or "上海"
        days = args.days or 2
        pois = [p.strip() for p in args.pois.split(",") if p.strip()] if args.pois else None
        prefs = {"start_city": args.start_city} if args.start_city else None
        run_pipeline(city, days, args.research, pois, prefs)
