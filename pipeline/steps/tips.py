import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

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
