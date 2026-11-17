# -*- coding: utf-8 -*-
"""
数据溯源与时效 (TR-3)
=====================
为手册里的时效性数据（价格 / 票价 / 营业时间 / 天气 / 交通时刻）附带来源与抓取时间，
过期时提示用户出行前核实。

约定：原有字段保持不变，另增并行字段 `<field>_meta = stamp(...)`：

    {"value": ..., "source": "amap|flyai|weather:<provider>|llm",
     "fetched_at": "2026-11-18T10:00:00+08:00", "ttl_hours": 24}

- `fetched_at` 必须是数据**真正取得的时间**（缓存命中时为缓存写入时间，不是当前时间）。
- `source == "llm"` 表示数值由大模型生成，手册一律标注「AI 估算，请核实」。
- `unwrap(x)` 兼容旧的裸值（非 stamp 结构原样返回）。
"""
import datetime as _dt
from typing import Any, Optional

# ---- 默认 TTL（小时） ----
TTL_PRICE_HOURS = 24            # 价格 / 票价
TTL_OPENING_HOURS = 24 * 30     # 营业时间（30 天）
TTL_WEATHER_HOURS = 6           # 天气
TTL_SCHEDULE_HOURS = 24         # 交通时刻

SOURCE_AMAP = "amap"
SOURCE_FLYAI = "flyai"
SOURCE_LLM = "llm"
SOURCE_WEATHER_PREFIX = "weather:"

META_KEYS = ("value", "source", "fetched_at", "ttl_hours")


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _coerce_dt(ts: Any) -> Optional[_dt.datetime]:
    """把 datetime / epoch 秒 / ISO8601 字符串规整成带时区的 datetime；无法识别返回 None。"""
    if ts is None or isinstance(ts, bool):
        return None
    dt = None
    if isinstance(ts, _dt.datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        try:
            dt = _dt.datetime.fromtimestamp(float(ts))
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(ts, str):
        try:
            dt = _dt.datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # 无时区的 naive 时间按本地时区解释
    return dt


def stamp(value: Any, source: str, fetched_at: Any = None, ttl_hours: Optional[float] = None) -> dict:
    """给一个值打上来源与抓取时间戳。

    fetched_at 缺省或无法识别时取当前时间；传入缓存写入时间则原样保留。
    """
    dt = _coerce_dt(fetched_at) or _now()
    return {
        "value": value,
        "source": str(source),
        "fetched_at": dt.isoformat(timespec="seconds"),
        "ttl_hours": ttl_hours,
    }


def is_stamped(x: Any) -> bool:
    return isinstance(x, dict) and all(k in x for k in META_KEYS)


def unwrap(x: Any) -> Any:
    """取出 stamp 里的 value；旧的裸值原样返回。"""
    if is_stamped(x):
        return x["value"]
    return x


def is_stale(stamped: Any, now: Optional[_dt.datetime] = None) -> bool:
    """是否已超过 TTL。

    非 stamp 结构、ttl_hours 缺省（None）、fetched_at 无法解析 → 视为未过期
    （旧数据没有时效信息，不凭空判定过期）。
    """
    if not is_stamped(stamped):
        return False
    ttl = stamped.get("ttl_hours")
    if ttl is None:
        return False
    fetched = _coerce_dt(stamped.get("fetched_at"))
    if fetched is None:
        return False
    cur = _coerce_dt(now) if now is not None else _now()
    if cur is None:
        cur = _now()
    return (cur - fetched) > _dt.timedelta(hours=float(ttl))


def is_llm(stamped: Any) -> bool:
    return is_stamped(stamped) and stamped.get("source") == SOURCE_LLM


def fmt_fetched(stamped: Any) -> str:
    """fetched_at → 'MM-DD HH:mm'（按 stamp 自带时区的墙上时间）；无法解析返回空串。"""
    if not is_stamped(stamped):
        return ""
    dt = _coerce_dt(stamped.get("fetched_at"))
    return dt.strftime("%m-%d %H:%M") if dt else ""


# 来源 → 展示名（未知来源原样展示，由渲染层转义）
SOURCE_LABELS = {
    SOURCE_AMAP: "高德地图",
    SOURCE_FLYAI: "飞猪 FlyAI",
    SOURCE_LLM: "AI 估算，请核实",
    SOURCE_WEATHER_PREFIX + "amap": "高德天气",
    SOURCE_WEATHER_PREFIX + "open-meteo": "Open-Meteo（往年同期参考）",
}


def source_label(source: Any) -> str:
    s = str(source or "")
    return SOURCE_LABELS.get(s, s or "未知来源")


def inline_note(stamped: Any) -> str:
    """Markdown/纯文本用的行内来源说明：「（来源，更新于 MM-DD HH:mm[，可能已变化，出行前请核实]）」。

    非 stamp 结构返回空串。
    """
    if not is_stamped(stamped):
        return ""
    parts = [source_label(stamped.get("source"))]
    ts = fmt_fetched(stamped)
    if ts:
        parts.append(f"更新于 {ts}")
    if is_stale(stamped):
        parts.append("可能已变化，出行前请核实")
    return "（" + "，".join(parts) + "）"
