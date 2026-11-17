# -*- coding: utf-8 -*-
"""
行程多格式导出（TR-4）：iCalendar(.ics) / GPX 1.1 / KML 2.2
==========================================================
全部手写标准格式，无第三方依赖。入参 ``itinerary_ctx`` 为 pipeline 的 context 字典：

- ``itinerary``: ``[{day, label, pois:[slot...], foods:[slot...]}, ...]``
  slot 字段：name / city / location=[lng, lat] / time_slot / transit / note / cost / cost_meta ...
- ``start_date``: ``YYYY-MM-DD``（第 N 天 = start_date + N-1）
- ``poi_enriched``: slot 自身无坐标时按名称回查
- ``city`` / ``task_id``（可选）：用于标题与 UID 稳定性

注意：高德坐标为 GCJ-02，本模块原样输出，不做 WGS-84 转换。
"""
import datetime
import hashlib
import re
import unicodedata
from xml.sax.saxutils import escape as _xml_escape

from utils import provenance
from utils.schema import _coords_from_mapping, normalize_name, parse_time_range

TZID = "Asia/Shanghai"
_PRODID = "-//travel-itinerary-generator//TR-4//CN"
_UID_DOMAIN = "travel-itinerary"
_DEFAULT_DURATION_MIN = 60

# 无具体钟点时的时段排序参考（分钟）；仅用于 GPX/KML 路线顺序，不生成定时事件
_PERIOD_ORDER = (("早", 480), ("上午", 540), ("午", 720), ("下午", 840), ("傍晚", 1050), ("晚", 1110), ("夜", 1200))

_SINGLE_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)")
_XML_BAD_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


# ---------------------------------------------------------------------------
#  通用：读取 context
# ---------------------------------------------------------------------------

def _ctx_get(ctx, key, default=None):
    return ctx.get(key, default) if isinstance(ctx, dict) else default


def _parse_start_date(ctx):
    raw = str(_ctx_get(ctx, "start_date", "") or "").strip()
    try:
        return datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _itinerary_id(ctx):
    ident = _ctx_get(ctx, "task_id") or _ctx_get(ctx, "itinerary_id")
    if ident:
        return str(ident)
    return f"{_ctx_get(ctx, 'city', '')}|{_ctx_get(ctx, 'start_date', '')}"


def _poi_index(ctx):
    idx = {}
    for p in _ctx_get(ctx, "poi_enriched", []) or []:
        if isinstance(p, dict) and p.get("name"):
            idx.setdefault(normalize_name(p["name"]), p)
    return idx


def _coords(slot, poi_idx):
    """(lat, lng) 或 (None, None)：slot 自身（lat/lng 或 location）优先，其次 poi_enriched 按名称。"""
    lat, lng = _coords_from_mapping(slot)
    if lat is not None and lng is not None:
        return lat, lng
    poi = poi_idx.get(normalize_name(slot.get("name")))
    if poi:
        return _coords_from_mapping(poi)
    return None, None


def _time_minutes(time_slot):
    """time_slot → (start_min, end_min) 或 None。支持 HH:MM-HH:MM 与单个 HH:MM（默认 60 分钟）。"""
    rng = parse_time_range(time_slot)
    if rng:
        return rng
    m = _SINGLE_TIME_RE.search(unicodedata.normalize("NFKC", str(time_slot or "")))
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h < 24 and mi < 60:
            start = h * 60 + mi
            return start, start + _DEFAULT_DURATION_MIN
    return None


def _sort_key(time_slot, original_idx):
    rng = _time_minutes(time_slot)
    if rng:
        return rng[0], original_idx
    text = str(time_slot or "")
    for kw, minute in _PERIOD_ORDER:
        if kw in text:
            return minute, original_idx
    return 720, original_idx


def _day_slots(day, poi_idx):
    """当天 slot 列表（景点在前、餐厅在后，再按时间稳定排序），附 _lat/_lng/_time。"""
    raw = [s for s in (day.get("pois") or []) if isinstance(s, dict)] + \
          [s for s in (day.get("foods") or []) if isinstance(s, dict)]
    ordered = sorted(enumerate(raw), key=lambda t: _sort_key(t[1].get("time_slot"), t[0]))
    out = []
    for _, s in ordered:
        if not str(s.get("name") or "").strip():
            continue
        lat, lng = _coords(s, poi_idx)
        out.append({"slot": s, "name": str(s["name"]).strip(), "lat": lat, "lng": lng,
                    "time": _time_minutes(s.get("time_slot"))})
    return out


def _day_number(day, fallback):
    try:
        return int(day.get("day"))
    except (TypeError, ValueError):
        return fallback


def _day_title(day, n):
    label = str(day.get("label") or "").strip()
    return f"Day {n} {label}".strip() if label else f"Day {n}"


def _price_text(slot):
    cost = slot.get("cost")
    if cost in (None, "", [], "?"):
        return ""
    return f"价格：{cost}{provenance.inline_note(slot.get('cost_meta'))}"


# ---------------------------------------------------------------------------
#  iCalendar
# ---------------------------------------------------------------------------

def _ics_escape(text):
    s = str(text if text is not None else "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def _fold(line, limit=75):
    """按 UTF-8 字节折行：每行（不含 CRLF）≤ limit octets，续行以单个空格开头。"""
    if len(line.encode("utf-8")) <= limit:
        return [line]
    out, cur, cur_len, max_len = [], "", 0, limit
    for ch in line:
        n = len(ch.encode("utf-8"))
        if cur_len + n > max_len:
            out.append(cur)
            cur, cur_len, max_len = " ", 1, limit
        cur += ch
        cur_len += n
    if cur:
        out.append(cur)
    return out


def _ics_uid(ident, date_iso, name, taken):
    base = hashlib.sha1(f"{ident}|{date_iso}|{name}".encode("utf-8")).hexdigest()
    uid, n = base, 1
    while uid in taken:  # 同日同名（极少见）加序号以保持唯一
        n += 1
        uid = hashlib.sha1(f"{base}#{n}".encode("utf-8")).hexdigest()
    taken.add(uid)
    return f"{uid}@{_UID_DOMAIN}"


def _vtimezone():
    return [
        "BEGIN:VTIMEZONE", f"TZID:{TZID}",
        "BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:+0800", "TZOFFSETTO:+0800",
        "TZNAME:CST", "END:STANDARD", "END:VTIMEZONE",
    ]


def to_ics(itinerary_ctx, now=None):
    """生成 RFC 5545 日历文本（CRLF 行尾）。有钟点的 slot 为定时事件(TZID=Asia/Shanghai)，其余为全天事件。"""
    ctx = itinerary_ctx
    start = _parse_start_date(ctx)
    ident = _itinerary_id(ctx)
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    poi_idx = _poi_index(ctx)
    city_default = str(_ctx_get(ctx, "city", "") or "")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{_PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{_ics_escape((city_default + ' 旅行行程').strip())}", f"X-WR-TIMEZONE:{TZID}"]
    lines += _vtimezone()

    taken = set()
    for di, day in enumerate(_ctx_get(ctx, "itinerary", []) or [], 1):
        if not isinstance(day, dict) or start is None:
            continue
        n = _day_number(day, di)
        date = start + datetime.timedelta(days=n - 1)
        for item in _day_slots(day, poi_idx):
            s, name = item["slot"], item["name"]
            city = str(s.get("city") or "").strip() or city_default
            ev = ["BEGIN:VEVENT", f"UID:{_ics_uid(ident, date.isoformat(), name, taken)}", f"DTSTAMP:{stamp}"]
            if item["time"]:
                t0, t1 = item["time"]
                base = datetime.datetime.combine(date, datetime.time())
                d0, d1 = base + datetime.timedelta(minutes=t0), base + datetime.timedelta(minutes=t1)
                ev.append(f"DTSTART;TZID={TZID}:{d0.strftime('%Y%m%dT%H%M%S')}")
                ev.append(f"DTEND;TZID={TZID}:{d1.strftime('%Y%m%dT%H%M%S')}")
            else:
                ev.append(f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}")
                ev.append(f"DTEND;VALUE=DATE:{(date + datetime.timedelta(days=1)).strftime('%Y%m%d')}")
            ev.append(f"SUMMARY:{_ics_escape(name)}")
            loc = f"{name} {city}".strip() if city and city not in name else name
            ev.append(f"LOCATION:{_ics_escape(loc)}")
            if item["lat"] is not None:
                ev.append(f"GEO:{item['lat']:.6f};{item['lng']:.6f}")
            desc = [f"{_day_title(day, n)}"]
            if s.get("time_slot"):
                desc.append(f"时间：{s['time_slot']}")
            if s.get("transit"):
                desc.append(f"交通：{s['transit']}")
            if s.get("note"):
                desc.append(f"备注：{s['note']}")
            price = _price_text(s)
            if price:
                desc.append(price)
            ev.append(f"DESCRIPTION:{_ics_escape(chr(10).join(desc))}")
            ev.append("END:VEVENT")
            lines += ev

    lines.append("END:VCALENDAR")
    folded = []
    for ln in lines:
        folded.extend(_fold(ln))
    return "\r\n".join(folded) + "\r\n"


# ---------------------------------------------------------------------------
#  GPX / KML
# ---------------------------------------------------------------------------

def _x(text):
    return _xml_escape(_XML_BAD_CHARS_RE.sub("", str(text if text is not None else "")))


def _collect_days(ctx):
    """[(day_no, title, [item...])...] 与无坐标点总数。"""
    poi_idx = _poi_index(ctx)
    days, skipped = [], 0
    for di, day in enumerate(_ctx_get(ctx, "itinerary", []) or [], 1):
        if not isinstance(day, dict):
            continue
        n = _day_number(day, di)
        items = _day_slots(day, poi_idx)
        skipped += sum(1 for it in items if it["lat"] is None)
        days.append((n, _day_title(day, n), items))
    return days, skipped


def _title(ctx):
    return f"{_ctx_get(ctx, 'city', '') or ''} 旅行行程".strip()


def to_gpx(itinerary_ctx):
    """GPX 1.1：每天一个 <rte>，<rtept lat lon><name>；无坐标点跳过（数量写入 metadata/desc）。"""
    days, skipped = _collect_days(itinerary_ctx)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="travel-itinerary-generator" xmlns="http://www.topografix.com/GPX/1/1">',
           "  <metadata>", f"    <name>{_x(_title(itinerary_ctx))}</name>"]
    if skipped:
        out.append(f"    <desc>{skipped} 个无坐标地点已跳过</desc>")
    out.append("  </metadata>")
    for _, title, items in days:
        pts = [it for it in items if it["lat"] is not None]
        if not pts:
            continue
        out.append("  <rte>")
        out.append(f"    <name>{_x(title)}</name>")
        for it in pts:
            out.append(f'    <rtept lat="{it["lat"]:.6f}" lon="{it["lng"]:.6f}">')
            out.append(f"      <name>{_x(it['name'])}</name>")
            if it["slot"].get("time_slot"):
                out.append(f"      <desc>{_x(it['slot']['time_slot'])}</desc>")
            out.append("    </rtept>")
        out.append("  </rte>")
    out.append("</gpx>")
    return "\n".join(out) + "\n"


def to_kml(itinerary_ctx):
    """KML 2.2：每天一个 Folder（Placemark Point + 当天按顺序的 LineString）；无坐标点跳过。"""
    days, skipped = _collect_days(itinerary_ctx)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2">', "<Document>",
           f"  <name>{_x(_title(itinerary_ctx))}</name>"]
    if skipped:
        out.append(f"  <description>{skipped} 个无坐标地点已跳过</description>")
    for _, title, items in days:
        pts = [it for it in items if it["lat"] is not None]
        out.append("  <Folder>")
        out.append(f"    <name>{_x(title)}</name>")
        for it in pts:
            desc = " | ".join(x for x in (str(it["slot"].get("time_slot") or ""),
                                          str(it["slot"].get("note") or "")) if x)
            out.append("    <Placemark>")
            out.append(f"      <name>{_x(it['name'])}</name>")
            if desc:
                out.append(f"      <description>{_x(desc)}</description>")
            out.append(f"      <Point><coordinates>{it['lng']:.6f},{it['lat']:.6f},0</coordinates></Point>")
            out.append("    </Placemark>")
        if len(pts) >= 2:
            coords = " ".join(f"{it['lng']:.6f},{it['lat']:.6f},0" for it in pts)
            out.append("    <Placemark>")
            out.append(f"      <name>{_x(title)} 路线</name>")
            out.append(f"      <LineString><tessellate>1</tessellate><coordinates>{coords}</coordinates></LineString>")
            out.append("    </Placemark>")
        out.append("  </Folder>")
    out += ["</Document>", "</kml>"]
    return "\n".join(out) + "\n"


# 供 deliver 使用：扩展名 → 生成函数
EXPORTERS = (("ics", to_ics), ("gpx", to_gpx), ("kml", to_kml))
EXPORT_EXTS = tuple(ext for ext, _ in EXPORTERS)
