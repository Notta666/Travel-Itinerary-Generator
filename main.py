"""ASGI 入口转发 — 供 `uvicorn main:app` 从项目根目录启动 webapp。

webapp/main.py 自注入 sys.path，此处仅做模块转发，保持单入口。
"""
from webapp.main import app

__all__ = ["app"]
