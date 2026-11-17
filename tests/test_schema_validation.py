# -*- coding: utf-8 -*-
"""
TR-2 防幻觉校验测试（全部离线，LLM 以 mock 替代）
=================================================
- 含虚构 POI 的 LLM 返回 → 重试 1 次 → 仍含则剔除，validation.removed 正确
- 重试后合格 → removed == 0
- 名称模糊匹配 + 100m 坐标规则
- 时间重叠 / 距离超限仅记 issue
- 手册渲染：validation 提示出现，POI 名称中的 <script> 被转义
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AMAP_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from pipeline.steps import planner  # noqa: E402
from utils.schema import (  # noqa: E402
    Itinerary, ISSUE_NON_CANDIDATE, ISSUE_OVERLAP, ISSUE_STRUCTURE, ISSUE_TRANSIT,
    count_removed, haversine_m, normalize_name, parse_time_range, parse_transit_minutes,
    validate_itinerary,
)

CANDIDATES = [
    {"name": "外滩", "location": [121.4900, 31.2400]},
    {"name": "豫园（上海老城厢）", "location": [121.4920, 31.2270]},
    {"name": "南翔小笼馆", "location": [121.4925, 31.2272]},
]


def _plan(slots_by_day, **extra):
    d = {"days": [{"day": i, "label": f"D{i}", "summary": "", "accommodation_city": "",
                   "slots": slots} for i, slots in enumerate(slots_by_day, 1)],
         "overall_note": "", "food_highlights": []}
    d.update(extra)
    return d


def _slot(name, typ="sight", time_slot="", **kw):
    s = {"type": typ, "name": name, "city": "上海", "time_slot": time_slot, "transit": "", "note": ""}
    s.update(kw)
    return s


class TestPlannerRetry(unittest.TestCase):
    def _fusion_json(self, names):
        return json.dumps(_plan([[_slot(n) for n in names]]), ensure_ascii=False)

    def test_fabricated_poi_persists_after_retry_is_removed(self):
        llm = MagicMock(side_effect=[
            self._fusion_json(["外滩", "不存在的虚构塔"]),
            self._fusion_json(["外滩", "不存在的虚构塔"]),
        ])
        result, validation = planner._plan_with_validation(llm, "sys", "PROMPT", CANDIDATES)
        self.assertEqual(llm.call_count, 2)
        names = [s["name"] for s in result["days"][0]["slots"]]
        self.assertEqual(names, ["外滩"])
        self.assertEqual(validation["removed"], 1)
        self.assertTrue(any("不存在的虚构塔" in i for i in validation["issues"]))
        # 重试提示在原提示后追加，且带上了不在候选列表的地点
        retry_prompt = llm.call_args_list[1][0][1]
        self.assertTrue(retry_prompt.startswith("PROMPT"))
        self.assertIn("以下地点不在候选列表中，请只使用候选列表中的地点", retry_prompt)
        self.assertIn("不存在的虚构塔", retry_prompt)

    def test_retry_succeeds_removed_zero(self):
        llm = MagicMock(side_effect=[
            self._fusion_json(["外滩", "不存在的虚构塔"]),
            self._fusion_json(["外滩", "豫园"]),
        ])
        result, validation = planner._plan_with_validation(llm, "sys", "PROMPT", CANDIDATES)
        self.assertEqual(llm.call_count, 2)
        self.assertEqual([s["name"] for s in result["days"][0]["slots"]], ["外滩", "豫园"])
        self.assertEqual(validation["removed"], 0)
        self.assertTrue(validation["retried"])

    def test_clean_first_response_no_retry(self):
        llm = MagicMock(return_value=self._fusion_json(["外滩"]))
        _, validation = planner._plan_with_validation(llm, "sys", "PROMPT", CANDIDATES)
        self.assertEqual(llm.call_count, 1)
        self.assertEqual(validation["removed"], 0)
        self.assertFalse(validation["retried"])

    def test_retry_exception_keeps_cleaned_first_result(self):
        llm = MagicMock(side_effect=[self._fusion_json(["外滩", "虚构塔"]), RuntimeError("boom")])
        result, validation = planner._plan_with_validation(llm, "sys", "PROMPT", CANDIDATES)
        self.assertEqual([s["name"] for s in result["days"][0]["slots"]], ["外滩"])
        self.assertEqual(validation["removed"], 1)

    def test_step6_end_to_end_sets_validation_in_context(self):
        class FakeAmap:
            def geocode(self, *a, **k):
                return None
        fused = self._fusion_json(["外滩", "虚构塔"])
        context = {
            "city": "上海", "days": 1,
            "poi_enriched": [{"name": "外滩", "location": [121.49, 31.24], "address": "", "district": "",
                              "nearby_food": []}],
            "distance_matrix": {"matrix": [], "labels": []},
            "food_recommendations": [], "flyai_prices": {},
        }
        with patch("utils.llm.call_deepseek", return_value=fused) as m:
            ctx = planner.step_6_plan_itinerary(context, amap=FakeAmap())
        # bull + bear + bear 空结果重试 + fusion + 校验重试 = 5 次；最后一次带校验反馈
        self.assertEqual(m.call_count, 5)
        self.assertIn("以下地点不在候选列表中", m.call_args_list[-1][0][1])
        self.assertEqual(ctx["validation"]["removed"], 1)
        names = [p["name"] for d in ctx["itinerary"] for p in d["pois"]]
        self.assertEqual(names, ["外滩"])


class TestPlannerDistanceMatrixPrompt(unittest.TestCase):
    def test_matrix_cell_km(self):
        self.assertEqual(planner._matrix_cell_km({"distance": 2345, "duration": 600}), 2.3)
        self.assertEqual(planner._matrix_cell_km({"distance": None, "duration": None}), 0)
        self.assertEqual(planner._matrix_cell_km(None), 0)
        self.assertEqual(planner._matrix_cell_km(3.26), 3.3)

    def test_prompt_matrix_has_nonzero_values(self):
        class FakeAmap:
            def geocode(self, *a, **k):
                return None

        def cell(d, t):
            return {"distance": d, "duration": t}

        context = {
            "city": "上海", "days": 1,
            "poi_enriched": [
                {"name": "外滩", "location": [121.49, 31.24], "address": "", "district": "", "nearby_food": []},
                {"name": "豫园", "location": [121.492, 31.227], "address": "", "district": "", "nearby_food": []},
            ],
            "distance_matrix": {"labels": ["外滩", "豫园"],
                                "matrix": [[cell(0, 0), cell(4200, 900)], [cell(4200, 900), cell(0, 0)]]},
            "food_recommendations": [], "flyai_prices": {},
        }
        fused = json.dumps(_plan([[_slot("外滩")]]), ensure_ascii=False)
        with patch("utils.llm.call_deepseek", return_value=fused) as m:
            planner.step_6_plan_itinerary(context, amap=FakeAmap())
        prompt = m.call_args_list[0][0][1]
        self.assertIn('"distance_matrix_km": [[0.0, 4.2], [4.2, 0.0]]', prompt)


class TestCandidateMatching(unittest.TestCase):
    def _kept(self, slot_dicts, candidates=CANDIDATES):
        out, issues = validate_itinerary(_plan([slot_dicts]), candidates)
        return [s["name"] for s in out["days"][0]["slots"]], issues

    def test_normalize_fullwidth_brackets_and_spaces(self):
        self.assertEqual(normalize_name("豫园（上海老城厢）"), normalize_name("豫园 (上海老城厢)"))
        self.assertEqual(normalize_name("豫 园"), normalize_name("豫园(别名)"))
        self.assertEqual(normalize_name("ＡＢＣ　Cafe"), "abccafe")

    def test_exact_and_fuzzy_name_match(self):
        kept, issues = self._kept([_slot("豫园 (老城厢)"), _slot("外 滩"), _slot("豫园（上海老城厢）")])
        self.assertEqual(len(kept), 3, issues)
        self.assertEqual(count_removed(issues), 0)

    def test_unknown_name_removed(self):
        kept, issues = self._kept([_slot("外滩"), _slot("魔法城堡")])
        self.assertEqual(kept, ["外滩"])
        self.assertEqual(count_removed(issues), 1)
        self.assertTrue(issues[0].startswith(ISSUE_NON_CANDIDATE))

    def test_containment_plus_within_100m_passes(self):
        # "外滩风景区" 包含 "外滩"，坐标相距约 ~10m
        slot = _slot("外滩风景区", lng=121.4901, lat=31.2400)
        kept, issues = self._kept([slot])
        self.assertEqual(kept, ["外滩风景区"], issues)

    def test_containment_but_beyond_100m_fails(self):
        # 约 0.002 度经度 ≈ 190m
        slot = _slot("外滩风景区", lng=121.4920, lat=31.2400)
        self.assertGreater(haversine_m(31.24, 121.49, 31.24, 121.492), 100)
        kept, issues = self._kept([slot])
        self.assertEqual(kept, [])
        self.assertEqual(count_removed(issues), 1)

    def test_containment_without_coords_unique_candidate_passes_and_backfills(self):
        cands = [{"id": "B001", "name": "外滩", "location": [121.49, 31.24]},
                 {"name": "豫园", "location": [121.492, 31.227]}]
        out, issues = validate_itinerary(_plan([[_slot("外滩风景区")]]), cands)
        self.assertEqual(issues, [])
        slot = out["days"][0]["slots"][0]
        self.assertEqual(slot["name"], "外滩风景区")
        self.assertEqual(slot["id"], "B001")
        self.assertAlmostEqual(slot["lng"], 121.49)
        self.assertAlmostEqual(slot["lat"], 31.24)

    def test_reverse_containment_without_coords_passes(self):
        # slot 名比候选名短：候选"外滩风景区" 包含 slot "外滩"
        cands = [{"name": "外滩风景区", "location": [121.49, 31.24]}]
        kept, issues = self._kept([_slot("外滩")], cands)
        self.assertEqual(kept, ["外滩"], issues)

    def test_ambiguous_containment_removed_with_issue(self):
        cands = [{"name": "西湖断桥", "location": [120.15, 30.26]},
                 {"name": "西湖苏堤", "location": [120.14, 30.24]}]
        out, issues = validate_itinerary(_plan([[_slot("西湖")]]), cands)
        self.assertEqual(out["days"][0]["slots"], [])
        self.assertEqual(count_removed(issues), 1)
        self.assertIn("ambiguous", issues[0])

    def test_short_name_below_two_chars_not_matched(self):
        cands = [{"name": "外滩", "location": [121.49, 31.24]}]
        kept, _ = self._kept([_slot("滩")], cands)
        self.assertEqual(kept, [])

    def test_exact_match_wins_over_ambiguity(self):
        cands = [{"name": "西湖"}, {"name": "西湖断桥"}, {"name": "西湖苏堤"}]
        kept, issues = self._kept([_slot("西湖")], cands)
        self.assertEqual(kept, ["西湖"], issues)

    def test_backfill_does_not_override_existing_fields(self):
        cands = [{"id": "B001", "name": "外滩", "location": [121.49, 31.24]}]
        out, _ = validate_itinerary(_plan([[_slot("外滩风景区", id="B001", lng=121.4901, lat=31.2400)]]), cands)
        slot = out["days"][0]["slots"][0]
        self.assertEqual(slot["lng"], 121.4901)

    def test_location_list_form_of_slot_coords(self):
        slot = _slot("外滩风景区", location=[121.4901, 31.2400])
        kept, _ = self._kept([slot])
        self.assertEqual(kept, ["外滩风景区"])

    def test_id_exact_match(self):
        cands = [{"id": "B001", "name": "外滩", "location": [121.49, 31.24]}]
        ok = _slot("任意名字", id="B001")
        bad = _slot("外滩", id="B999")  # id 不在候选集 → 剔除（即使名称相同）
        kept, issues = self._kept([ok, bad], cands)
        self.assertEqual(kept, ["任意名字"])
        self.assertEqual(count_removed(issues), 1)

    def test_extra_fields_preserved(self):
        out, _ = validate_itinerary(_plan([[_slot("外滩", mood="happy", cost=88)]], custom="x"), CANDIDATES)
        self.assertEqual(out["custom"], "x")
        self.assertEqual(out["days"][0]["slots"][0]["mood"], "happy")
        self.assertEqual(out["days"][0]["slots"][0]["cost"], 88)

    def test_non_sight_food_slot_types_pass_through(self):
        kept, issues = self._kept([_slot("机场大巴", typ="transport")])
        self.assertEqual(kept, ["机场大巴"])
        self.assertEqual(issues, [])

    def test_null_fields_tolerated(self):
        raw = {"days": [{"day": 1, "label": None, "slots": [{"type": "sight", "name": "外滩", "note": None}]}]}
        out, issues = validate_itinerary(raw, CANDIDATES)
        self.assertEqual(issues, [])
        self.assertEqual(out["days"][0]["slots"][0]["name"], "外滩")

    def test_structure_failure_returns_raw_with_issue(self):
        raw = {"days": "not-a-list"}
        out, issues = validate_itinerary(raw, CANDIDATES)
        self.assertEqual(out, raw)
        self.assertTrue(issues[0].startswith(ISSUE_STRUCTURE))

    def test_model_validate_json(self):
        it = Itinerary.model_validate_json(json.dumps(_plan([[_slot("外滩")]]), ensure_ascii=False))
        self.assertEqual(it.days[0].slots[0].name, "外滩")


class TestTimeAndTransit(unittest.TestCase):
    def test_parse_helpers(self):
        self.assertEqual(parse_time_range("09:00-11:30"), (540, 690))
        self.assertEqual(parse_time_range("９：００～１０：００"), (540, 600))
        self.assertIsNone(parse_time_range("上午"))
        self.assertEqual(parse_transit_minutes("打车约1小时30分钟"), 90)
        self.assertEqual(parse_transit_minutes("地铁15分钟"), 15)
        self.assertIsNone(parse_transit_minutes("出发"))

    def test_overlap_detected_but_not_removed(self):
        slots = [_slot("外滩", time_slot="09:00-11:00"),
                 _slot("豫园", time_slot="10:30-12:00"),
                 _slot("南翔小笼馆", typ="food", time_slot="12:00-13:00")]
        out, issues = validate_itinerary(_plan([slots]), CANDIDATES)
        overlaps = [i for i in issues if i.startswith(ISSUE_OVERLAP)]
        self.assertEqual(len(overlaps), 1)
        self.assertIn("外滩", overlaps[0])
        self.assertIn("豫园", overlaps[0])
        self.assertEqual(len(out["days"][0]["slots"]), 3)  # 不删除

    def test_adjacent_slots_not_overlap(self):
        slots = [_slot("外滩", time_slot="09:00-11:00"), _slot("豫园", time_slot="11:00-12:00")]
        _, issues = validate_itinerary(_plan([slots]), CANDIDATES)
        self.assertEqual(issues, [])

    def test_overlap_only_within_same_day(self):
        d1 = [_slot("外滩", time_slot="09:00-11:00")]
        d2 = [_slot("豫园", time_slot="09:30-10:30")]
        _, issues = validate_itinerary(_plan([d1, d2]), CANDIDATES)
        self.assertEqual(issues, [])

    def _matrix(self, seconds):
        return {"labels": ["外滩", "豫园（上海老城厢）"],
                "matrix": [[{"distance": 0, "duration": 0}, {"distance": 2000, "duration": seconds}],
                           [{"distance": 2000, "duration": seconds}, {"distance": 0, "duration": 0}]]}

    def test_transit_over_limit_only_records_issue(self):
        slots = [_slot("外滩", time_slot="09:00-10:00"),
                 _slot("豫园", time_slot="11:00-12:00", transit="打车40分钟")]
        out, issues = validate_itinerary(_plan([slots]), CANDIDATES, self._matrix(600))  # 估计 10 分钟
        transit = [i for i in issues if i.startswith(ISSUE_TRANSIT)]
        self.assertEqual(len(transit), 1)
        self.assertEqual(len(out["days"][0]["slots"]), 2)
        self.assertEqual(count_removed(issues), 0)

    def test_transit_within_tolerance_ok(self):
        slots = [_slot("外滩", time_slot="09:00-10:00"),
                 _slot("豫园", time_slot="11:00-12:00", transit="打车14分钟")]  # ≤ 10×1.5
        _, issues = validate_itinerary(_plan([slots]), CANDIDATES, self._matrix(600))
        self.assertEqual(issues, [])

    def test_walking_and_missing_matrix_skipped(self):
        slots = [_slot("外滩"), _slot("豫园", transit="步行60分钟")]
        _, issues = validate_itinerary(_plan([slots]), CANDIDATES, self._matrix(600))
        self.assertEqual(issues, [])
        slots2 = [_slot("外滩"), _slot("豫园", transit="打车60分钟")]
        _, issues2 = validate_itinerary(_plan([slots2]), CANDIDATES, None)
        self.assertEqual(issues2, [])


class TestBrochureValidationNotice(unittest.TestCase):
    def _render(self, validation, poi_name="外滩"):
        from utils.brochure import generate_brochure
        itinerary = [{
            "day": 1, "accommodation_city": "上海", "label": "D1",
            "pois": [{"name": poi_name, "location": [121.49, 31.24], "address": "中山东一路",
                      "time_slot": "09:00-11:00", "geo_status": "resolved"}],
            "foods": [],
        }]
        with patch("utils.brochure._fetch_photos_batch", return_value={}), \
             patch("utils.brochure._search_hotels", return_value=[]):
            return generate_brochure(itinerary, "上海", tips={}, validation=validation)

    def test_notice_shown_when_removed(self):
        html = self._render({"removed": 2, "issues": ["x"]})
        self.assertIn("已移除 2 项未经验证的地点", html)

    def test_no_notice_when_zero_or_missing(self):
        self.assertNotIn("未经验证的地点", self._render({"removed": 0, "issues": []}))
        self.assertNotIn("未经验证的地点", self._render(None))
        self.assertNotIn("未经验证的地点", self._render({"removed": "bad"}))

    def test_script_in_poi_name_escaped(self):
        payload = "<script>alert('x')</script>"
        html = self._render({"removed": 1, "issues": []}, poi_name=payload)
        self.assertIn("已移除 1 项未经验证的地点", html)
        self.assertNotIn(payload, html)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", html.replace("&#39;", "&#x27;"))


if __name__ == "__main__":
    unittest.main()
