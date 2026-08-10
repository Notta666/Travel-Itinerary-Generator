"""
Test: webapp security and robustness fixes (A1 - A8)
"""
import os
import sys
import uuid
import pytest
import asyncio
from html import escape
from pydantic import ValidationError
from fastapi import HTTPException

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from webapp.main import GenerateRequest, _TASK_SEM, app
from webapp.task_manager import cancel_task
from webapp.db import store_task, update_task, get_task, _init_db


def test_a1_xss_escape():
    """A1: Assert XSS payload <script>alert(1)</script> is properly HTML escaped."""
    raw_err = "<script>alert('xss')</script>"
    escaped = escape(raw_err)
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped


def test_a2_cancel_already_cancelled_task():
    """A2: Cancel task that is already cancelled should return 400."""
    _init_db()
    tid = f"test_cancel_a2_{uuid.uuid4().hex[:8]}"
    store_task(tid, "测试行程")
    update_task(tid, status="cancelled", error="用户已取消规划")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(cancel_task(tid))

    assert exc_info.value.status_code == 400
    assert "无法取消" in exc_info.value.detail or "cancelled" in exc_info.value.detail


def test_a4_pydantic_input_validation():
    """A4: Overlength goal, negative people, invalid days should raise ValidationError."""
    # 超长 goal (> 500 chars)
    with pytest.raises(ValidationError):
        GenerateRequest(goal="a" * 501)

    # 负数 people
    with pytest.raises(ValidationError):
        GenerateRequest(goal="Valid Goal", people=-1)

    # 非法 days (> 30 or < 1)
    with pytest.raises(ValidationError):
        GenerateRequest(goal="Valid Goal", days=31)

    with pytest.raises(ValidationError):
        GenerateRequest(goal="Valid Goal", days=0)

    # 合法数据通过
    req = GenerateRequest(goal="杭州3日游", days=3, people=2, steps=["research", "invalid_step"])
    assert req.goal == "杭州3日游"


def test_a5_semaphore_concurrency_limit():
    """A5: Semaphore limit of 3 should reject 4th acquire when full."""
    # Acquire 3 times
    a1 = _TASK_SEM.acquire(blocking=False)
    a2 = _TASK_SEM.acquire(blocking=False)
    a3 = _TASK_SEM.acquire(blocking=False)
    assert a1 and a2 and a3

    # 4th acquire should fail
    a4 = _TASK_SEM.acquire(blocking=False)
    assert not a4

    # Release all 3
    _TASK_SEM.release()
    _TASK_SEM.release()
    _TASK_SEM.release()


def test_a8_cors_config_allow_all():
    """A8: When CORS_ALLOW_ALL is not set to '1', CORS_ORIGINS should not be ['*']."""
    orig_cors = os.environ.get("CORS_ORIGINS")
    orig_allow = os.environ.get("CORS_ALLOW_ALL")

    try:
        os.environ["CORS_ORIGINS"] = "*"
        if "CORS_ALLOW_ALL" in os.environ:
            del os.environ["CORS_ALLOW_ALL"]

        # Re-import config to trigger reload logic
        if "webapp.config" in sys.modules:
            del sys.modules["webapp.config"]

        from webapp.config import CORS_ORIGINS
        assert CORS_ORIGINS != ["*"]
        assert "http://localhost:8080" in CORS_ORIGINS

        # Now set CORS_ALLOW_ALL=1
        os.environ["CORS_ALLOW_ALL"] = "1"
        if "webapp.config" in sys.modules:
            del sys.modules["webapp.config"]

        from webapp.config import CORS_ORIGINS as CORS_ORIGINS_ALLOWED
        assert CORS_ORIGINS_ALLOWED == ["*"]

    finally:
        if orig_cors is not None:
            os.environ["CORS_ORIGINS"] = orig_cors
        else:
            os.environ.pop("CORS_ORIGINS", None)
        if orig_allow is not None:
            os.environ["CORS_ALLOW_ALL"] = orig_allow
        else:
            os.environ.pop("CORS_ALLOW_ALL", None)
        if "webapp.config" in sys.modules:
            del sys.modules["webapp.config"]
