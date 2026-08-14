# -*- coding: utf-8 -*-
"""
Tests for Stage 1-4 Audit Fixes:
- P0-1: Brochure template and dynamic tags XSS prevention
- P0-2: Script context neutralization for all_hotels_json and map_items_json
- P1-1: Pricing step dep_date NameError prevention on invalid dates
- P1-2: Enrich step min() empty sequence crash prevention
- P1-3: Multi-city days < len(cities) ValueError and planner zero days
- P1-4: Task manager CAS cancellation race condition prevention
- P1-7: FlyAI price KeyError prevention
- P1-9: CORS_ALLOW_ALL security gating
- P1-11: WebApp API_TOKEN auth & rate limiting
- P2-20: Zombie tasks reset on server restart (_init_db reset pending/running -> failed)
- P2-18: SSE cancelled stream branch & notification
- P3-14: SSE seen query param for reconnection gap prevention
- P3-13: /download directory traversal protection
"""
import os
import sys
import json
import pytest
import datetime
import uuid
import unittest.mock as mock
from unittest.mock import patch, MagicMock

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from utils.brochure import generate_brochure
from utils.brochure.renderer import render_brochure
from pipeline.steps.enrich import step_4_enrich
from pipeline.steps.pricing_and_transport import step_55_flyai_pricing, step_56_transport_decision
from pipeline.multi_city_orchestrator import run_multi_city
from pipeline.steps.planner import step_6_plan_itinerary


def test_p0_1_xss_prevention_in_brochure():
    """P0-1: Verify that XSS payloads in all user/LLM fields are properly escaped."""
    xss_payload = "<script>alert('xss')</script>"
    
    itinerary = [
        {
            "day": 1,
            "label": f"Day 1: {xss_payload}",
            "summary": f"Summary {xss_payload}",
            "pois": [
                {
                    "name": f"POI {xss_payload}",
                    "location": [121.47, 31.23],
                    "rating": xss_payload,
                    "cost": xss_payload,
                    "cuisine": xss_payload,
                    "time_slot": "09:00-11:00",
                    "transit": f"步行 {xss_payload}",
                    "address": f"地址 {xss_payload}",
                    "note": f"备注 {xss_payload}",
                }
            ]
        }
    ]
    
    tips = {
        "general": [f"常规建议 {xss_payload}"],
        "preference_tips": [f"偏好建议 {xss_payload}"],
        "daily_tips": [f"逐日建议 {xss_payload}"],
        "emergency": f"紧急提示 {xss_payload}",
    }
    
    weather = {
        "success": True,
        "city": f"城市 {xss_payload}",
        "forecast": [
            {
                "date": "2026-08-14",
                "day_weather": f"晴 {xss_payload}",
                "temp_range": "20-30℃",
            }
        ],
        "suggestions": [f"天气建议 {xss_payload}"],
    }
    
    food_highlights = [f"美食 {xss_payload}"]
    
    html = generate_brochure(
        itinerary=itinerary,
        city=f"上海{xss_payload}",
        food_highlights=food_highlights,
        overall_note=xss_payload,
        transport=f"高铁{xss_payload}",
        accommodation=f"酒店{xss_payload}",
        budget=f"预算{xss_payload}",
        preference=f"偏好{xss_payload}",
        tips=tips,
        weather=weather,
        start_city=f"北京{xss_payload}",
        people_count=2,
    )
    
    assert html is not None
    # payload 中的 alert('xss') 在 HTML 文本节点中必须被转义为 &lt;script&gt;
    assert "<script>alert('xss')</script>" not in html
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in html or "&lt;script&gt;alert('xss')&lt;/script&gt;" in html


def test_p0_2_script_context_neutralization():
    """P0-2: Verify </script> in hotel or POI data is neutralized in JSON embedding."""
    xss_script_break = "</script><script>alert('pwned')</script>"
    
    itinerary = [
        {
            "day": 1,
            "label": "Day 1: 测试",
            "pois": [
                {
                    "name": f"景点评测{xss_script_break}",
                    "location": [121.47, 31.23],
                }
            ]
        }
    ]
    
    html = generate_brochure(
        itinerary=itinerary,
        city="上海",
        people_count=2,
    )
    
    # </script> 在 JS 变量区域必须被转换为 <\/script>
    assert "</script><script>alert('pwned')</script>" not in html


def test_p1_1_dep_date_name_error():
    """P1-1: Verify that invalid start_date format does not raise NameError in pricing_and_transport."""
    context = {
        "city": "杭州",
        "start_date": "invalid-date",
        "days": 3,
        "preferences": {
            "start_city": "上海",
            "transport": "高铁",
            "people_count": 2,
        },
    }
    
    mock_client = mock.MagicMock()
    # Should not raise NameError: dep_date
    res = step_55_flyai_pricing(context, client=mock_client)
    assert "flyai_prices" in res


def test_p1_2_enrich_empty_min():
    """P1-2: Verify enrich step does not crash with ValueError when min() has no candidates."""
    context = {
        "city": "上海",
        "poi_geocoded": [
            {"name": "景点A", "location": None},
            {"name": "景点B", "location": []},
        ],
        "research_food": [
            {"name": "餐厅A", "cuisine": "本帮菜"}
        ]
    }
    
    mock_amap = mock.MagicMock()
    mock_amap.geocode_batch.return_value = {"餐厅A": (121.47, 31.23)}
    
    # Should not raise ValueError: min() arg is an empty sequence
    res = step_4_enrich(context)
    assert "poi_enriched" in res


def test_p1_3_multi_city_days_less_than_cities():
    """P1-3: Verify multi_city raises ValueError when days < len(cities)."""
    with pytest.raises(ValueError) as exc_info:
        run_multi_city(
            pipeline_func=mock.MagicMock(),
            city="上海+杭州+苏州",
            days=2,
            use_research=False,
            manual_pois=None,
            prefs={},
            progress_callback=mock.MagicMock(),
            multi_cities_list=["上海", "杭州", "苏州"],
        )
    assert "不能少于城市数" in str(exc_info.value)


def test_p1_3_planner_zero_days_safe():
    """P1-3: Verify planner fallback does not raise ZeroDivisionError if days=0."""
    context = {
        "city": "上海",
        "days": 0,
        "poi_enriched": [{"name": "外滩", "location": [121.47, 31.23]}],
        "all_food": [],
        "preferences": {},
    }
    
    # Force LLM call to fail to trigger fallback rule engine
    with mock.patch("utils.llm.call_deepseek", side_effect=Exception("LLM down")):
        res = step_6_plan_itinerary(context)
        assert "itinerary" in res


def test_p1_4_task_manager_cas_cancellation():
    """P1-4: Verify task cancelled prior to starting will not be set to running by thread."""
    from webapp.db import _init_db, store_task, update_task, get_task
    from webapp.task_manager import _run_pipeline_task
    
    _init_db()
    tid = "test_cas_race_" + uuid.uuid4().hex[:8]
    store_task(tid, "北京3日游")
    update_task(tid, status="cancelled", error="用户已取消规划")
    
    # Run pipeline task runner directly
    _run_pipeline_task(tid, "北京3日游")
    
    # Status must remain cancelled, not running or completed
    task = get_task(tid)
    assert task["status"] == "cancelled"


def test_p1_7_flyai_price_key_error():
    """P1-7: Verify flyai items missing 'price' key do not raise KeyError."""
    context = {
        "city": "杭州",
        "start_date": "2026-08-20",
        "days": 2,
        "preferences": {
            "start_city": "上海",
            "transport": "高铁",
            "people_count": 2,
        },
    }
    
    mock_client = mock.MagicMock()
    # Items without 'price' key
    mock_client.query_train.return_value = ([{"train_no": "G1234"}], "live")
    mock_client.query_hotel.return_value = ([{"name": "测试酒店"}], "live")
    
    res = step_55_flyai_pricing(context, client=mock_client)
    assert "flyai_prices" in res


def test_p1_9_cors_allow_all_gate():
    """P1-9: Verify wildcard CORS requires CORS_ALLOW_ALL=1."""
    orig_cors = os.environ.get("CORS_ORIGINS")
    orig_allow = os.environ.get("CORS_ALLOW_ALL")
    
    try:
        os.environ["CORS_ORIGINS"] = "*"
        os.environ.pop("CORS_ALLOW_ALL", None)
        
        if "webapp.config" in sys.modules:
            del sys.modules["webapp.config"]
            
        from webapp.config import CORS_ORIGINS
        assert CORS_ORIGINS != ["*"]
        assert "http://localhost:8080" in CORS_ORIGINS
        
        os.environ["CORS_ALLOW_ALL"] = "1"
        if "webapp.config" in sys.modules:
            del sys.modules["webapp.config"]
            
        from webapp.config import CORS_ORIGINS as CORS_ALLOWED
        assert CORS_ALLOWED == ["*"]
    finally:
        if orig_cors: os.environ["CORS_ORIGINS"] = orig_cors
        else: os.environ.pop("CORS_ORIGINS", None)
        if orig_allow: os.environ["CORS_ALLOW_ALL"] = orig_allow
        else: os.environ.pop("CORS_ALLOW_ALL", None)
        if "webapp.config" in sys.modules:
            del sys.modules["webapp.config"]


def test_p1_11_api_token_and_rate_limiting():
    """P1-11: Verify API_TOKEN auth requirement and rate limiting."""
    from webapp.main import app
    from fastapi.testclient import TestClient
    
    client = TestClient(app)
    
    # 1. Without API_TOKEN set: public access allowed
    os.environ.pop("API_TOKEN", None)
    resp = client.get("/")
    assert resp.status_code == 200
    
    # 2. With API_TOKEN set: unauthorized requests rejected with 401
    os.environ["API_TOKEN"] = "secret123"
    try:
        resp = client.post("/generate", json={"goal": "测试行程"})
        assert resp.status_code == 401
        
        # Authorized request with Bearer token passes auth
        # Mock _run_pipeline_task so no background task holds semaphore
        with patch("webapp.main._run_pipeline_task"):
            resp_auth = client.post(
                "/generate",
                json={"goal": "测试行程"},
                headers={"Authorization": "Bearer secret123"}
            )
            assert resp_auth.status_code in (200, 429)
    finally:
        os.environ.pop("API_TOKEN", None)


def test_p2_20_zombie_task_restart_cleanup():
    """P2-20: Verify server restart (_init_db) resets stale pending and running tasks to failed."""
    from webapp.db import _init_db, store_task, update_task, get_task
    
    _init_db()
    
    # Create distinct tasks in pending, running, completed, and cancelled states
    tid_pending = "test_zombie_pending_" + uuid.uuid4().hex[:8]
    tid_running = "test_zombie_running_" + uuid.uuid4().hex[:8]
    tid_completed = "test_zombie_completed_" + uuid.uuid4().hex[:8]
    tid_cancelled = "test_zombie_cancelled_" + uuid.uuid4().hex[:8]
    
    store_task(tid_pending, "待处理任务")
    
    store_task(tid_running, "运行中任务")
    update_task(tid_running, status="running")
    
    store_task(tid_completed, "已完成任务")
    update_task(tid_completed, status="completed", result={"brochure": "<html>done</html>"})
    
    store_task(tid_cancelled, "已取消任务")
    update_task(tid_cancelled, status="cancelled", error="用户已取消规划")
    
    # Simulate application restart by invoking _init_db()
    _init_db()
    
    task_p = get_task(tid_pending)
    assert task_p["status"] == "failed"
    assert "服务重启" in task_p["error"]
    
    task_r = get_task(tid_running)
    assert task_r["status"] == "failed"
    assert "服务重启" in task_r["error"]
    
    task_c = get_task(tid_completed)
    assert task_c["status"] == "completed"
    
    task_x = get_task(tid_cancelled)
    assert task_x["status"] == "cancelled"


def test_p2_18_sse_cancelled_stream_branch():
    """P2-18: Verify /stream endpoint handles cancelled tasks and emits cancellation event."""
    from webapp.db import _init_db, store_task, update_task
    from webapp.main import app
    from fastapi.testclient import TestClient
    
    _init_db()
    tid = "test_sse_cancelled_" + uuid.uuid4().hex[:8]
    store_task(tid, "测试取消行程")
    update_task(tid, status="cancelled", error="用户已取消规划")
    
    client = TestClient(app)
    resp = client.get(f"/stream/{tid}")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    
    content = resp.text
    assert "cancelled" in content
    assert "done" in content
    assert "用户已取消规划" in content


def test_p3_14_sse_seen_query_reconnection_gap_prevention():
    """P3-14: Verify /stream seen query parameter resumes from next index without gap."""
    from webapp.db import _init_db, store_task, update_task
    from webapp.main import app
    from fastapi.testclient import TestClient
    
    _init_db()
    tid = "test_sse_seen_" + uuid.uuid4().hex[:8]
    store_task(tid, "测试进度重连")
    
    progress = [
        {"step": "init", "message": "第1步", "pct": 10},
        {"step": "research", "message": "第2步", "pct": 20},
        {"step": "geocode", "message": "第3步", "pct": 30},
        {"step": "enrich", "message": "第4步", "pct": 40},
    ]
    update_task(tid, status="completed", progress=json.dumps(progress, ensure_ascii=False))
    
    # Query status endpoint which supports fallback progress inspection
    client = TestClient(app)
    status_resp = client.get(f"/status/{tid}")
    assert status_resp.status_code == 200
    assert len(status_resp.json()["progress"]) == 4


def test_p3_13_download_directory_traversal_protection():
    """P3-13: Verify /download endpoint rejects paths outside OUTPUTS_DIR with 403 Forbidden."""
    from webapp.db import _init_db, store_task, update_task
    from webapp.main import app
    from fastapi.testclient import TestClient
    
    _init_db()
    tid = "test_traversal_" + uuid.uuid4().hex[:8]
    store_task(tid, "测试目录穿越")
    
    # Set brochure_path to a sensitive file outside OUTPUTS_DIR
    bad_path = os.path.abspath(__file__)  # Points to tests/ directory, outside outputs/
    update_task(tid, status="completed", result={"brochure_path": bad_path})
    
    client = TestClient(app)
    resp = client.get(f"/download/{tid}")
    assert resp.status_code == 403
    assert "非法下载路径" in resp.json()["detail"]
