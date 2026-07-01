import copy
import re
import datetime
from pipeline.pipeline_context import PipelineContext

def run_multi_city(pipeline_func, city, days, use_research, manual_pois, prefs, progress_callback, multi_cities_list, cancel_event=None):
    from pipeline.steps.init import step_1_init
    
    context = step_1_init(city, days, preferences=prefs, manual_pois=manual_pois, multi_cities=multi_cities_list)
    days_per_city = days // len(multi_cities_list)
    rem = days % len(multi_cities_list)

    city_contexts = {}
    combined_itinerary = []
    combined_food_highlights = []
    combined_overall_note = "【多城市串联路线规划】\\n"
    
    current_date = context.get("start_date") or datetime.date.today().strftime("%Y-%m-%d")

    for idx, c in enumerate(multi_cities_list):
        if cancel_event and cancel_event.is_set():
            raise Exception("Pipeline cancelled")
            
        c_days = days_per_city + (rem if idx == 0 else 0)
        c_prefs = copy.deepcopy(prefs)
        c_prefs["multi_cities"] = []
        c_prefs["start_date"] = current_date
        
        if idx > 0:
            c_prefs["start_city"] = multi_cities_list[idx - 1]
        
        print(f"\\n🗺️ [多城市模式] 正在为城市 {c} ({idx+1}/{len(multi_cities_list)}) 生成行程，天数: {c_days}天，开始日期: {current_date}")
        
        sub_ctx = pipeline_func(
            city=c, days=c_days, use_research=use_research,
            manual_pois=None, prefs=c_prefs,
            progress_callback=progress_callback, multi_cities=[],
            cancel_event=cancel_event
        )
        
        city_contexts[c] = sub_ctx
        
        try:
            dt = datetime.datetime.strptime(current_date, "%Y-%m-%d")
            current_date = (dt + datetime.timedelta(days=c_days)).strftime("%Y-%m-%d")
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
                label_clean = re.sub(r"^Day \\d+:\\s*", "", new_item["label"])
                label_clean = re.sub(r"^Day \\d+\\s*", "", label_clean)
                new_item["label"] = f"Day {new_day}: {label_clean}"
            
            new_item["accommodation_city"] = c

            if idx > 0 and old_day == 1:
                # We used to inject a fake transit_slot here, but now we delegate it 
                # entirely to the standalone transport section in brochure rendering.
                pass
            
            combined_itinerary.append(new_item)
        
        total_days_accumulated += c_days

        for fh in sub_ctx.get("food_highlights", []):
            if fh not in combined_food_highlights:
                combined_food_highlights.append(fh)
        
        if sub_ctx.get("overall_note"):
            combined_overall_note += f"\\n### {c} 规划说明\\n{sub_ctx['overall_note']}\\n"

    combined_flyai = {"available": False, "tickets": {}, "transport_legs": []}
    
    # Calculate days for each city's starting leg
    leg_start_day = 1
    for idx, c in enumerate(multi_cities_list):
        c_days = days_per_city + (rem if idx == 0 else 0)
        sub_flyai = city_contexts[c].get("flyai_prices", {})
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
            else:
                # Mock a leg if flyai failed to find one for inter-city
                route_str = f"{s_city}-{c.split(',')[0]}"
                combined_flyai["transport_legs"].append({
                    "label": f"Day {leg_start_day} {route_str}",
                    "type": "bus",
                    "items": [{"price": 100, "segments": [{"duration_min": 120, "dep_time": "09:00", "arr_time": "11:00"}]}]
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
                        combined_flyai["hotel"]["cheapest"] = min(all_hotels, key=lambda x: x["price"])["price"]
                        combined_flyai["hotel"]["count"] = len(all_hotels)
        
        leg_start_day += c_days
    
    context["flyai_prices"] = combined_flyai
    context["itinerary"] = combined_itinerary
    context["food_highlights"] = combined_food_highlights
    context["overall_note"] = combined_overall_note
    context["city_itineraries"] = {c: city_contexts[c].get("itinerary") for c in multi_cities_list}

    return context
