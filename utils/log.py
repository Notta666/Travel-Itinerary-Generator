"""统一日志：LOG_FORMAT=json|text（默认 text，保持 CLI 观感）。

- text：仅输出消息本体（与原 print 观感一致），写 stdout。
- json：每行一个 JSON，含 ts, level, logger, msg, task_id, step, elapsed_ms。
- task_id / step 通过 contextvars 传递，可用 set_task_id() / log_step() 设置。
"""
import contextvars
import json
import logging
import sys
import time
from contextlib import contextmanager

from utils.config import get_setting

_task_id = contextvars.ContextVar("task_id", default=None)
_step = contextvars.ContextVar("step", default=None)
_step_t0 = contextvars.ContextVar("step_t0", default=None)


def set_task_id(task_id):
    """设置当前上下文的 task_id，返回 token（可用于 reset）。"""
    return _task_id.set(task_id)


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        t0 = _step_t0.get()
        elapsed = getattr(record, "elapsed_ms", None)
        if elapsed is None and t0 is not None:
            elapsed = int((time.monotonic() - t0) * 1000)
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
            + ".%03d" % int(record.msecs),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "task_id": _task_id.get(),
            "step": _step.get(),
            "elapsed_ms": elapsed,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _make_formatter():
    if get_setting("LOG_FORMAT", "text").strip().lower() == "json":
        return _JsonFormatter()
    return logging.Formatter("%(message)s")


def get_logger(name):
    """返回已配置的 logger（幂等；handler 直接挂在该 logger 上，不向 root 传播）。"""
    logger = logging.getLogger(name)
    if not getattr(logger, "_travel_configured", False):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_make_formatter())
        logger.addHandler(handler)
        logger.setLevel(get_setting("LOG_LEVEL", "INFO").upper())
        logger.propagate = False
        logger._travel_configured = True
    return logger


@contextmanager
def log_step(step, logger=None):
    """设置当前 step 并在退出时输出该步骤耗时（elapsed_ms）。"""
    lg = logger or get_logger("travel_pipeline")
    tok_s = _step.set(step)
    tok_t = _step_t0.set(time.monotonic())
    t0 = time.monotonic()
    try:
        yield
    finally:
        ms = int((time.monotonic() - t0) * 1000)
        lg.info("步骤完成: %s 耗时 %dms", step, ms, extra={"elapsed_ms": ms})
        _step.reset(tok_s)
        _step_t0.reset(tok_t)
