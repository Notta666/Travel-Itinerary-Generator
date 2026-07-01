import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

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

    ticket_data = {}
    for p in poi_names:
        time.sleep(3.5)  # 主动增加延时，防止高频并发触发风控
        try:
            ticket_data[p["name"]] = client.query_poi_ticket(p["name"], p["city"])
        except Exception as e:
            ticket_data[p["name"]] = {"price_min": None, "price_max": None, "source": "fail"}

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
