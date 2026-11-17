# -*- coding: utf-8 -*-
"""
TR-4 多格式导出测试（全部离线）
===============================
- ics：BEGIN/END 配对、CRLF、每行 ≤75 octets、转义、UID 稳定、全天/定时事件
- gpx/kml：xml.etree 解析、点数、无坐标点跳过、<&> 转义
- deliver 输出 .ics/.gpx/.kml 三个文件，导出异常不影响主产物
- webapp 下载路由：扩展名白名单与 ../ 路径穿越防护；手册模板含导出按钮与 @media print
"""
import asyncio
import datetime
import os
import sys
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
os.environ.setdefault("AMAP_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from utils import exporters  # noqa: E402
from utils.exporters import to_gpx, to_ics, to_kml  # noqa: E402

LONG_NOTE = "这是一段很长的备注，" * 20 + "含逗号,分号;反斜杠\\以及\n换行"
NOW = datetime.datetime(2026, 11, 18, 8, 0, 0, tzinfo=datetime.timezone.utc)


def _ctx():
    return {
        "city": "上海",
        "start_date": "2026-12-01",
        "task_id": "task123",
        "poi_enriched": [{"name": "豫园", "location": [121.4920, 31.2270]}],
        "itinerary": [
            {"day": 1, "label": "老城厢", "pois": [
                {"name": "外滩", "city": "上海", "location": [121.49, 31.24], "time_slot": "09:00-11:30",
                 "transit": "地铁2号线", "note": LONG_NOTE, "cost": "免费",
                 "cost_meta": {"value": "免费", "source": "amap", "fetched_at": "2026-11-18T08:00:00+08:00",
                               "ttl_hours": 24}},
                {"name": "豫园", "city": "上海", "location": None, "time_slot": "下午"},
                {"name": "神秘<地点>&Co", "city": "上海", "location": None, "time_slot": "15:00-16:00"},
            ], "foods": [
                {"name": "南翔小笼馆", "city": "上海", "location": [121.4925, 31.2272], "time_slot": "12:00",
                 "cuisine": "本帮"},
            ]},
            {"day": 2, "label": "", "pois": [
                {"name": "田子坊", "city": "上海", "location": [121.47, 31.21], "time_slot": "10:00-12:00"},
                {"name": "新天地", "city": "上海", "lat": 31.22, "lng": 121.475, "time_slot": ""},
            ], "foods": []},
        ],
    }


def _unfold(text):
    return text.replace("\r\n ", "")


# ---------------------------------------------------------------- ics
def test_ics_structure_and_line_rules():
    ics = to_ics(_ctx(), now=NOW)
    assert ics.endswith("\r\n")
    assert "\n" not in ics.replace("\r\n", "")  # 只有 CRLF，没有裸 LF
    lines = ics.split("\r\n")[:-1]
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    for ln in lines:
        assert len(ln.encode("utf-8")) <= 75, ln
    stack = []
    for ln in lines:
        if ln.startswith("BEGIN:"):
            stack.append(ln[6:])
        elif ln.startswith("END:"):
            assert stack.pop() == ln[4:]
    assert stack == []
    assert "TZID:Asia/Shanghai" in ics and "BEGIN:VTIMEZONE" in ics


def test_ics_events_timed_and_allday():
    ics = _unfold(to_ics(_ctx(), now=NOW))
    assert ics.count("BEGIN:VEVENT") == 6  # 景点5（含未解析坐标的）+ 餐厅1
    assert "DTSTART;TZID=Asia/Shanghai:20261201T090000" in ics
    assert "DTEND;TZID=Asia/Shanghai:20261201T113000" in ics
    assert "DTSTART;TZID=Asia/Shanghai:20261201T120000" in ics  # 单个钟点默认 60 分钟
    assert "DTEND;TZID=Asia/Shanghai:20261201T130000" in ics
    # 「下午」「空」→ 全天事件；第 2 天日期 = start_date + 1
    assert "DTSTART;VALUE=DATE:20261201" in ics and "DTEND;VALUE=DATE:20261202" in ics
    assert "DTSTART;VALUE=DATE:20261202" in ics
    assert "SUMMARY:外滩" in ics
    assert "LOCATION:外滩 上海" in ics
    assert "GEO:31.240000;121.490000" in ics
    assert "GEO:31.227000;121.492000" in ics  # 豫园坐标来自 poi_enriched 回查
    assert "GEO:31.220000;121.475000" in ics  # slot 自带 lat/lng


def test_ics_text_escaping_and_provenance():
    ics = _unfold(to_ics(_ctx(), now=NOW))
    assert "含逗号\\,分号\\;反斜杠\\\\以及\\n换行" in ics
    assert "价格：免费（高德地图，更新于 11-18 08:00" in ics
    assert "SUMMARY:神秘<地点>&Co" in ics  # ics 不做 XML 转义


def test_ics_uid_stable_and_unique():
    a = to_ics(_ctx(), now=NOW)
    b = to_ics(_ctx(), now=NOW + datetime.timedelta(hours=5))
    uids = lambda t: [ln for ln in t.split("\r\n") if ln.startswith("UID:")]  # noqa: E731
    assert uids(a) == uids(b)
    assert len(set(uids(a))) == len(uids(a)) == 6
    assert all(u.endswith("@travel-itinerary") for u in uids(a))
    other = _ctx()
    other["task_id"] = "task999"
    assert uids(to_ics(other, now=NOW)) != uids(a)


def test_ics_bad_start_date_yields_valid_empty_calendar():
    ctx = _ctx()
    ctx["start_date"] = "not-a-date"
    ics = to_ics(ctx, now=NOW)
    assert "BEGIN:VEVENT" not in ics and ics.startswith("BEGIN:VCALENDAR")


# ------------------------------------------------------------ gpx / kml
GPX_NS = {"g": "http://www.topografix.com/GPX/1/1"}
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}


def test_gpx_parse_points_and_skip_unlocated():
    root = ET.fromstring(to_gpx(_ctx()).encode("utf-8"))
    assert root.get("version") == "1.1"
    rtes = root.findall("g:rte", GPX_NS)
    assert len(rtes) == 2
    day1 = [p.find("g:name", GPX_NS).text for p in rtes[0].findall("g:rtept", GPX_NS)]
    assert day1 == ["外滩", "豫园", "南翔小笼馆"]  # 无坐标的「神秘<地点>&Co」被跳过；按时间排序
    pt = rtes[0].find("g:rtept", GPX_NS)
    assert float(pt.get("lat")) == pytest.approx(31.24) and float(pt.get("lon")) == pytest.approx(121.49)
    assert len(rtes[1].findall("g:rtept", GPX_NS)) == 2
    desc = root.find("g:metadata/g:desc", GPX_NS).text
    assert desc.startswith("1 个无坐标")


def test_gpx_kml_escape_special_chars():
    ctx = _ctx()
    ctx["itinerary"][0]["pois"].append({"name": "A<b>&\"C'", "location": [121.5, 31.25], "time_slot": "17:00-18:00"})
    gpx, kml = to_gpx(ctx), to_kml(ctx)
    assert "A&lt;b&gt;&amp;" in gpx and "A&lt;b&gt;&amp;" in kml
    names = [n.text for n in ET.fromstring(gpx.encode("utf-8")).iter("{%s}name" % GPX_NS["g"])]
    assert "A<b>&\"C'" in names
    names = [n.text for n in ET.fromstring(kml.encode("utf-8")).iter("{%s}name" % KML_NS["k"])]
    assert "A<b>&\"C'" in names


def test_kml_folders_placemarks_linestring():
    root = ET.fromstring(to_kml(_ctx()).encode("utf-8"))
    folders = root.findall("k:Document/k:Folder", KML_NS)
    assert len(folders) == 2
    pms = folders[0].findall("k:Placemark", KML_NS)
    points = [p for p in pms if p.find("k:Point", KML_NS) is not None]
    lines = [p for p in pms if p.find("k:LineString", KML_NS) is not None]
    assert len(points) == 3 and len(lines) == 1
    coords = lines[0].find("k:LineString/k:coordinates", KML_NS).text.split()
    assert len(coords) == 3 and coords[0].startswith("121.490000,31.240000")
    assert root.find("k:Document/k:description", KML_NS).text.startswith("1 个无坐标")


def test_exports_empty_itinerary_still_valid():
    ctx = {"city": "X", "start_date": "2026-12-01", "itinerary": []}
    ET.fromstring(to_gpx(ctx).encode("utf-8"))
    ET.fromstring(to_kml(ctx).encode("utf-8"))
    assert "BEGIN:VCALENDAR" in to_ics(ctx)


# --------------------------------------------------------------- deliver
def test_deliver_writes_three_exports_next_to_brochure(tmp_path, capsys):
    from pipeline.steps import deliver
    brochure = tmp_path / "上海_brochure_x.html"
    ctx = _ctx()

    def fake_generate(**kw):
        brochure.write_text("<html></html>", encoding="utf-8")
        return str(brochure)

    with patch("utils.brochure.generate", side_effect=fake_generate):
        out = deliver.step_9_deliver(ctx)
    for ext in ("ics", "gpx", "kml"):
        assert (tmp_path / f"上海_brochure_x.{ext}").exists()
    assert out["brochure_path"] == str(brochure)
    printed = capsys.readouterr().out
    assert "图文手册" in printed and "日历(ics)" in printed and "GPX" in printed and "KML" in printed


def test_deliver_export_failure_is_warning_only(tmp_path, capsys):
    from pipeline.steps import deliver
    brochure = tmp_path / "b.html"
    brochure.write_text("<html></html>", encoding="utf-8")
    ctx = _ctx()
    ctx["brochure_path"] = str(brochure)
    with patch("utils.brochure.generate", return_value=str(brochure)), \
            patch.object(exporters, "EXPORTERS", (("ics", lambda c: 1 / 0), ("gpx", exporters.to_gpx),
                                                  ("kml", exporters.to_kml))):
        out = deliver.step_9_deliver(ctx)
    assert out["brochure_path"] == str(brochure)
    assert not (tmp_path / "b.ics").exists()
    assert (tmp_path / "b.gpx").exists() and (tmp_path / "b.kml").exists()


# ---------------------------------------------------- 手册模板 / webapp
def test_brochure_template_has_export_buttons_and_print_css():
    from utils.brochure.renderer import render_brochure
    html = render_brochure(
        city="上海", trip_label="二日深度游", date_range_str="", accommodation="", cover_extra_html="",
        day_html="", hotel_html="", tips_html="", weather_html="", budget_html="", tickets_html="",
        food_highlights_html="", transport_html="", day_map_labels=[], map_items_json="[]",
        all_hotels_json="[]", research_source="", generated_ts="", export_base="上海_brochure_x")
    assert 'href="%E4%B8%8A%E6%B5%B7_brochure_x.ics"' in html
    assert 'href="%E4%B8%8A%E6%B5%B7_brochure_x.gpx"' in html
    assert 'href="%E4%B8%8A%E6%B5%B7_brochure_x.kml"' in html
    assert "window.print()" in html and "@media print" in html
    assert "page-break-inside:avoid" in html


def test_webapp_export_download_whitelist_and_traversal(tmp_path):
    from fastapi import HTTPException
    from webapp import main as wm

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "t.html").write_text("<html></html>", encoding="utf-8")
    (outputs / "t.ics").write_text("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", encoding="utf-8")
    (tmp_path / "secret.ics").write_text("secret", encoding="utf-8")

    def run(task_path, ext):
        task = {"result": {"brochure_path": task_path}}
        with patch.object(wm, "_get_task", return_value=task), patch.object(wm, "OUTPUTS_DIR", str(outputs)):
            return asyncio.run(wm.download_export("tid", ext))

    resp = run(str(outputs / "t.html"), "ics")
    assert resp.media_type == "text/calendar"
    with pytest.raises(HTTPException) as e:
        run(str(outputs / "t.html"), "exe")  # 扩展名不在白名单
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        run(str(outputs / "t.html"), "gpx")  # 文件不存在
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        run(str(outputs / ".." / "secret.html"), "ics")  # 路径穿越到 outputs 之外
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        run(str(outputs / "t.html"), "../secret")  # ext 本身带 ../
    assert e.value.status_code == 404


def test_webapp_result_rewrites_export_links(tmp_path):
    from webapp import main as wm
    html = '<a href="b%C3%A9.ics">x</a><a href="other.ics">y</a>'
    task = {"status": "completed", "result": {"brochure": html, "brochure_path": str(tmp_path / "bé.html")}}
    with patch.object(wm, "_get_task", return_value=task):
        resp = asyncio.run(wm.get_result("abc123"))
    body = resp.body.decode("utf-8")
    assert 'href="/download/abc123/ics"' in body and 'href="other.ics"' in body
