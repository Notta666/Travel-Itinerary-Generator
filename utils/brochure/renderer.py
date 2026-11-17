"""
Jinja2-based brochure renderer.
Replaces the old f-string HTML generation with template-based rendering.
"""
import os, json, time
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _fmt_ttl(hours):
    if hours % 24 == 0 and hours >= 24:
        return f"{int(hours // 24)} 天"
    return f"{int(hours)} 小时"


def _data_notes():
    """手册页脚「数据说明」：数据源与时效规则（TTL 取自 utils.provenance，保持单一事实来源）。"""
    from utils import provenance as pv
    return [
        "数据来源：高德地图（POI、地址、营业时间、周边酒店价格）；飞猪 FlyAI（机票/高铁/酒店/门票价格）；"
        "高德天气与 Open-Meteo（天气，超出预报范围时为往年同期参考）。",
        "每条价格、营业时间、天气与交通时刻旁标注「来源 · 更新于 MM-DD HH:mm」，时间为数据实际取得时间（缓存命中则为缓存写入时间）。",
        f"时效规则：价格/门票 {_fmt_ttl(pv.TTL_PRICE_HOURS)}、交通时刻 {_fmt_ttl(pv.TTL_SCHEDULE_HOURS)}、"
        f"营业时间 {_fmt_ttl(pv.TTL_OPENING_HOURS)}、天气 {_fmt_ttl(pv.TTL_WEATHER_HOURS)}；"
        "超过时效的数据会灰显并提示「可能已变化，出行前请核实」。",
        "标注「AI 估算，请核实」的数值由大模型生成，并非实时报价，请以商家或官方渠道为准。",
        "标注「未在地图中检索到，请核实」的地点未能在高德地图中找到同名 POI，请出行前自行确认其是否存在。",
    ]


def _get_env():
    """Get the Jinja2 environment, caching the template loader."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "htm"]),
    )


def render_brochure(
    city,
    trip_label,
    date_range_str,
    accommodation,
    cover_extra_html,
    day_html,
    hotel_html,
    tips_html,
    weather_html,
    budget_html,
    tickets_html,
    food_highlights_html,
    transport_html,
    day_map_labels,
    map_items_json,
    all_hotels_json,
    research_source,
    generated_ts,
    validation_removed=0,
):
    """
    Render the brochure HTML from the Jinja2 template.
    
    Args:
        city: Destination city name
        trip_label: e.g. "三日深度游"
        date_range_str: e.g. "7月5日—7日"
        accommodation: Accommodation description
        cover_extra_html: Extra cover metadata HTML
        day_html: Joined HTML string for all day sections
        hotel_html: Joined HTML string for all hotel sections
        tips_html: Travel tips section HTML
        weather_html: Weather section HTML
        budget_html: Budget section HTML
        food_highlights_html: Food highlights section HTML
        transport_html: Transport guide section HTML
        day_map_labels: List of dicts with "day" keys for map tabs
        map_items_json: JSON string for map markers
        all_hotels_json: JSON string for hotel data
        generated_ts: Generation timestamp string
        
    Returns:
        Complete HTML string for the brochure page.
    """
    if not HAS_JINJA2:
        raise RuntimeError(
            "Jinja2 is required for brochure rendering. "
            "Install it with: pip install jinja2>=3.0.0"
        )

    env = _get_env()
    template = env.get_template("brochure.html")

    return template.render(
        city=city,
        trip_label=trip_label,
        date_range_str=date_range_str,
        accommodation=accommodation,
        cover_extra_html=cover_extra_html,
        day_html=day_html,
        hotel_html=hotel_html,
        tips_html=tips_html,
        weather_html=weather_html,
        budget_html=budget_html,
        tickets_html=tickets_html,
        food_highlights_html=food_highlights_html,
        transport_html=transport_html,
        day_map_labels=day_map_labels,
        map_items_json=map_items_json,
        all_hotels_json=all_hotels_json,
        research_source=research_source,
        generated_ts=generated_ts,
        validation_removed=validation_removed,
        data_notes=_data_notes(),
    )
