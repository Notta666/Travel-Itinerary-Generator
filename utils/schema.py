# -*- coding: utf-8 -*-
"""
行程结构 schema + 防幻觉校验器 (TR-2)
=====================================
- pydantic v2 模型 `Itinerary / Day / Slot / POIRef`：字段名与类型以 planner Fusion 输出的
  现有 dict 为准（Slot 是扁平结构：type/name/city/time_slot/transit/note/cuisine/cost/rating），
  `extra="allow"` 保证未知字段不丢；最终仍以 dict 交给下游。
- `validate_itinerary(raw, candidates, distance_matrix=None) -> (itinerary_dict, issues)`：
    1. POI 必须属于输入候选集（id 精确 / 名称规范化相等 / 名称包含 + 坐标 ≤100m），否则剔除；
    2. 同一天时间段不重叠（仅记 issue）；
    3. 有距离矩阵时，相邻 slot 交通时长 ≤ 矩阵估计 × 1.5（仅记 issue，不删除）。

issue 文本以固定前缀开头，便于调用方分类：
    ISSUE_NON_CANDIDATE（已剔除）/ ISSUE_STRUCTURE（结构校验失败）/ ISSUE_OVERLAP / ISSUE_TRANSIT
"""
import json
import math
import re
import unicodedata
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from utils.log import get_logger

logger = get_logger("travel_pipeline")

ISSUE_NON_CANDIDATE = "非候选POI"
ISSUE_STRUCTURE = "结构校验失败"
ISSUE_OVERLAP = "时间重叠"
ISSUE_TRANSIT = "交通时长超限"

# 名称包含关系成立时，坐标距离需在此阈值（米）内
NAME_MATCH_MAX_DISTANCE_M = 100.0
# 交通时长容忍倍数
TRANSIT_TOLERANCE = 1.5
# 距离矩阵单元为纯数字（视为公里）时的估算速度：30 km/h → 2 分钟/公里
_MIN_PER_KM = 2.0


# ---------------------------------------------------------------------------
#  模型
# ---------------------------------------------------------------------------

class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_none(cls, data):
        """LLM 常返回 null：丢弃 None 让字段默认值生效（与 dict.get(k, default) 行为一致）。"""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class POIRef(_Model):
    """候选/引用的地点：id 可选；坐标 lat/lng 可选。"""
    id: Optional[str] = None
    name: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None


class Slot(_Model):
    """行程中的一个时段（景点或餐厅）。字段名与 planner Fusion 输出一致。"""
    type: str = "sight"
    name: str = ""
    city: str = ""
    time_slot: str = ""
    transit: str = ""
    note: str = ""
    cuisine: str = ""
    cost: Any = ""
    rating: Any = ""

    def poi_ref(self) -> POIRef:
        """按 slot 上可能存在的 id/坐标字段构造 POIRef（LLM 通常只给 name）。"""
        extra = self.model_extra or {}
        lat, lng = _coords_from_mapping(extra)
        return POIRef(id=_first_id(extra), name=self.name, lat=lat, lng=lng)


class Day(_Model):
    day: Optional[int] = None
    label: str = ""
    summary: str = ""
    accommodation_city: str = ""
    slots: List[Slot] = []


class Itinerary(_Model):
    days: List[Day] = []
    overall_note: str = ""
    food_highlights: List[Any] = []


# ---------------------------------------------------------------------------
#  名称 / 坐标工具
# ---------------------------------------------------------------------------

_BRACKET_RE = re.compile(r"[（(\[【].*?[）)\]】]")


def normalize_name(name) -> str:
    """名称规范化：全半角统一(NFKC)、去括号内容、去空格/标点、小写。"""
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", str(name))
    stripped = _BRACKET_RE.sub("", text)
    out = re.sub(r"[^\w一-龥]", "", stripped).lower()
    if out:
        return out
    # 名称仅由括号内容构成时，退回不剥括号的版本
    return re.sub(r"[^\w一-龥]", "", text).lower()


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    """两点球面距离（米）。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _to_float(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _coords_from_mapping(m) -> tuple:
    """从 dict 中提取 (lat, lng)；支持 lat/lng(lon)、location=[lng, lat] 或 "lng,lat" 字符串。"""
    if not isinstance(m, dict):
        return None, None
    lat = _to_float(m.get("lat"))
    lng = _to_float(m.get("lng") if m.get("lng") is not None else m.get("lon"))
    if lat is not None and lng is not None:
        return lat, lng
    loc = m.get("location")
    if isinstance(loc, str) and "," in loc:
        loc = loc.split(",", 1)
    if isinstance(loc, (list, tuple)) and len(loc) >= 2:
        lo, la = _to_float(loc[0]), _to_float(loc[1])
        if lo is not None and la is not None:
            return la, lo
    return None, None


def _first_id(m) -> Optional[str]:
    if not isinstance(m, dict):
        return None
    for key in ("id", "poi_id", "uid"):
        v = m.get(key)
        if v not in (None, ""):
            return str(v)
    return None


def _backfill(slot: Slot, cand: Optional[POIRef]) -> None:
    """把匹配到的候选 id/坐标回填到 slot 上缺失的字段（便于下游地图），不覆盖 slot 已有值。"""
    if cand is None:
        return
    extra = slot.model_extra or {}
    if cand.id and not _first_id(extra):
        setattr(slot, "id", cand.id)
    s_lat, s_lng = _coords_from_mapping(extra)
    if (s_lat is None or s_lng is None) and cand.lat is not None and cand.lng is not None:
        setattr(slot, "lat", cand.lat)
        setattr(slot, "lng", cand.lng)


def _to_candidate(c) -> Optional[POIRef]:
    if isinstance(c, POIRef):
        return c
    if isinstance(c, str):
        return POIRef(name=c)
    if isinstance(c, dict):
        lat, lng = _coords_from_mapping(c)
        return POIRef(id=_first_id(c), name=str(c.get("name") or ""), lat=lat, lng=lng)
    return None


class _CandidateIndex:
    def __init__(self, candidates):
        self.items: List[tuple] = []  # (POIRef, normalized_name)
        self.by_id = {}
        self.by_norm = {}
        for c in candidates or []:
            ref = _to_candidate(c)
            if ref is None:
                continue
            norm = normalize_name(ref.name)
            if not norm and not ref.id:
                continue
            self.items.append((ref, norm))
            if ref.id:
                self.by_id.setdefault(ref.id, ref)
            if norm:
                self.by_norm.setdefault(norm, ref)

    def match(self, slot: Slot) -> tuple:
        """返回 (状态, 候选)：状态为 "ok" / "none" / "ambiguous"；ambiguous 时候选为匹配到的候选列表。

        规则：id 精确 → 规范化名称相等 → 名称包含关系：
          - slot 有坐标：包含关系 + 与候选坐标距离 ≤100m；
          - slot 无坐标：包含关系（较短名规范化后长度 ≥2）且恰好命中一个候选才放行，命中多个 → ambiguous。
        """
        ref = slot.poi_ref()
        if ref.id:
            cand = self.by_id.get(ref.id)
            return ("ok", cand) if cand else ("none", None)
        norm = normalize_name(ref.name)
        if not norm:
            return "none", None
        if norm in self.by_norm:
            return "ok", self.by_norm[norm]
        contained = []
        for cand, cnorm in self.items:
            if not cnorm or min(len(norm), len(cnorm)) < 2:
                continue
            if norm in cnorm or cnorm in norm:
                contained.append(cand)
        if ref.lat is not None and ref.lng is not None:
            for cand in contained:
                if cand.lat is None or cand.lng is None:
                    continue
                if haversine_m(ref.lat, ref.lng, cand.lat, cand.lng) <= NAME_MATCH_MAX_DISTANCE_M:
                    return "ok", cand
            return "none", None
        if len(contained) == 1:
            return "ok", contained[0]
        if len(contained) > 1:
            return "ambiguous", contained
        return "none", None


# ---------------------------------------------------------------------------
#  时间 / 交通
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})\s*(?:[-~～–—至到]+)\s*(\d{1,2})\s*[:：]\s*(\d{2})")


def parse_time_range(text) -> Optional[tuple]:
    """'09:00-11:30' → (540, 690)（分钟）；无法解析/不是区间返回 None；跨零点则 end+1440。"""
    if not text:
        return None
    m = _RANGE_RE.search(unicodedata.normalize("NFKC", str(text)))
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
        return None
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if end < start:
        end += 1440
    if end == start:
        return None
    return start, end


def _fmt_range(rng) -> str:
    def f(x):
        x %= 1440
        return f"{x // 60:02d}:{x % 60:02d}"
    return f"{f(rng[0])}-{f(rng[1])}"


def parse_transit_minutes(text) -> Optional[float]:
    """'打车约1小时30分钟' → 90；无时长信息返回 None。"""
    if not text:
        return None
    t = unicodedata.normalize("NFKC", str(text))
    h = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|h\b)", t, re.I)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min)", t, re.I)
    if not h and not m:
        return None
    return (float(h.group(1)) * 60 if h else 0.0) + (float(m.group(1)) if m else 0.0)


def _matrix_estimate_minutes(distance_matrix, a_name, b_name) -> Optional[float]:
    """从距离矩阵估计 a→b 的时长（分钟）。单元为 {distance(m), duration(s)} 或数字(km)。"""
    if not isinstance(distance_matrix, dict):
        return None
    labels = distance_matrix.get("labels") or []
    matrix = distance_matrix.get("matrix") or []
    if not labels or not matrix:
        return None
    idx = {}
    for i, lb in enumerate(labels):
        idx.setdefault(normalize_name(lb), i)
    i, j = idx.get(normalize_name(a_name)), idx.get(normalize_name(b_name))
    if i is None or j is None or i == j:
        return None
    try:
        cell = matrix[i][j]
    except (IndexError, TypeError):
        return None
    if isinstance(cell, dict):
        dur = _to_float(cell.get("duration"))
        if dur is not None and dur > 0:
            return dur / 60.0
        dist = _to_float(cell.get("distance"))
        if dist is not None and dist > 0:
            return dist / 1000.0 * _MIN_PER_KM
        return None
    km = _to_float(cell)
    if km is not None and km > 0:
        return km * _MIN_PER_KM
    return None


# ---------------------------------------------------------------------------
#  对外 API
# ---------------------------------------------------------------------------

def parse_itinerary(raw) -> Itinerary:
    """dict → model_validate；JSON 字符串 → model_validate_json。失败抛 ValidationError/ValueError。"""
    if isinstance(raw, Itinerary):
        return raw
    if isinstance(raw, (str, bytes)):
        return Itinerary.model_validate_json(raw)
    return Itinerary.model_validate(raw)


def _summarize_validation_error(e: ValidationError, limit: int = 3) -> str:
    parts = []
    for err in e.errors()[:limit]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', '')}")
    more = e.error_count() - limit
    return "; ".join(parts) + (f" 等 {e.error_count()} 处" if more > 0 else "")


def validate_itinerary(raw, candidates, distance_matrix=None):
    """校验并清洗 LLM 行程。

    返回 (itinerary_dict, issues)：
      - 非候选 POI 的 slot 被剔除（issue 以 ISSUE_NON_CANDIDATE 开头）；
      - 结构不合法时原样返回 raw（dict）并给出 ISSUE_STRUCTURE issue；
      - 时间重叠、交通时长超限只记 issue，不删除。
    """
    issues: List[str] = []
    try:
        model = parse_itinerary(raw)
    except (ValidationError, ValueError) as e:
        msg = _summarize_validation_error(e) if isinstance(e, ValidationError) else str(e)[:200]
        issues.append(f"{ISSUE_STRUCTURE}: {msg}")
        fallback = raw if isinstance(raw, dict) else {"days": []}
        return fallback, issues

    index = _CandidateIndex(candidates)
    for d_pos, day in enumerate(model.days, 1):
        day_no = day.day if day.day is not None else d_pos
        kept: List[Slot] = []
        for slot in day.slots:
            # 仅校验景点/餐厅；无名称的 slot 交给 planner 既有逻辑跳过
            if slot.type not in ("sight", "food") or not slot.name.strip():
                kept.append(slot)
                continue
            status, cand = index.match(slot)
            if status == "ok":
                _backfill(slot, cand)
                kept.append(slot)
            elif status == "ambiguous":
                names = "、".join(c.name for c in cand[:5])
                issues.append(
                    f"{ISSUE_NON_CANDIDATE}: Day{day_no} 「{slot.name.strip()}」匹配到多个候选"
                    f"（ambiguous: {names}），已剔除")
            else:
                issues.append(f"{ISSUE_NON_CANDIDATE}: Day{day_no} 「{slot.name.strip()}」不在候选列表，已剔除")
        day.slots = kept

        # --- 时间重叠 ---
        timed = []
        for slot in kept:
            rng = parse_time_range(slot.time_slot) or parse_time_range((slot.model_extra or {}).get("time"))
            if rng:
                timed.append((rng, slot.name))
        timed.sort(key=lambda x: x[0])
        for (r1, n1), (r2, n2) in zip(timed, timed[1:]):
            if r2[0] < r1[1]:
                issues.append(f"{ISSUE_OVERLAP}: Day{day_no} 「{n1}」({_fmt_range(r1)}) 与「{n2}」({_fmt_range(r2)})")

        # --- 交通时长 vs 距离矩阵 ---
        if distance_matrix:
            named = [s for s in kept if s.name.strip()]
            for prev, cur in zip(named, named[1:]):
                transit = cur.transit or ""
                if "步行" in transit or "走路" in transit:
                    continue  # 矩阵为驾车耗时，步行不可比
                actual = parse_transit_minutes(transit)
                est = _matrix_estimate_minutes(distance_matrix, prev.name, cur.name)
                if actual is None or est is None:
                    continue
                if actual > est * TRANSIT_TOLERANCE:
                    issues.append(
                        f"{ISSUE_TRANSIT}: Day{day_no} 「{prev.name}→{cur.name}」"
                        f"{actual:.0f}分钟 > 矩阵估计 {est:.0f}分钟×{TRANSIT_TOLERANCE}"
                    )

    return model.model_dump(exclude_unset=True), issues


def count_removed(issues) -> int:
    """issues 中被剔除的非候选 POI 数量。"""
    return sum(1 for i in issues if str(i).startswith(ISSUE_NON_CANDIDATE))


def has_blocking_issues(issues) -> bool:
    """是否需要回灌 LLM 重试：存在非候选 POI 或结构校验失败。"""
    return any(str(i).startswith((ISSUE_NON_CANDIDATE, ISSUE_STRUCTURE)) for i in issues)


def dumps_issues(issues) -> str:
    return json.dumps(list(issues), ensure_ascii=False)
