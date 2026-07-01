import threading
import json
import os
from fastapi import HTTPException
from webapp.db import update_task, get_task
from webapp.config import PROJECT

# Aliases to keep the original method bodies completely unchanged
_update_task = update_task
_get_task = get_task

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


async def cancel_task(task_id: str):
    """Cancel a running task."""
    task = get_task(task_id)
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
            update_task(task_id, status="cancelled", error="用户已取消规划")
            return {"status": "cancelled"}


def _run_pipeline_task(task_id, goal_text, enabled_steps=None, people=None, budget=None, hotel_budget_min=300, hotel_budget_max=500):
    """Run the pipeline in a background thread with SSE progress."""
    try:
        from pipeline.run_pipeline import _parse_goal, run_pipeline
        _update_task(task_id, status="running", progress="[]")

        # Register cancel flag
        with _cancel_lock:
            cancel_evt = threading.Event()
            _cancel_flags[task_id] = cancel_evt

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

        # 酒店每晚预算区间（默认300~500）
        prefs["hotel_budget_min"] = hotel_budget_min
        prefs["hotel_budget_max"] = hotel_budget_max

        # Set customized step list
        if enabled_steps is not None:
            prefs["enabled_steps"] = enabled_steps

        # Run pipeline with progress_callback
        context = run_pipeline(city, days, manual_pois=pois, prefs=prefs, progress_callback=_progress, cancel_event=cancel_evt)

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
