import sys, os

# Ensure project root is importable before importing local webapp submodules
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

import json, uuid, asyncio, threading
from html import escape
from pydantic import BaseModel, Field

from webapp.config import STATIC_DIR, TEMPLATES_DIR, OUTPUTS_DIR, DB_PATH, CORS_ORIGINS
from webapp.db import _init_db, store_task, update_task, get_task
from webapp.task_manager import _run_pipeline_task, cancel_task

# Aliases to keep original method bodies of routes unchanged
_store_task = store_task
_update_task = update_task
_get_task = get_task

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI旅行攻略", version="3.5.7")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["POST", "GET", "OPTIONS"], allow_headers=["*"])

# Static files and templates setup
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Initialize database
_init_db()

_TASK_SEM = threading.Semaphore(3)
VALID_STEPS = {"research", "enrich", "distance", "flyai", "tips"}

_rate_limit_lock = threading.Lock()
_ip_request_records = {}  # ip -> list of timestamps


def _verify_api_token(request: Request):
    """If API_TOKEN is configured in environment, require and verify token in headers/query."""
    expected_token = os.environ.get("API_TOKEN", "").strip()
    if not expected_token:
        return  # No token required by default
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "x-api-key" in request.headers:
        token = request.headers.get("x-api-key", "").strip()
    elif "token" in request.query_params:
        token = request.query_params.get("token", "").strip()
    
    if not token or token != expected_token:
        raise HTTPException(401, "API Token 无效或未提供")


def _check_rate_limit(request: Request, max_per_minute=10):
    """Simple in-memory rate limiting per client IP."""
    client_ip = request.client.host if request.client else "unknown"
    now = asyncio.get_event_loop().time() if False else threading.time.time() if hasattr(threading, "time") else __import__("time").time()
    with _rate_limit_lock:
        timestamps = _ip_request_records.get(client_ip, [])
        timestamps = [t for t in timestamps if now - t < 60]
        if len(timestamps) >= max_per_minute:
            raise HTTPException(429, "请求频率过高，每分钟最多允许 10 次生成请求")
        timestamps.append(now)
        _ip_request_records[client_ip] = timestamps


class GenerateRequest(BaseModel):
    goal: str = Field(..., max_length=500)
    days: int | None = Field(None, ge=1, le=30)
    people: int | None = Field(None, ge=1, le=20)
    budget: float | None = Field(None, ge=0)
    hotel_budget_min: float = Field(300, ge=0)
    hotel_budget_max: float = Field(500, ge=0)
    steps: list[str] | None = None
    prefs: dict = Field(default_factory=dict)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "3.5.7"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main page from the Jinja2 template."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/check-opencli")
async def check_opencli_route():
    """Check OpenCLI installation and Xiaohongshu login status."""
    from utils.research import check_opencli_status
    ok, msg, details = check_opencli_status()
    # P3-13: 不回传敏感 npm/安装路径细节
    return {"ok": ok, "message": msg}


@app.post("/generate")
async def generate(data: GenerateRequest, request: Request):
    """Submit a generation task."""
    _verify_api_token(request)
    _check_rate_limit(request)

    from utils.research import check_opencli_status
    # 小红书调研为可选项：未连接 OpenCLI 时降级为内置推荐库，不再硬拒（与 CLI 行为一致）
    ok, check_msg, details = check_opencli_status()
    if not ok:
        print(f"  ℹ️ 未检测到 OpenCLI/小红书登录态，将使用内置推荐库生成（{check_msg}）")

    goal = data.goal.strip()
    enabled_steps = data.steps
    days = data.days
    people = data.people
    budget = data.budget
    hotel_budget_min = data.hotel_budget_min
    hotel_budget_max = data.hotel_budget_max
    user_prefs = data.prefs

    if hotel_budget_min > hotel_budget_max:
        raise HTTPException(400, "酒店预算下限不能大于上限")

    if not isinstance(enabled_steps, (list, tuple, set)):
        enabled_steps = ["research", "enrich", "distance", "flyai", "tips"]
    else:
        # P3-13: 尊重用户选项，不强制追加 research
        enabled_steps = [s for s in enabled_steps if s in VALID_STEPS]

    if not goal:
        raise HTTPException(400, "请输入目的地描述")

    if not _TASK_SEM.acquire(blocking=False):
        raise HTTPException(429, "任务队列已满，请稍后再试")

    task_id = uuid.uuid4().hex[:12]
    _store_task(task_id, goal)

    def _run_with_sem():
        try:
            _run_pipeline_task(task_id, goal, enabled_steps, people, budget, hotel_budget_min, hotel_budget_max, user_prefs, days, ok)
        finally:
            _TASK_SEM.release()

    # Run in background thread (non-blocking)
    thread = threading.Thread(
        target=_run_with_sem,
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/cancel/{task_id}")
async def cancel_task_endpoint(task_id: str, request: Request):
    """Cancel task with optional API_TOKEN check."""
    _verify_api_token(request)
    return await cancel_task(task_id)


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """Query task status with progress support for SSE fallback polling (P3-15)."""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    try:
        progress_data = json.loads(task.get("progress", "[]"))
    except (json.JSONDecodeError, TypeError):
        progress_data = []
    resp = {
        "status": task["status"],
        "goal": task.get("goal", ""),
        "created": task.get("created", 0),
        "progress": progress_data,
    }
    if task["status"] == "completed":
        resp["result"] = task.get("result", {})
    if task["status"] == "failed":
        resp["error"] = task.get("error", "")
    if task["status"] == "cancelled":
        resp["error"] = task.get("error", "用户已取消规划")
    return resp


@app.get("/result/{task_id}", response_class=HTMLResponse)
async def get_result(task_id: str):
    """Get the complete brochure page."""
    task = _get_task(task_id)
    if not task:
        return HTMLResponse("<div style='padding:40px;text-align:center;'><h2>任务不存在</h2></div>", status_code=404)
    if task["status"] == "failed":
        err_msg = task.get("error", "行程生成失败")
        return HTMLResponse(f"<div style='padding:40px;text-align:center;color:#e53e3e;font-family:sans-serif;'><h2>生成失败</h2><p>{escape(err_msg)}</p></div>", status_code=400)
    if task["status"] != "completed":
        return HTMLResponse(f"<div style='padding:40px;text-align:center;font-family:sans-serif;'><h2>任务未完成</h2><p>当前状态: {escape(str(task['status']))}</p></div>", status_code=400)
    brochure_html = task.get("result", {}).get("brochure", "")
    if not brochure_html:
        return HTMLResponse("<div style='padding:40px;text-align:center;font-family:sans-serif;'><h2>手册生成中，请稍后查看</h2></div>")
    return HTMLResponse(brochure_html)


@app.get("/download/{task_id}")
async def download(task_id: str):
    """Download the brochure HTML file."""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    path = task.get("result", {}).get("brochure_path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(404, "文件不存在")
    # P3-13: 校验路径在 OUTPUTS_DIR 内，防止目录穿越
    real_path = os.path.realpath(path)
    real_outputs = os.path.realpath(OUTPUTS_DIR)
    if not (real_path == real_outputs or real_path.startswith(real_outputs + os.sep)):
        raise HTTPException(403, "非法下载路径")
    return FileResponse(real_path, filename=os.path.basename(real_path), media_type="text/html")


@app.get("/stream/{task_id}")
async def stream_progress(task_id: str, request: Request, seen: int = None):
    """SSE endpoint: real-time progress via Server-Sent Events with reconnection gap prevention (P3-14)."""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    if task["status"] == "completed":
        async def _done():
            yield f"data: {json.dumps({'message': '✅ 任务已完成', 'done': True}, ensure_ascii=False)}\n\n"
        return StreamingResponse(_done(), media_type="text/event-stream")

    if task["status"] == "failed":
        err_msg = task.get("error", "")
        async def _failed():
            yield f"data: {json.dumps({'message': '❌ 失败: ' + err_msg, 'done': True, 'failed': True, 'error': err_msg}, ensure_ascii=False)}\n\n"
        return StreamingResponse(_failed(), media_type="text/event-stream")

    if task["status"] == "cancelled":
        err_msg = task.get("error", "用户已取消规划")
        async def _cancelled():
            yield f"data: {json.dumps({'message': '⛔ 任务已取消: ' + err_msg, 'done': True, 'failed': True, 'cancelled': True, 'error': err_msg}, ensure_ascii=False)}\n\n"
        return StreamingResponse(_cancelled(), media_type="text/event-stream")

    # P3-14: 支持 ?seen= query 参数及 Last-Event-ID header，避免重连时产生时间线间隙
    if seen is None:
        last_id = request.headers.get("last-event-id")
        if last_id and last_id.isdigit():
            seen_idx = int(last_id)
        else:
            seen_idx = 0
    else:
        seen_idx = max(0, seen)

    async def _stream():
        nonlocal seen_idx
        yield f"data: {json.dumps({'message': '⏳ 任务已提交，等待执行...', 'done': False}, ensure_ascii=False)}\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
            if await request.is_disconnected():
                break
            task = _get_task(task_id)
            if not task:
                yield f"data: {json.dumps({'message': '❌ 任务已消失', 'done': True, 'failed': True}, ensure_ascii=False)}\n\n"
                break
            try:
                progress = json.loads(task.get("progress", "[]"))
            except (json.JSONDecodeError, TypeError):
                progress = []
            if len(progress) > seen_idx:
                for idx, p in enumerate(progress[seen_idx:], start=seen_idx + 1):
                    yield f"id: {idx}\ndata: {json.dumps({'message': p.get('message', ''), 'step': p.get('step', ''), 'pct': p.get('pct', 0), 'done': False}, ensure_ascii=False)}\n\n"
                seen_idx = len(progress)
            if task["status"] == "completed":
                yield f"data: {json.dumps({'message': '✅ 任务完成', 'done': True}, ensure_ascii=False)}\n\n"
                break
            if task["status"] == "failed":
                err_msg = task.get("error", "")
                yield f"data: {json.dumps({'message': '❌ 失败: ' + err_msg, 'done': True, 'failed': True, 'error': err_msg}, ensure_ascii=False)}\n\n"
                break
            if task["status"] == "cancelled":
                err_msg = task.get("error", "用户已取消规划")
                yield f"data: {json.dumps({'message': '⛔ 任务已取消: ' + err_msg, 'done': True, 'failed': True, 'cancelled': True, 'error': err_msg}, ensure_ascii=False)}\n\n"
                break
    return StreamingResponse(_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    # 监听地址与端口可配置：默认 0.0.0.0:8080
    _host = os.environ.get("HOST", "0.0.0.0")
    _port = int(os.environ.get("PORT", "8080"))
    print("🌍 AI旅行攻略 Web App 启动中...")
    print(f"   访问地址: http://localhost:{_port}  (host={_host})")
    print("   按 Ctrl+C 停止")
    print(f"   SQLite 数据库: {DB_PATH}")
    uvicorn.run(app, host=_host, port=_port, timeout_keep_alive=600)

