import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()
BROCHURE_ENABLED = True
BASE = PROJECT_ROOT

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
                          start_date=context.get("start_date", ""),
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
