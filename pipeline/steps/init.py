import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

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
