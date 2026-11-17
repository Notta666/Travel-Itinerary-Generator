# -*- coding: utf-8 -*-
"""
TR-3 数据溯源与时效测试
======================
- utils.provenance：stamp / is_stale / unwrap / inline_note
- flyai 缓存命中时 fetched_at = 缓存写入时间（而不是当前时间）
- LLM 估算价格标注、未验证 POI 标注与降权（高德检索 mock）
- 手册渲染：来源 · 更新于、过期提示、AI 估算、数据说明，恶意来源字符串转义
全程离线：高德/飞猪均 mock，不访问真实外部 API。
"""
import datetime as dt
import json
import os
import re
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AMAP_KEY", "test-key")

from utils import provenance as pv  # noqa: E402


def _ago(hours):
    return (dt.datetime.now().astimezone() - dt.timedelta(hours=hours)).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
#  stamp / is_stale / unwrap
# ---------------------------------------------------------------------------

class TestStampBasics:
    def test_stamp_structure_and_tz(self):
        m = pv.stamp(60, "amap", ttl_hours=24)
        assert set(m) == {"value", "source", "fetched_at", "ttl_hours"}
        assert m["value"] == 60 and m["source"] == "amap" and m["ttl_hours"] == 24
        parsed = dt.datetime.fromisoformat(m["fetched_at"])
        assert parsed.tzinfo is not None, "fetched_at 必须带时区"
        assert abs((dt.datetime.now().astimezone() - parsed).total_seconds()) < 5

    def test_stamp_keeps_given_fetched_at(self):
        t = time.time() - 7200
        m = pv.stamp(1, "flyai", fetched_at=t, ttl_hours=24)
        assert abs(dt.datetime.fromisoformat(m["fetched_at"]).timestamp() - t) < 1
        m2 = pv.stamp(1, "flyai", fetched_at="2026-01-02T03:04:05+08:00")
        assert m2["fetched_at"] == "2026-01-02T03:04:05+08:00"

    def test_stamp_bad_fetched_at_falls_back_to_now(self):
        m = pv.stamp(1, "flyai", fetched_at=MagicMock())
        assert abs((dt.datetime.now().astimezone() - dt.datetime.fromisoformat(m["fetched_at"])).total_seconds()) < 5

    def test_default_ttl_constants(self):
        assert pv.TTL_PRICE_HOURS == 24
        assert pv.TTL_OPENING_HOURS == 720
        assert pv.TTL_WEATHER_HOURS == 6
        assert pv.TTL_SCHEDULE_HOURS == 24

    def test_is_stale(self):
        fresh = pv.stamp(1, "amap", fetched_at=_ago(1), ttl_hours=24)
        old = pv.stamp(1, "amap", fetched_at=_ago(25), ttl_hours=24)
        assert pv.is_stale(fresh) is False
        assert pv.is_stale(old) is True
        # 显式 now
        now = dt.datetime.now().astimezone() + dt.timedelta(hours=30)
        assert pv.is_stale(fresh, now=now) is True
        # 营业时间 30 天
        assert pv.is_stale(pv.stamp("9-17", "amap", fetched_at=_ago(24 * 29), ttl_hours=pv.TTL_OPENING_HOURS)) is False
        assert pv.is_stale(pv.stamp("9-17", "amap", fetched_at=_ago(24 * 31), ttl_hours=pv.TTL_OPENING_HOURS)) is True

    def test_is_stale_non_stamp_or_no_ttl_is_not_stale(self):
        assert pv.is_stale(None) is False
        assert pv.is_stale(123) is False
        assert pv.is_stale({"price": 1}) is False
        assert pv.is_stale(pv.stamp(1, "amap", fetched_at=_ago(9999), ttl_hours=None)) is False

    def test_unwrap_compatible_with_bare_values(self):
        assert pv.unwrap(pv.stamp(42, "amap")) == 42
        assert pv.unwrap(42) == 42
        assert pv.unwrap("abc") == "abc"
        assert pv.unwrap(None) is None
        assert pv.unwrap({"value": 1}) == {"value": 1}  # 缺少其它键 → 不是 stamp，原样返回

    def test_inline_note(self):
        fresh = pv.stamp(1, "amap", fetched_at="2026-11-18T10:00:00+08:00", ttl_hours=None)
        assert pv.inline_note(fresh) == "（高德地图，更新于 11-18 10:00）"
        llm = pv.stamp("80", "llm", fetched_at=_ago(1), ttl_hours=24)
        assert "AI 估算，请核实" in pv.inline_note(llm)
        old = pv.stamp(1, "flyai", fetched_at=_ago(48), ttl_hours=24)
        assert "可能已变化，出行前请核实" in pv.inline_note(old)
        assert pv.inline_note("raw") == ""


# ---------------------------------------------------------------------------
#  缓存命中：fetched_at 是缓存写入时间
# ---------------------------------------------------------------------------

class TestFlyaiCacheFetchedAt:
    def _client(self, tmp_path):
        from utils.flyai_api import FlyAIApiClient
        return FlyAIApiClient(cache_dir=str(tmp_path))

    def test_cache_hit_records_cache_written_time(self, tmp_path):
        client = self._client(tmp_path)
        params = {"origin": "上海", "destination": "杭州", "date": "2026-12-01"}
        cache_path = client._get_cache_path("train", params)
        written_at = time.time() - 3 * 3600  # 3 小时前写入，train TTL=24h 仍有效
        items = [{"price": 73.0, "segments": [], "jump_url": ""}]
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"cached_at": written_at, "cmd_type": "train", "result": items}, f)

        with patch.object(client, "_run_cli", side_effect=AssertionError("缓存命中不应调用 CLI")):
            got, source = client.query_train("上海", "杭州", "2026-12-01")
        assert source == "cache" and got == items
        assert client.fetch_times["train"] == pytest.approx(written_at)

    def test_live_query_records_now(self, tmp_path):
        client = self._client(tmp_path)
        raw = {"data": {"itemList": [{"ticketPrice": "99", "journeys": [], "jumpUrl": ""}]}}
        before = time.time()
        with patch.object(client, "_run_cli", return_value=raw):
            _, source = client.query_flight("上海", "北京", "2026-12-01")
        assert source == "live"
        assert before <= client.fetch_times["flight"] <= time.time()

    def test_step55_price_meta_uses_cache_time_not_now(self, tmp_path):
        from pipeline.steps.pricing_and_transport import step_55_flyai_pricing
        client = self._client(tmp_path)
        written_at = time.time() - 5 * 3600
        params = {"origin": "上海", "destination": "杭州", "date": "2026-12-01"}
        with open(client._get_cache_path("train", params), "w", encoding="utf-8") as f:
            json.dump({"cached_at": written_at, "cmd_type": "train",
                       "result": [{"price": 73.0, "segments": [], "jump_url": ""}]}, f)
        context = {
            "city": "杭州", "start_date": "2026-12-01", "days": 2,
            "preferences": {"start_city": "上海", "transport": "高铁", "people_count": 2,
                            "hotel_budget_min": 300, "hotel_budget_max": 500},
        }
        with patch.object(client, "_run_cli", return_value=None), \
                patch("time.sleep", lambda *a, **k: None):
            ctx = step_55_flyai_pricing(context, client=client)
        train = ctx["flyai_prices"]["train"]
        assert train["cheapest"] == 73.0, "原有字段保持不变"
        meta = train["price_meta"]
        assert meta["source"] == "flyai" and meta["ttl_hours"] == pv.TTL_PRICE_HOURS
        fetched = dt.datetime.fromisoformat(meta["fetched_at"]).timestamp()
        assert fetched == pytest.approx(written_at, abs=1.5), "缓存命中时 fetched_at 必须是缓存写入时间"
        assert time.time() - fetched > 4.9 * 3600
        assert train["schedule_meta"]["ttl_hours"] == pv.TTL_SCHEDULE_HOURS
        # 酒店查询失败（_run_cli 返回 None）→ 没有 items，不应伪造 meta
        assert "price_meta" not in ctx["flyai_prices"]["hotel"]

    def test_ticket_meta_regex_uses_poi_cache_time(self, tmp_path):
        """regex 路径：fetched_at 取 POI 缓存文件里的 cached_at。"""
        from utils import flyai_api
        written_at = time.time() - 10 * 3600
        cache_dir = tmp_path / "data" / "cache" / "flyai"
        cache_dir.mkdir(parents=True)
        with open(cache_dir / "poi_abc.json", "w", encoding="utf-8") as f:
            json.dump({"cached_at": written_at, "cmd_type": "poi",
                       "result": [{"name": "西湖", "description": "门票 60元/人"}]}, f, ensure_ascii=False)
        with patch.object(flyai_api, "BASE_DIR", str(tmp_path)):
            client = flyai_api.FlyAIApiClient(cache_dir=str(cache_dir))
            res = client.query_poi_ticket("西湖", "杭州")
        assert res["source"] == "regex" and res["price_min"] == 60
        assert res["fetched_at"] == pytest.approx(written_at)

    def test_step7_stamps_tickets(self):
        from pipeline.steps.query_tickets import step_7_query_tickets
        written_at = time.time() - 2 * 3600
        fake_client = MagicMock()
        fake_client.query_poi_ticket.side_effect = lambda n, c: (
            {"price_min": 60, "price_max": 60, "source": "regex", "fetched_at": written_at} if n == "西湖"
            else {"price_min": None, "price_max": None, "source": "fail"})
        day_pois = [{"name": "西湖", "location": None}, {"name": "无名景点", "location": None}]
        context = {"city": "杭州", "flyai_prices": {"available": True},
                   "itinerary": [{"day": 1, "pois": day_pois}]}
        with patch("utils.flyai_api.FlyAIApiClient", return_value=fake_client):
            ctx = step_7_query_tickets(context)
        t = ctx["flyai_prices"]["tickets"]
        assert t["西湖"]["price_min"] == 60 and t["西湖"]["source"] == "regex"
        m = t["西湖"]["price_meta"]
        assert m["source"] == "flyai" and m["value"] == {"min": 60, "max": 60}
        assert dt.datetime.fromisoformat(m["fetched_at"]).timestamp() == pytest.approx(written_at, abs=1.5)
        assert "price_meta" not in t["无名景点"]


# ---------------------------------------------------------------------------
#  LLM 估算标注（planner._cost_meta）
# ---------------------------------------------------------------------------

class TestCostSource:
    def test_llm_cost_marked_llm(self):
        from pipeline.steps.planner import _cost_meta
        m = _cost_meta("某小吃店", "人均60", [])
        assert m["source"] == "llm" and m["value"] == "人均60" and m["ttl_hours"] == pv.TTL_PRICE_HOURS

    def test_passthrough_from_amap_candidate_marked_amap(self):
        from pipeline.steps.planner import _cost_meta
        cands = [{"name": "某小吃店", "cost": "58"}]
        assert _cost_meta("某小吃店", "58", cands)["source"] == "amap"
        # 数值被 LLM 改过 → 视为 LLM 估算
        assert _cost_meta("某小吃店", "80", cands)["source"] == "llm"

    def test_non_price_text_not_stamped(self):
        from pipeline.steps.planner import _cost_meta
        assert _cost_meta("x", "不限", []) is None
        assert _cost_meta("x", "", []) is None


# ---------------------------------------------------------------------------
#  POI 存在性二次校验（enrich）
# ---------------------------------------------------------------------------

def _enrich_context(names):
    return {
        "city": "杭州",
        "poi_geocoded": [{"name": n, "location": (120.1 + i * 0.01, 30.2), "geo_status": "resolved"}
                         for i, n in enumerate(names)],
        "xhs_pois": {"sights": []}, "xhs_food_data": [], "preferences": {},
    }


class TestPoiVerification:
    def _amap(self, table):
        """table: name -> list（成功）/ None（请求失败）"""
        m = MagicMock()
        m.reverse_geocode.return_value = {}
        m.place_text_checked.side_effect = lambda keywords, **kw: table[keywords]
        return m

    def test_unverified_poi_demoted_and_flagged(self):
        from pipeline.steps import enrich
        table = {
            "幻觉景点甲": [],  # 高德成功响应但查无
            "西湖": [{"id": "B0001", "name": "西湖风景名胜区", "business": {"opentime_today": "全天开放"}}],
            "灵隐寺": [{"id": "B0002", "name": "灵隐寺", "business": {}}],
        }
        ctx = _enrich_context(["幻觉景点甲", "西湖", "灵隐寺"])  # 幻觉景点排在最前
        with patch.object(enrich, "amap", self._amap(table)):
            out = enrich.step_4_enrich(ctx)
        names = [p["name"] for p in out["poi_enriched"]]
        assert names == ["西湖", "灵隐寺", "幻觉景点甲"], "verified=False 应排到最后（降权），其余保持相对顺序"
        by = {p["name"]: p for p in out["poi_enriched"]}
        assert by["幻觉景点甲"]["verified"] is False
        assert by["西湖"]["verified"] is True and by["西湖"]["amap_id"] == "B0001"
        assert by["西湖"]["opening_hours"] == "全天开放"
        om = by["西湖"]["opening_hours_meta"]
        assert om["source"] == "amap" and om["ttl_hours"] == pv.TTL_OPENING_HOURS
        assert "opening_hours" not in by["灵隐寺"]

    def test_network_failure_is_unknown_not_demoted(self):
        from pipeline.steps import enrich
        table = {"西湖": None, "灵隐寺": [{"id": "B2", "name": "灵隐寺", "business": {}}]}
        ctx = _enrich_context(["西湖", "灵隐寺"])
        with patch.object(enrich, "amap", self._amap(table)):
            out = enrich.step_4_enrich(ctx)
        by = {p["name"]: p for p in out["poi_enriched"]}
        assert by["西湖"]["verified"] is None, "查询失败 → 未知（None），不是 False"
        assert [p["name"] for p in out["poi_enriched"]] == ["西湖", "灵隐寺"], "未知不降权"

    def test_poi_with_amap_id_skips_lookup(self):
        from pipeline.steps import enrich
        m = self._amap({})
        ctx = _enrich_context(["西湖"])
        ctx["poi_geocoded"][0]["amap_id"] = "B000A"
        with patch.object(enrich, "amap", m):
            out = enrich.step_4_enrich(ctx)
        assert out["poi_enriched"][0]["verified"] is True
        assert out["poi_enriched"][0]["amap_id"] == "B000A"
        m.place_text_checked.assert_not_called()

    def test_name_matching_rules(self):
        from pipeline.steps.enrich import _poi_name_matches
        assert _poi_name_matches("西湖", "西湖风景名胜区")
        assert _poi_name_matches("东方明珠广播电视塔", "东方明珠")
        assert _poi_name_matches("豫园（老城隍庙）", "豫园")
        assert not _poi_name_matches("幻觉景点甲", "某某大酒店")

    def test_verify_multi_city_partial_failure(self):
        from pipeline.steps.enrich import _verify_poi_exists
        m = MagicMock()
        m.place_text_checked.side_effect = lambda keywords, region, **kw: {"广州": [], "佛山": None}[region]
        v, _ = _verify_poi_exists("某景", ["广州", "佛山"], m)
        assert v is None, "有城市请求失败且无命中 → 未知"
        m.place_text_checked.side_effect = lambda keywords, region, **kw: {"广州": [], "佛山": []}[region]
        v, _ = _verify_poi_exists("某景", ["广州", "佛山"], m)
        assert v is False

    def test_amap_place_text_checked_distinguishes_failure(self):
        from utils import amap_api
        client = amap_api.AMapClient(key="k")
        with patch.object(amap_api, "_request", return_value={}):
            assert client.place_text_checked("x", "杭州") is None
        with patch.object(amap_api, "_request", side_effect=amap_api.AmapApiError("boom")):
            assert client.place_text_checked("x", "杭州") is None
        with patch.object(amap_api, "_request", return_value={"status": "1", "pois": []}):
            assert client.place_text_checked("x", "杭州") == []
        with patch.object(amap_api, "_request", return_value={"status": "1", "pois": [{"name": "a"}]}):
            assert client.place_text_checked("x", "杭州") == [{"name": "a"}]


# ---------------------------------------------------------------------------
#  手册渲染 + Markdown 报告
# ---------------------------------------------------------------------------

EVIL = "<script>alert(1)</script>"


def _sample_inputs():
    fresh = lambda value, src, ttl: pv.stamp(value, src, fetched_at=_ago(1), ttl_hours=ttl)  # noqa: E731
    old = lambda value, src, ttl: pv.stamp(value, src, fetched_at=_ago(24 * 60), ttl_hours=ttl)  # noqa: E731
    itinerary = [{
        "day": 1, "label": "西湖线", "accommodation_city": "杭州",
        "pois": [
            {"name": "西湖", "location": [120.15, 30.25], "address": "西湖区", "time_slot": "09:00-11:00",
             "geo_status": "resolved", "verified": True,
             "opening_hours": "全天开放", "opening_hours_meta": old("全天开放", "amap", pv.TTL_OPENING_HOURS)},
            {"name": "幻觉景点甲", "location": [120.16, 30.26], "address": "", "time_slot": "14:00-16:00",
             "geo_status": "resolved", "verified": False},
            {"name": "灵隐寺", "location": [120.1, 30.24], "address": "法云弄", "time_slot": "16:00-17:00",
             "geo_status": "resolved", "cost": "75", "cost_meta": fresh("75", "amap", pv.TTL_PRICE_HOURS)},
        ],
        "foods": [
            {"name": "某小吃店", "location": [120.17, 30.27], "time_slot": "12:00-13:00", "cuisine": "小吃",
             "cost": "人均60", "cost_meta": fresh("人均60", "llm", pv.TTL_PRICE_HOURS)},
            {"name": "恶意来源餐厅", "location": [120.18, 30.28], "time_slot": "18:00-19:00", "cuisine": "杭帮",
             "cost": "100", "cost_meta": fresh("100", EVIL, pv.TTL_PRICE_HOURS)},
        ],
    }]
    weather = {
        "success": True, "type": "forecast", "city": "杭州",
        "forecast": [{"date": "2026-12-01", "day_weather": "晴", "night_weather": "多云", "temp_range": "5~12°C"}],
        "suggestions": ["✨ 天气宜人"],
        "meta": pv.stamp("forecast", "weather:amap", fetched_at=_ago(8), ttl_hours=pv.TTL_WEATHER_HOURS),  # 8h > 6h 过期
    }
    flyai = {
        "available": True,
        "train": {"items": [{"price": 73.0, "segments": [{"dep_time": "2026-12-01 08:00", "arr_time": "2026-12-01 09:00",
                                                          "duration_min": 60}], "jump_url": ""}],
                  "source": "cache", "cheapest": 73.0, "count": 1,
                  "price_meta": fresh(73.0, "flyai", pv.TTL_PRICE_HOURS),
                  "schedule_meta": fresh(1, "flyai", pv.TTL_SCHEDULE_HOURS)},
        "hotel": {"items": [{"name": "测试酒店", "price": 388.0, "star": "四星", "main_pic": "", "jump_url": ""}],
                  "source": "live", "cheapest": 388.0, "count": 1,
                  "price_meta": old(388.0, "flyai", pv.TTL_PRICE_HOURS)},
        "tickets": {"灵隐寺": {
            "price_min": 75, "price_max": 75, "source": "regex",
            "price_meta": fresh({"min": 75, "max": 75}, "flyai", pv.TTL_PRICE_HOURS)}},
    }
    return itinerary, weather, flyai


def build_sample_html():
    """用测试夹具生成一份示例手册 HTML（离线）。"""
    from utils.brochure import generate_brochure
    itinerary, weather, flyai = _sample_inputs()
    amap_hotels = [{"name": "高德酒店A", "location": "120.1,30.2", "address": "x", "rating": "4.5",
                    "cost": "399", "tel": "", "distance": 100}]
    with patch("utils.brochure._fetch_photos_batch", return_value={}), \
            patch("utils.brochure._search_hotels", return_value=amap_hotels):
        return generate_brochure(itinerary, "杭州", start_city="上海", weather=weather, tips={},
                                 flyai_prices=flyai, research_source="xiaohongshu")


@pytest.fixture(scope="module")
def html():
    return build_sample_html()


class TestBrochureProvenance:
    def test_source_and_updated_at_rendered(self, html):
        assert re.search(r'class="pv">价格：高德地图 · 更新于 \d\d-\d\d \d\d:\d\d</p>', html), "灵隐寺价格行"
        assert "门票：飞猪 FlyAI · 更新于" in html
        assert "酒店价格：" in html

    def test_llm_estimate_labeled(self, html):
        assert "价格：AI 估算，请核实 · 更新于" in html

    def test_stale_rows_grayed_with_warning(self, html):
        # 营业时间 60 天前（>30 天）、天气 8h 前（>6h）、酒店价格 60 天前（>24h）
        stale_rows = re.findall(r'class="pv stale">([^<]*)<', html)
        joined = "\n".join(stale_rows)
        assert "营业时间 全天开放：高德地图" in joined
        assert "天气：高德天气" in joined
        assert "酒店价格：飞猪 FlyAI" in joined
        assert all("可能已变化，出行前请核实" in r for r in stale_rows) and stale_rows
        # 新鲜数据不应带过期提示
        fresh_rows = re.findall(r'class="pv">([^<]*)<', html)
        assert fresh_rows and all("可能已变化" not in r for r in fresh_rows)

    def test_unverified_poi_flagged(self, html):
        assert "未在地图中检索到，请核实" in html
        assert html.count('<span class="t tr">⚠️ 未在地图中检索到，请核实</span>') == 1

    def test_data_notes_footer(self, html):
        assert 'id="data-note"' in html and "数据说明" in html
        assert "时效规则：价格/门票 1 天、交通时刻 1 天、营业时间 30 天、天气 6 小时" in html

    def test_malicious_source_escaped(self, html):
        assert EVIL not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_amap_hotel_with_cost_no_longer_crashes(self):
        """_search_hotels 返回带价格的酒店时曾因 cost_display 未赋值而崩溃；现应渲染价格与来源。"""
        from utils.brochure import generate_brochure
        itinerary, weather, _ = _sample_inputs()
        amap_hotels = [{"name": "高德酒店A", "location": "120.1,30.2", "address": "x", "rating": "4.5",
                        "cost": "399", "tel": "", "distance": 100}]
        with patch("utils.brochure._fetch_photos_batch", return_value={}), \
                patch("utils.brochure._search_hotels", return_value=amap_hotels), \
                patch("utils.amap_api.AMapClient.geocode", return_value=(120.15, 30.25)):
            html = generate_brochure(itinerary, "杭州", weather=weather, tips={})
        assert "¥399" in html and "高德酒店A" in html
        assert re.search(r'class="pv">价格：高德地图 · 更新于 \d\d-\d\d \d\d:\d\d</div>', html)

    def test_old_data_without_meta_renders_no_provenance(self):
        from utils.brochure import generate_brochure
        itinerary = [{"day": 1, "accommodation_city": "上海",
                      "pois": [{"name": "外滩", "location": [121.49, 31.24], "time_slot": "09:00-11:00",
                                "cost": "50"}], "foods": []}]
        with patch("utils.brochure._fetch_photos_batch", return_value={}), \
                patch("utils.brochure._search_hotels", return_value=[]):
            html = generate_brochure(itinerary, "上海", tips={})
        assert 'class="pv' not in html.split("</style>", 1)[1]  # 正文中没有溯源行（CSS 里有 .pv 定义）
        assert "数据说明" in html


class TestMarkdownReport:
    def test_report_has_source_notes(self, tmp_path):
        from pipeline.steps import report
        itinerary, _, _ = _sample_inputs()
        context = {"city": "杭州", "timestamp": "2026-11-18 10:00:00", "itinerary": itinerary,
                   "preferences": {}, "research_notes": []}
        with patch.object(report, "PROJECT_ROOT", str(tmp_path)):
            ctx = report.step_8_generate_report(context)
        text = open(ctx["report_path"], encoding="utf-8").read()
        assert "¥75（高德地图，更新于" in text
        assert "人均60（AI 估算，请核实，更新于" in text
        assert "🕒 营业时间 全天开放（高德地图，更新于" in text and "可能已变化，出行前请核实" in text
        assert "⚠️ 未在地图中检索到，请核实" in text


class TestWeatherMeta:
    def test_weather_meta_attached(self):
        from utils import weather
        fake = {"success": True, "type": "forecast", "city": "杭州", "forecast": [], "suggestions": []}
        with patch.object(weather, "_get_weather_for_dates", return_value=fake):
            wx = weather.get_weather_for_dates("杭州", "2026-12-01", 2)
        assert wx["meta"]["source"] == "weather:amap" and wx["meta"]["ttl_hours"] == pv.TTL_WEATHER_HOURS
        hist = {"success": True, "type": "historical", "city": "杭州", "forecast": [], "suggestions": []}
        with patch.object(weather, "_get_weather_for_dates", return_value=hist):
            assert weather.get_weather_for_dates("杭州")["meta"]["source"] == "weather:open-meteo"

    def test_failed_weather_has_no_meta(self):
        from utils import weather
        fail = {"success": False, "type": "unavailable", "forecast": []}
        with patch.object(weather, "_get_weather_for_dates", return_value=fail):
            assert "meta" not in weather.get_weather_for_dates("杭州")
