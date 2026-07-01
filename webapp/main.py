import sys, os

# Ensure project root is importable before importing local webapp submodules
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

import json, uuid, asyncio, threading

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

app = FastAPI(title="AI旅行攻略", version="3.5.5")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

# Static files and templates setup
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Initialize database
_init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main page from the Jinja2 template."""
    return templates.TemplateResponse(request, "index.html")


@app.post("/generate")
async def generate(data: dict):
    """Submit a generation task."""
    goal = (data.get("goal") or "").strip()
    enabled_steps = data.get("steps")
    people = data.get("people")
    budget = data.get("budget")
    hotel_budget_min = data.get("hotel_budget_min", 300)
    hotel_budget_max = data.get("hotel_budget_max", 500)
    if not goal:
        raise HTTPException(400, "请输入目的地描述")
    if len(goal) > 500:
        raise HTTPException(400, "目的地描述过长，请控制在500字以内")
    task_id = uuid.uuid4().hex[:12]
    _store_task(task_id, goal)
    # Run in background thread (non-blocking)
    thread = threading.Thread(
        target=_run_pipeline_task,
        args=(task_id, goal, enabled_steps, people, budget, hotel_budget_min, hotel_budget_max),
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
        raise HTTPException(404, "任务不存在")
    if task["status"] != "completed":
        raise HTTPException(400, f"任务未完成，当前状态: {task['status']}")
    brochure_html = task.get("result", {}).get("brochure", "")
    if not brochure_html:
        return HTMLResponse("<h2>手册生成中，请稍后查看</h2>")
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
async def stream_progress(task_id: str):
    """SSE endpoint: real-time progress via Server-Sent Events."""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    if task["status"] == "completed":
        async def _done():
            yield f"data: {json.dumps({'message': '✅ 任务已完成', 'done': True})}\n\n"
        return StreamingResponse(_done(), media_type="text/event-stream")

    if task["status"] == "failed":
        err_msg = task.get("error", "")
        async def _failed():
            yield f"data: {json.dumps({'message': '❌ 失败: ' + err_msg, 'done': True})}\n\n"
        return StreamingResponse(_failed(), media_type="text/event-stream")

    seen = len(json.loads(task.get("progress", "[]")))

    async def _stream():
        nonlocal seen
        yield f"data: {json.dumps({'message': '⏳ 任务已提交，等待执行...', 'done': False})}\n\n"
        while True:
            await asyncio.sleep(0.5)
            task = _get_task(task_id)
            if not task:
                yield f"data: {json.dumps({'message': '❌ 任务已消失', 'done': True})}\n\n"
                break
            try:
                progress = json.loads(task.get("progress", "[]"))
            except (json.JSONDecodeError, TypeError):
                progress = []
            if len(progress) > seen:
                for p in progress[seen:]:
                    yield f"data: {json.dumps({'message': p.get('message', ''), 'step': p.get('step', ''), 'pct': p.get('pct', 0), 'done': False})}\n\n"
                seen = len(progress)
            if task["status"] == "completed":
                yield f"data: {json.dumps({'message': '✅ 任务完成', 'done': True})}\n\n"
                break
            if task["status"] == "failed":
                yield f"data: {json.dumps({'message': '❌ 失败: ' + task.get('error', ''), 'done': True})}\n\n"
                break
    return StreamingResponse(_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    print("🌍 AI旅行攻略 Web App 启动中...")
    print("   访问地址: http://localhost:8080")
    print("   按 Ctrl+C 停止")
    print(f"   SQLite 数据库: {DB_PATH}")
    uvicorn.run(app, host="127.0.0.1", port=8080, timeout_keep_alive=600)
