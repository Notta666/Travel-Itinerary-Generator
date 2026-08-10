import threading
import json
import os
import logging
from fastapi import HTTPException
from webapp.db import update_task, get_task
from webapp.config import PROJECT

logger = logging.getLogger("webapp")

# Aliases to keep the original method bodies completely unchanged
_update_task = update_task
_get_task = get_task

_cancel_flags = {}  # task_id -> threading.Event
_cancel_lock = threading.Lock()


class CancelledError(Exception):
    """Raised when a task is cancelled by the user."""
    pass


_task_start_times = {}
_last_pct = {}

def _cleanup_stale_tasks():
    import time
    now = time.time()
    with _cancel_lock:
        for tid in list(_cancel_flags.keys()):
            if now - _task_start_times.get(tid, now) > 1800:
                _cancel_flags.pop(tid, None)
                _task_start_times.pop(tid, None)
                _last_pct.pop(tid, None)

def _is_cancelled(task_id):
    """Check if a cancel has been requested for this task."""
    with _cancel_lock:
        evt = _cancel_flags.get(task_id)
        return evt is not None and evt.is_set()


async def cancel_task(task_id: str):
    """Cancel a running task."""
    _cleanup_stale_tasks()
    with _cancel_lock:
        task = get_task(task_id)
        if not task:
            raise HTTPException(404, "任务不存在")
        if task["status"] not in ("pending", "running"):
            raise HTTPException(400, f"任务状态为 {task['status']}，无法取消")
        evt = _cancel_flags.get(task_id)
        if evt is not None:
            evt.set()
            return {"status": "cancelling"}
        else:
            # Task hasn't started its thread yet; update status directly
            update_task(task_id, status="cancelled", error="用户已取消规划")
            return {"status": "cancelled"}


def _run_pipeline_task(task_id, goal_text, enabled_steps=None, people=None, budget=None, hotel_budget_min=300, hotel_budget_max=500, user_prefs=None, days=None, opencli_ok=True):
    """Run the pipeline in a background thread with SSE progress."""
    try:
        from pipeline.run_pipeline import _parse_goal, run_pipeline
        _update_task(task_id, status="running", progress="[]")

        # Register cancel flag
        with _cancel_lock:
            cancel_evt = threading.Event()
            _cancel_flags[task_id] = cancel_evt
            import time
            _task_start_times[task_id] = time.time()

        # 注册后复查 DB 状态，若已 cancelled 直接退出
        task_info = get_task(task_id)
        if task_info and task_info.get("status") == "cancelled":
            _update_task(task_id, status="cancelled", error="用户已取消规划")
            return

        def _progress(step, msg, pct):
            # Check cancellation before reporting progress
            if _is_cancelled(task_id):
                raise CancelledError("用户已取消规划")
            prev = _last_pct.get(task_id, -100)
            if pct - prev >= 5 or "完成" in msg or "失败" in msg or pct == 100:
                # 追加进度并写入数据库
                try:
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
                    _last_pct[task_id] = pct
                except Exception as e:
                    logger.warning(f"更新任务进度失败 (task_id={task_id}): {e}")

        # Parse goal
        parsed_city, parsed_days, pois, prefs = _parse_goal(goal_text)

        city = parsed_city
        final_days = int(days) if days is not None and str(days).isdigit() and int(days) > 0 else parsed_days

        # Override with Web UI user inputs
        ui_people = people if people is not None else 2

        if budget is not None:
            ui_budget_str = f"共{budget}元"
        else:
            total_est = 1500 * ui_people * max(final_days or 2, 1)
            ui_budget_str = f"共{total_est}元"

        prefs["people_count"] = ui_people
        prefs["budget"] = ui_budget_str

        # 酒店每晚预算区间（默认300~500）
        prefs["hotel_budget_min"] = hotel_budget_min
        prefs["hotel_budget_max"] = hotel_budget_max
        # 数据来源标注：小红书可用则走真实调研，否则内置推荐库（用于产物标注）
        prefs["research_source"] = "xiaohongshu" if opencli_ok else "default_pois"

        # 用户偏好（复选框选择）
        if user_prefs:
            prefs["user_prefs"] = user_prefs

        # Set customized step list if valid list/set
        if enabled_steps is not None and isinstance(enabled_steps, (list, tuple, set)):
            prefs["enabled_steps"] = enabled_steps

        # Run pipeline with progress_callback
        context = run_pipeline(city, final_days, manual_pois=pois, prefs=prefs, progress_callback=_progress, cancel_event=cancel_evt)

        # Collect results
        result = {
            "city": city,
            "days": final_days,
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
        tb_str = traceback.format_exc()
        logger.exception(f"任务 {task_id} 执行异常: {e}")
        _update_task(task_id, status="failed", error="任务执行失败，请查看服务日志",
                     traceback=tb_str)
    finally:
        with _cancel_lock:
            _cancel_flags.pop(task_id, None)
            _task_start_times.pop(task_id, None)
            _last_pct.pop(task_id, None)
