import sys, os, json, time, copy, re, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.log import get_logger
logger = get_logger("travel_pipeline")
from utils.paths import PROJECT_ROOT

from utils.amap_api import AMapClient
amap = AMapClient()
BROCHURE_ENABLED = True
BASE = PROJECT_ROOT

def _export_files(context):
    """在手册/报告同目录输出 <base>.ics/.gpx/.kml；任一导出失败只记 warning，不影响主产物。"""
    base_path = context.get("brochure_path") or context.get("report_path") or context.get("html_path")
    if not base_path or not context.get("itinerary"):
        return {}
    base = os.path.splitext(base_path)[0]
    written = {}
    try:
        from utils import exporters
    except Exception as e:
        logger.warning(f"  ⚠️ 导出模块加载失败: {e}")
        return written
    for ext, fn in exporters.EXPORTERS:
        try:
            content = fn(context)
            path = f"{base}.{ext}"
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            written[ext] = path
        except Exception as e:
            logger.warning(f"  ⚠️ {ext} 导出跳过: {e}")
    if written:
        context["export_paths"] = written
    return written


def step_9_deliver(context):
    """归档 + 生成图文手册（含出行建议）"""
    logger.info(f"\n{'='*50}")
    logger.info(f"Step 9/9: 交付完成 ✅")
    logger.info(f"{'='*50}")

    if BROCHURE_ENABLED and context.get("itinerary"):
        try:
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
                          research_source=prefs.get("research_source", ""),
                          flyai_prices=context.get("flyai_prices", {}),
                          validation=context.get("validation"))
            context["brochure_path"] = path
            logger.info(f"  📖 手册: {path}")
        except Exception as e:
            logger.warning(f"  ⚠️ 手册生成跳过: {e}")

    export_paths = _export_files(context)

    print(f"\n  📄 HTML地图: {context.get('html_path','')}")
    print(f"  📄 MD报告:  {context.get('report_path','')}")
    if context.get("brochure_path"):
        print(f"  📖 图文手册: {context['brochure_path']}")
    for ext, label in (("ics", "日历(ics)"), ("gpx", "GPX 路线"), ("kml", "KML 路线")):
        if export_paths.get(ext):
            print(f"  🗓️ {label}: {export_paths[ext]}")
    print(f"  ✨ 多方案辩论: ✅")
    print(f"{'='*50}\n")
    return context
