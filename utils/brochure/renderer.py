"""
Jinja2-based brochure renderer.
Replaces the old f-string HTML generation with template-based rendering.
"""
import os, json, time
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _get_env():
    """Get the Jinja2 environment, caching the template loader."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,  # We render trusted HTML content
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
    generated_ts,
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
        generated_ts=generated_ts,
    )
