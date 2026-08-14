import copy
import re
import datetime
from pipeline.pipeline_context import PipelineContext

try:
    from pipeline.run_pipeline import PipelineStoppedError
except ImportError:
    class PipelineStoppedError(Exception):
        pass


def run_multi_city(pipeline_func, city, days, use_research, manual_pois, prefs, progress_callback, multi_cities_list, cancel_event=None):
    from pipeline.steps.init import step_1_init
    
    context = step_1_init(city, days, preferences=prefs, manual_pois=manual_pois, multi_cities=multi_cities_list)
    if days < len(multi_cities_list):
        raise ValueError(f"总天数 ({days}) 不能少于城市数 ({len(multi_cities_list)})")
    days_per_city = days // len(multi_cities_list)
    rem = days % len(multi_cities_list)

    city_contexts = {}
    combined_itinerary = []
    combined_food_highlights = []
    combined_overall_note = "【多城市串联路线规划】\n"
    
    current_date = context.get("start_date") or datetime.date.today().strftime("%Y-%m-%d")

    for idx, c in enumerate(multi_cities_list):
        if cancel_event and cancel_event.is_set():
            raise PipelineStoppedError("Pipeline cancelled")
            
        c_days = days_per_city + (1 if idx < rem else 0)
        c_prefs = copy.deepcopy(prefs)
        c_prefs["multi_cities"] = []
        c_prefs["start_date"] = current_date
        c_prefs["is_sub_pipeline"] = True
        
        if idx > 0:
            c_prefs["start_city"] = multi_cities_list[idx - 1]
        
        print(f"\n🗺️ [多城市模式] 正在为城市 {c} ({idx+1}/{len(multi_cities_list)}) 生成行程，天数: {c_days}天，开始日期: {current_date}")
        
        sub_ctx = pipeline_func(
            city=c, days=c_days, use_research=use_research,
            manual_pois=None, prefs=c_prefs,
            progress_callback=progress_callback, multi_cities=[],
            cancel_event=cancel_event
        )
        
        if sub_ctx.get("error"):
            print(f"  ⚠️ [多城市模式] 城市 {c} 子管线执行异常: {sub_ctx['error']}，将跳过合并该城行程")
        
        city_contexts[c] = sub_ctx
        
        try:
            dt = datetime.datetime.strptime(current_date, "%Y-%m-%d")
            current_date = (dt + datetime.timedelta(days=c_days)).strftime("%Y-%m-%d")
        except Exception:
            pass

    total_days_accumulated = 0
    for idx, c in enumerate(multi_cities_list):
        sub_ctx = city_contexts.get(c, {})
        if sub_ctx.get("error"):
            continue
        sub_itinerary = sub_ctx.get("itinerary") or []
        c_days = days_per_city + (1 if idx < rem else 0)
        
        for item in sub_itinerary:
            new_item = copy.deepcopy(item)
            old_day = new_item.get("day", 1)
            new_day = total_days_accumulated + old_day
            new_item["day"] = new_day
            
            if "label" in new_item:
                label_clean = re.sub(r"^Day \d+:\s*", "", new_item["label"])
                label_clean = re.sub(r"^Day \d+\s*", "", label_clean)
                new_item["label"] = f"Day {new_day}: {label_clean}"
            
            new_item["accommodation_city"] = c

            # P2-23: 多城市过渡日平滑衔接打磨（城际交通、退房与抵达时间过渡）
            if idx > 0 and old_day == 1:
                prev_city = multi_cities_list[idx - 1]
                trans_msg = f"【城际交通过渡】从 {prev_city} 退房出发前往 {c}，预计城际耗时 1~2.5 小时，建议午间抵达办理行李寄存或入住后开启游览。"
                if new_item.get("summary"):
                    new_item["summary"] = f"{trans_msg} {new_item['summary']}"
                else:
                    new_item["summary"] = trans_msg
                new_item["transition_from"] = prev_city
                
                # 平滑首个 slot 的交通提示
                if new_item.get("pois"):
                    first_poi = new_item["pois"][0]
                    if not first_poi.get("transit") or first_poi.get("transit") == "出发":
                        first_poi["transit"] = f"城际交通: {prev_city} → {c} (抵达后前往)"
                if new_item.get("slots"):
                    for s in new_item["slots"]:
                        if not s.get("transit") or s.get("transit") == "出发":
                            s["transit"] = f"城际交通: {prev_city} → {c} (抵达后前往)"
                            break
            
            combined_itinerary.append(new_item)
        
        total_days_accumulated += c_days

        for fh in sub_ctx.get("food_highlights", []):
            if fh not in combined_food_highlights:
                combined_food_highlights.append(fh)
        
        if sub_ctx.get("overall_note"):
            combined_overall_note += f"\n### {c} 规划说明\n{sub_ctx['overall_note']}\n"

    # P2-23: 注入多城市过渡与城际动线综合建议
    if len(multi_cities_list) > 1:
        combined_overall_note += "\n### 多城市过渡与城际衔接建议 (Transition Guide)\n"
        for i in range(1, len(multi_cities_list)):
            from_c = multi_cities_list[i - 1]
            to_c = multi_cities_list[i]
            combined_overall_note += f"- **{from_c} → {to_c} 过渡日**：建议在前序城市游览结束后上午出发，乘坐高铁/城际巴士抵达 {to_c}，先至酒店寄存行李再轻装出行。\n"

    combined_flyai = {"available": False, "tickets": {}, "transport_legs": []}
    
    # Calculate days for each city's starting leg
    leg_start_day = 1
    for idx, c in enumerate(multi_cities_list):
        c_days = days_per_city + (1 if idx < rem else 0)
        sub_ctx = city_contexts.get(c, {})
        if sub_ctx.get("error"):
            leg_start_day += c_days
            continue
        sub_flyai = sub_ctx.get("flyai_prices", {})
        if sub_flyai.get("available"):
            combined_flyai["available"] = True
            if "tickets" in sub_flyai:
                combined_flyai["tickets"].update(sub_flyai["tickets"])
            
            # Determine start city for this leg
            if idx == 0:
                s_city = prefs.get("start_city", "") or "出发地"
            else:
                s_city = multi_cities_list[idx - 1]
                
            # Build transport leg for this city hop
            _leg_type = "flight" if sub_flyai.get("flight", {}).get("items") else ("train" if sub_flyai.get("train", {}).get("items") else "")
            if _leg_type:
                items = sub_flyai[_leg_type]["items"]
                if items:
                    route_str = f"{s_city}-{c.split(',')[0]}"
                    combined_flyai["transport_legs"].append({
                        "label": f"Day {leg_start_day} {route_str}",
                        "type": _leg_type,
                        "items": [items[0]]
                    })
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
                        combined_flyai["hotel"]["cheapest"] = min(all_hotels, key=lambda x: x.get("price", float('inf'))).get("price")
                        combined_flyai["hotel"]["count"] = len(all_hotels)
        
        leg_start_day += c_days
    
    context["flyai_prices"] = combined_flyai
    context["itinerary"] = combined_itinerary
    context["food_highlights"] = combined_food_highlights
    context["overall_note"] = combined_overall_note
    context["city_itineraries"] = {c: city_contexts[c].get("itinerary") for c in multi_cities_list if c in city_contexts and not city_contexts[c].get("error")}

    return context
