"""
Step 6: 对抗性辩论路线规划 (Bull / Bear / Fusion)
====================================================
"""
import json, copy, time, logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("travel_pipeline")


def _build_lodging_instruction(context):
    """根据 context 动态生成住宿与时间限制规则"""
    city = context.get("city", "")
    days = context.get("days", 2)
    start_date = context.get("start_date", "")
    prefs = context.get("preferences", {})
    goal = prefs.get("goal", "")

    # 如果用户 goal 中已包含详细住宿规则，直接注入不覆盖
    if "住宿" in goal and ("住" in goal or "酒店" in goal or "宿" in goal):
        return f"""
【基本住宿规则】:
根据 {days} 天 {days-1} 晚的行程安排，每天游玩后入住当地酒店。
最后一天行程结束后无需安排住宿。
"""

    # 基本住宿指令
    lines = [
        f"【基本住宿与时间限制规则（供参考）】:",
        f"1. 这是一次 {days}天{days-1}晚的行程，出发日期为 {start_date or '未指定'}。",
        f"2. 每天白天在对应城市游玩，晚上在当地安排住宿（最后一天除外）。",
        f"3. 需根据每日活动路线，合理安排住宿城市，避免绕路。",
        f"4. 具体住宿分配：",
    ]

    for d in range(1, days + 1):
        if d < days:
            lines.append(f"   Day {d}: 白天游玩 → 晚上入住当地或顺路城市酒店（过夜）")
        else:
            lines.append(f"   Day {days}: 白天游玩 → 行程结束，无需过夜住宿")

    return "\n".join(lines)


def step_6_plan_itinerary(context, amap=None, progress_callback=None):
    """三段式DeepSeek API:
       Bull(高效派) → 密集景点+就近配餐厅
       Bear(悠闲派) → 品质体验+用餐推荐
       Fusion(综合) → 最终行程(景点+餐厅交替)
    """
    _report = lambda step, msg, pct: progress_callback and progress_callback(step, msg, pct)
    _report("plan_itinerary", "Step 6/9: 对抗性辩论路线规划 🐂🐻⚖️", 50)

    from utils.llm import call_deepseek

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

    lodging_instruction = _build_lodging_instruction(context)

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

        # ---- Fusion Prompt (压缩Bull/Bear摘要) ----
        def _summarize_plan(result):
            """从Bull/Bear完整结果中提取 day/label/poi_names/key_notes 摘要"""
            days = result.get("days", []) if isinstance(result, dict) else []
            summary = []
            for d in days:
                slots = d.get("slots", [])
                sight_names = [s["name"] for s in slots if s.get("type") != "food"]
                food_names = [s["name"] for s in slots if s.get("type") == "food"]
                notes = [s.get("note", "") for s in slots if s.get("note")]
                summary.append({
                    "day": d.get("day"),
                    "label": d.get("label"),
                    "sights": sight_names,
                    "foods": food_names,
                    "key_notes": notes[:3],
                })
            return json.dumps(summary, ensure_ascii=False)

        bull_summary = _summarize_plan(bull_result)
        bear_summary = _summarize_plan(bear_result)

        fusion_prompt = f"""首席旅行规划官。综合两位分析师（高效派 Bull 与 悠闲避雷派 Bear）的辩论方案做出最终融合。

【用户特别行程与动线要求】
{context.get("goal", "无")}

Bull高效方案摘要: {bull_summary}
Bear悠闲避雷方案摘要: {bear_summary}

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
                except Exception:
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
    _report("plan_itinerary", f"✅ Fusion完成: {len(itinerary)} 天", 60)
    return context
