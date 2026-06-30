"""
Travel-Itinerary-Generator · Web App
=====================================
FastAPI 后端，支持异步任务模式：
  POST   /generate    → 提交任务，返回 task_id
  GET    /status/{id}  → 查询任务状态
  GET    /result/{id}  → 获取生成结果（brochure HTML / 报告）
  GET    /download/{id} → 下载手册 HTML 文件

Changes in Phase 5:
  - Tasks are persisted in SQLite (data/tasks.db) instead of in-memory dict
  - Frontend HTML/CSS/JS externalized to webapp/templates/ and webapp/static/
  - Uses Jinja2Templates for template rendering
"""
import sys, os, json, uuid, time, threading, shutil, glob, asyncio, sqlite3
import datetime as _dt

# Ensure project root is importable
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI旅行攻略", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Output directory for brochure files
OUTPUTS_DIR = os.path.join(PROJECT, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# Data directory for SQLite DB
DATA_DIR = os.path.join(PROJECT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "tasks.db")


# ====================================================================
# SQLite Task Store
# ====================================================================

def _get_db():
    """Get a thread-safe SQLite connection."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    """Create the tasks table on startup."""
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                goal TEXT DEFAULT '',
                created REAL NOT NULL,
                updated REAL DEFAULT NULL,
                result TEXT DEFAULT NULL,
                error TEXT DEFAULT NULL,
                traceback TEXT DEFAULT NULL,
                brochure_path TEXT DEFAULT NULL,
                progress TEXT DEFAULT '[]'
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _task_to_dict(row):
    """Convert a sqlite3.Row to a plain dict, parsing JSON result field."""
    if row is None:
        return None
    d = dict(row)
    if d.get("result") and isinstance(d["result"], str):
        try:
            d["result"] = json.loads(d["result"])
        except (json.JSONDecodeError, TypeError):
            d["result"] = {}
    if d.get("result") is None:
        d["result"] = {}
    return d


def _store_task(task_id, goal):
    """Insert a new task record."""
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO tasks (id, status, goal, created) VALUES (?, ?, ?, ?)",
            (task_id, "pending", goal, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _update_task(task_id, **fields):
    """Update arbitrary fields on a task."""
    if not fields:
        return
    fields["updated"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values())
    conn = _get_db()
    try:
        # Serialize result to JSON if present
        if "result" in fields and isinstance(fields["result"], dict):
            vals[list(fields.keys()).index("result")] = json.dumps(fields["result"], ensure_ascii=False)
        conn.execute(
            f"UPDATE tasks SET {sets} WHERE id = ?",
            vals + [task_id],
        )
        conn.commit()
    finally:
        conn.close()


def _get_task(task_id):
    """Retrieve a single task by ID."""
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_to_dict(row)
    finally:
        conn.close()


_init_db()  # Create tables on module load


# ====================================================================
# Background pipeline runner
_cancel_flags = {}  # task_id -> threading.Event
_cancel_lock = threading.Lock()


class CancelledError(Exception):
    """Raised when a task is cancelled by the user."""
    pass


def _is_cancelled(task_id):
    """Check if a cancel has been requested for this task."""
    with _cancel_lock:
        evt = _cancel_flags.get(task_id)
        return evt is not None and evt.is_set()


def _run_pipeline_task(task_id, goal_text, enabled_steps=None, people=None, budget=None):
    """Run the pipeline in a background thread with SSE progress."""
    try:
        from pipeline.run_pipeline import _parse_goal, run_pipeline
        _update_task(task_id, status="running", progress="[]")

        # Register cancel flag
        with _cancel_lock:
            _cancel_flags[task_id] = threading.Event()

        def _progress(step, msg, pct):
            # Check cancellation before reporting progress
            if _is_cancelled(task_id):
                raise CancelledError("用户已取消规划")
            # 追加进度并写入数据库
            task = _get_task(task_id)
            if task and task.get("progress"):
                try:
                    prog = json.loads(task["progress"])
                except (json.JSONDecodeError, TypeError):
                    prog = []
            else:
                prog = []
            prog.append({"step": step, "message": msg, "pct": pct})
            _update_task(task_id, progress=json.dumps(prog, ensure_ascii=False))

        # Parse goal
        city, days, pois, prefs = _parse_goal(goal_text)

        # Override with Web UI user inputs
        ui_people = people if people is not None else 2

        if budget is not None:
            ui_budget_str = f"共{budget}元"
        else:
            total_est = 1500 * ui_people * max(days or 2, 1)
            ui_budget_str = f"共{total_est}元"

        prefs["people_count"] = ui_people
        prefs["budget"] = ui_budget_str

        # Set customized step list
        if enabled_steps is not None:
            prefs["enabled_steps"] = enabled_steps

        # Run pipeline with progress_callback
        context = run_pipeline(city, days, manual_pois=pois, prefs=prefs, progress_callback=_progress)

        # Collect results
        result = {
            "city": city,
            "days": days,
            "brochure": None,
            "report": None,
        }

        # Read brochure HTML
        if context.get("brochure_path") and os.path.exists(context["brochure_path"]):
            with open(context["brochure_path"], "r", encoding="utf-8") as f:
                result["brochure"] = f.read()
            result["brochure_path"] = context["brochure_path"]

        # Read report MD
        if context.get("report_path") and os.path.exists(context["report_path"]):
            with open(context["report_path"], "r", encoding="utf-8") as f:
                result["report"] = f.read()

        _update_task(task_id, status="completed", result=result,
                     brochure_path=result.get("brochure_path", ""))

    except CancelledError:
        _update_task(task_id, status="cancelled", error="用户已取消规划")
    except Exception as e:
        import traceback
        _update_task(task_id, status="failed", error=str(e),
                     traceback=traceback.format_exc())
    finally:
        # Clean up cancel flag
        with _cancel_lock:
            _cancel_flags.pop(task_id, None)


# ====================================================================
# Routes
# ====================================================================

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
    if not goal:
        raise HTTPException(400, "请输入目的地描述")
    task_id = uuid.uuid4().hex[:12]
    _store_task(task_id, goal)
    # Run in background thread (non-blocking)
    thread = threading.Thread(
        target=_run_pipeline_task,
        args=(task_id, goal, enabled_steps, people, budget),
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a running task."""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] not in ("pending", "running"):
        raise HTTPException(400, f"任务状态为 {task['status']}，无法取消")
    with _cancel_lock:
        evt = _cancel_flags.get(task_id)
        if evt is not None:
            evt.set()
            return {"status": "cancelling"}
        else:
            # Task hasn't started its thread yet; update status directly
            _update_task(task_id, status="cancelled", error="用户已取消规划")
            return {"status": "cancelled"}


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


# ====================================================================
# Main entry point
# ====================================================================

if __name__ == "__main__":
    import uvicorn
    print("🌍 AI旅行攻略 Web App 启动中...")
    print("   访问地址: http://localhost:8080")
    print("   按 Ctrl+C 停止")
    print(f"   SQLite 数据库: {DB_PATH}")
    uvicorn.run(app, host="0.0.0.0", port=8080, timeout_keep_alive=600)
