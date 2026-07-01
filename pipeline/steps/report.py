import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

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
    safe_city = re.sub(r'[^\w\u4e00-\u9fa5\-\.]', '_', city)
    ts = time.strftime("%Y%m%d_%H%M%S")
    outputs_dir = os.path.join(PROJECT_ROOT, "outputs")
    path = os.path.join(outputs_dir, f"{safe_city}_travel_{ts}.md")
    os.makedirs(outputs_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    context["report_path"] = path
    print(f"  ✅ 报告: {path}")
    return context
