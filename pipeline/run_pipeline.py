"""
Travel-Itinerary-Generator · Pipeline 固定流程
================================================
Usage:
    python pipeline/run_pipeline.py --city 上海 --days 2
    python pipeline/run_pipeline.py --city 上海 --days 2 --pois "外滩,豫园"
    python pipeline/run_pipeline.py --city 上海 --days 2 --research

步骤列表（9步工序链）:
"""

import sys, os, json, argparse, time, copy, threading
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

    # 精读前 5 篇笔记
    if all_notes:
        print(f"  📖 精读 {min(5, len(all_notes))} 篇笔记...")
        for n in all_notes[:5]:
            url = n.get("url", "")
            if url:
                content = xhs.read_note_content(url)
                if content:
                    note_contents.append(content)
                    print(f"     ✅ {n.get('title','')[:30]}")
            time.sleep(0.5)

    # LLM提取结构化景点+美食
    xhs_pois = {"sights": [], "foods": []}
    if note_contents:
        notes_text = "\n\n".join(
            f"【笔记{i+1}】\n{n.get('content','')[:2000]}"
            for i, n in enumerate(note_contents)
        )
        extract_prompt = f"""你是一名旅行信息整理专家。从以下{city}的小红书笔记中，提取所有提到的【景点】和【餐厅/美食】。

要求：
1. 景点包括：自然风光、地标建筑、公园、博物馆、古镇等
2. 餐厅包括：餐馆、小吃店、咖啡馆、茶室等
3. 每个条目给出名称和简短描述（为什么值得去）
4. 优先提取笔记中反复提及的高频推荐
5. 按推荐热度排序，最多各取10个

笔记内容：
{notes_text}

输出格式（纯JSON，不要额外文字）：
{{"sights": [{{"name":"名称","reason":"推荐理由"}}], "foods": [{{"name":"名称","reason":"推荐理由","cuisine":"菜系类型"}}]}}"""

        try:
            result = call_deepseek("提取POI。返回纯JSON。", extract_prompt, temperature=0.1, max_tokens=3000)
            if isinstance(result, dict):
                xhs_pois["sights"] = result.get("sights", [])
                xhs_pois["foods"] = result.get("foods", [])
                print(f"  🤖 LLM提取: {len(xhs_pois['sights'])}个景点 + {len(xhs_pois['foods'])}家餐厅")
                for s in xhs_pois["sights"][:3]:
                    print(f"     🏛️ {s['name']}")
                for f in xhs_pois["foods"][:3]:
                    print(f"     🍴 {f['name']} — {f.get('cuisine','')}")
        except Exception as e:
            print(f"  ⚠️ LLM提取失败: {e}")
    else:
        print("  ⚠️ 未获取到小红书笔记内容")

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
    """高德地理编码: 小红书提取的景点名 → 坐标"""
    print(f"\n{'='*50}")
    print(f"Step 3/9: POI地理编码 🗺️")
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

    geocoded = []
    for name in pois_to_code:
        coord = amap.geocode(name, city)
        if coord:
            geocoded.append({"name": name, "location": coord})
            print(f"  ✅ {name:20s} → ({coord[0]:.4f}, {coord[1]:.4f})")
        else:
            # 降级 Mock 坐标方案
            h = hash(name)
            city_center = amap.geocode(city)
            if city_center:
                base_lng, base_lat = city_center
            else:
                base_lng, base_lat = 121.4737, 31.2304
                if city == "北京":
                    base_lng, base_lat = 116.4074, 39.9042
                elif city == "杭州":
                    base_lng, base_lat = 120.1535, 30.2874
            offset_lng = ((h % 100) - 50) * 0.001
            offset_lat = (((h // 100) % 100) - 50) * 0.001
            coord = (base_lng + offset_lng, base_lat + offset_lat)
            geocoded.append({"name": name, "location": coord})
            print(f"  ⚠️ {name:20s} → 编码失败，使用 Mock 坐标 ({coord[0]:.4f}, {coord[1]:.4f})")
        time.sleep(0.3)

    context["poi_geocoded"] = geocoded
    n = len(geocoded)
    print(f"  成功: {n}/{len(pois_to_code)}")
    return context


# ====================================================================
# Step 4: POI数据丰富 + 美食对接（小红书→高德验证）
# ====================================================================
def step_4_enrich(context):
    """逆地理编码拿地址 → 小红书美食列表对接高德坐标验证"""
    print(f"\n{'='*50}")
    print(f"Step 4/9: POI丰富 + 美食对接 🍽️（小红书→高德验证）")
    print(f"{'='*50}")
    enriched = []
    city = context["city"]
    all_food = []

    for poi in context["poi_geocoded"]:
        loc = poi["location"]
        detail = amap.enrich_poi(poi["name"], city)
        poi_info = {
            "name": poi["name"],
            "location": list(loc),
            "address": detail.get("address", "") if detail else "",
            "district": detail.get("district", "") if detail else "",
            "nearby_food": [],  # 不再搜索附近餐厅，来源替换为小红书
        }
        enriched.append(poi_info)
        print(f"  ✅ {poi['name']:20s} | {poi_info.get('address','')[:30]}")
        time.sleep(0.3)

    # 从小红书数据提取美食（高德验证坐标）
    xhs_foods = context.get("xhs_food_data", [])
    prefs = context.get("preferences", {})
    for f in xhs_foods:
        name = f.get("name", "")
        if name and name not in [x["name"] for x in all_food]:
            # 预算过滤
            budget_per = prefs.get("_budget_parsed", (None, None))
            daily_budget = budget_per[0]
            # 估算餐厅人均（无数据时按菜系估算）
            cuisines_price = {"小吃": 20, "面": 25, "咖啡": 30, "快餐": 35,
                           "川菜": 60, "湘菜": 55, "粤菜": 80, "杭帮": 70, "本帮": 65,
                           "日料": 120, "西餐": 150, "火锅": 100, "烧烤": 80}
            est_cost = cuisines_price.get(f.get("cuisine", "")[:2], 50)
            if daily_budget and est_cost > daily_budget * 1.5:
                continue  # 超出预算，跳过

            # 尝试高德验证坐标
            coord = amap.geocode(name, city)
            all_food.append({
                "name": name,
                "cuisine": f.get("cuisine", ""),
                "reason": f.get("reason", ""),
                "rating": "",  # 小红书不直接提供评分
                "location": list(coord) if coord else [121.47, 31.23],
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
        food_nearby = p.get("nearby_food", [])
        pois_data.append({
            "name": p["name"],
            "lng": loc[0], "lat": loc[1],
            "address": p.get("address", ""),
            "district": p.get("district", ""),
            "nearby_food": [{"name": f["name"], "rating": f.get("rating",""), "cost": f.get("cost",""),
                             "tag": f.get("tag",""), "distance": f.get("distance",0)} for f in food_nearby[:3]],
        })

    food_json = json.dumps([{"name": f["name"], "rating": f.get("rating",""), "cost": f.get("cost",""),
                             "tag": f.get("tag",""), "address": f.get("address","")} for f in food_list],
                           ensure_ascii=False, indent=2)
    input_json = json.dumps({"city": city, "days": days, "pois": pois_data,
                             "distance_matrix_km": dist_matrix.get("matrix", []),
                             "labels": dist_matrix.get("labels", [])}, ensure_ascii=False, indent=2)

    format_instruction = '输出JSON: {"days":[{"day":1,"label":"区域","summary":"","slots":[{"type":"sight/food","name":"名称","time":"时段","transit":"","note":"","cuisine":"","cost":"","rating":""}]}]}'

    # ---- Bull Prompt ----
    bull_prompt = f"""你是一名旅行规划师（Bull — 高效派）。规划【景点+美食】一体的高效行程。
【景点数据】{input_json}
【城市推荐餐厅】{food_json}
要求：每个景点配附近餐厅，时间标注sight/food
{format_instruction}"""

    # ---- Bear Prompt ----
    bear_prompt = f"""你是一名旅行规划师（Bear — 悠闲派）。规划【景点+美食】一体品质行程。
【景点数据】{input_json}
【城市推荐餐厅】{food_json}
要求：每天最多4景点+2餐厅，每餐≥60分钟，推荐评分≥4.0
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
        fusion_prompt = f"""首席旅行规划官。综合两位分析师方案做出最终融合。

Bull方案: {json.dumps(bull_result, ensure_ascii=False)}
Bear方案: {json.dumps(bear_result, ensure_ascii=False)}

【原始数据】{input_json}
【餐厅】{food_json}

裁决原则：
1. 采纳Bull路线效率 + Bear用餐体验
2. 景点和餐厅交替安排，每天≥1次正餐推荐
3. 标注餐厅菜系、人均
4. 每天≤4景点+2餐厅

输出JSON:
{{"days":[{{"day":1,"label":"主题","summary":"概要",
    "slots":[{{"type":"sight","name":"","time_slot":"","transit":"","note":""}},
             {{"type":"food","name":"","time_slot":"","cuisine":"","cost":"","rating":"","note":""}}]}}],
  "overall_note":"","food_highlights":["必吃1","必吃2"]}}"""

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

    # 城市中心坐标（用于验证合理性）
    city_center_coord = amap.geocode(city)
    if city_center_coord:
        city_center = list(city_center_coord)
    else:
        city_center = [120.0, 30.0]  # 默认华东
        if "安吉" in city or "杭州" in city or "浙江" in city:
            city_center = [119.6, 30.5]
        elif "上海" in city:
            city_center = [121.47, 31.23]
        elif "北京" in city:
            city_center = [116.4, 39.9]
        elif "广州" in city or "深圳" in city or "广东" in city:
            city_center = [113.3, 23.1]
        elif "成都" in city or "四川" in city:
            city_center = [104.1, 30.6]

    itinerary = []
    for d in days_out:
        day_pois, day_foods = [], []
        for s in d.get("slots", []):
            s_type = s.get("type", "sight")
            name = s["name"]
            matched = None
            if s_type == "food":
                if name in food_coord_map:
                    matched = {"location": food_coord_map[name]}
                else:
                    try:
                        coord = amap.geocode(name, city)
                        if coord:
                            _dist = abs(coord[0]-city_center[0])*111 + abs(coord[1]-city_center[1])*111
                            if _dist < 100:
                                matched = {"location": list(coord)}
                            else:
                                print(f"     ⚠️ {name}坐标偏离({coord[0]:.2f},{coord[1]:.2f}),跳过")
                    except:
                        pass
            else:
                for ep in pois:
                    if ep["name"] == name:
                        matched = ep
                        break
            entry = {
                "name": name,
                "location": matched["location"] if matched else [121.47, 31.23],
                "address": s.get("address","") or (matched.get("address","") if matched else ""),
                "rating": s.get("rating","") or (matched.get("rating","") if matched else ""),
                "cost": s.get("cost","") or (matched.get("cost","") if matched else ""),
                "time_slot": s.get("time_slot",""),
                "transit": s.get("transit",""),
                "note": s.get("note",""),
                "type": s_type,
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
                          start_city=prefs.get("start_city", ""))
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
    if not prefs:
        prefs = {}
    
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

    context = step_1_init(city, days, preferences=prefs, manual_pois=manual_pois)
    context = step_2_research(context)
    context = step_3_geocode(context, manual_pois)

    # Step 4+5 串行（共享context，不能并行）
    context = step_4_enrich(context)
    context = step_5_distance_matrix(context)

    # Step 6: Bull+Bear 并行调用（各自独立API请求）
    context = step_6_plan_itinerary(context)
    context = step_7_render_html(context)
    context = step_8_generate_report(context)
    context = step_85_tips(context)
    context = step_9_deliver(context)
    return context


# ====================================================================
# Goal Parser: 自然语言 → 结构化参数
# ====================================================================
def _parse_budget(budget_str, days=2):
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
    if '人均' in budget_str or '每人' in budget_str:
        if '天' in budget_str or '日' in budget_str:
            daily_per_person = total
        else:
            daily_per_person = total // max(days, 1)
        return (max(daily_per_person, 1), daily_per_person * max(days, 1) * 2)
    # 默认视为总预算
    daily_per_person = total // (2 * max(days, 1))
    return (max(daily_per_person, 1), daily_per_person * max(days, 1) * 2)


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

【当前季节】6月底夏季，推荐避暑/玩水/室内景点。

输出纯JSON，严格按以下格式，不要多余文字：
{{"city":"城市名","start_city":"出发城市","days":2,"start_date":"YYYY-MM-DD","pois":["景点1","景点2"],"transport":"方式","budget":"描述","preference":"描述","accommodation":"描述"}}"""

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
            print(f"\n🎯 目标解析结果:")
            print(f"   出发城市: {start_city or '未指定(将通过IP定位)'}")
            print(f"   目的地: {city}")
            print(f"   出行日期: {start_date}")
            print(f"   天数: {days}")
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
                "_budget_parsed": _parse_budget(budget, days),
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
