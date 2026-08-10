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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main page from the Jinja2 template."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/check-opencli")
async def check_opencli_route():
    """Check OpenCLI installation and Xiaohongshu login status."""
    from utils.research import check_opencli_status
    ok, msg, details = check_opencli_status()
    return {"ok": ok, "message": msg, "details": details}


@app.post("/generate")
async def generate(data: GenerateRequest):
    """Submit a generation task."""
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

    if not isinstance(enabled_steps, (list, tuple, set)):
        enabled_steps = ["research", "enrich", "distance", "flyai", "tips"]
    else:
        enabled_steps = [s for s in enabled_steps if s in VALID_STEPS]
        if "research" not in enabled_steps:
            enabled_steps.append("research")

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


# Register the imported cancel_task function as a FastAPI POST route
app.post("/cancel/{task_id}")(cancel_task)


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """Query task status."""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    resp = {
        "status": task["status"],
        "goal": task.get("goal", ""),
        "created": task.get("created", 0),
    }
    if task["status"] == "completed":
        resp["result"] = task.get("result", {})
    if task["status"] == "failed":
        resp["error"] = task.get("error", "")
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
    return FileResponse(path, filename=os.path.basename(path), media_type="text/html")


@app.get("/stream/{task_id}")
async def stream_progress(task_id: str, request: Request):
    """SSE endpoint: real-time progress via Server-Sent Events."""
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

    seen = len(json.loads(task.get("progress", "[]")))

    async def _stream():
        nonlocal seen
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
            if len(progress) > seen:
                for p in progress[seen:]:
                    yield f"data: {json.dumps({'message': p.get('message', ''), 'step': p.get('step', ''), 'pct': p.get('pct', 0), 'done': False}, ensure_ascii=False)}\n\n"
                seen = len(progress)
            if task["status"] == "completed":
                yield f"data: {json.dumps({'message': '✅ 任务完成', 'done': True}, ensure_ascii=False)}\n\n"
                break
            if task["status"] == "failed":
                err_msg = task.get("error", "")
                yield f"data: {json.dumps({'message': '❌ 失败: ' + err_msg, 'done': True, 'failed': True, 'error': err_msg}, ensure_ascii=False)}\n\n"
                break
    return StreamingResponse(_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    # 监听地址可配置：默认仅本机（安全）；外部访问（局域网/隧道）时设 HOST=0.0.0.0
    _host = os.environ.get("HOST", "127.0.0.1")
    print("🌍 AI旅行攻略 Web App 启动中...")
    print(f"   访问地址: http://localhost:8080  (host={_host})")
    print("   按 Ctrl+C 停止")
    print(f"   SQLite 数据库: {DB_PATH}")
    uvicorn.run(app, host=_host, port=8080, timeout_keep_alive=600)

