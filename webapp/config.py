import os

# 配置统一由 utils/config 读取（环境变量优先，其次项目根目录的 .env）
from utils.config import get_setting
from utils.paths import PROJECT_ROOT as PROJECT, STATE_DIR, OUTPUTS_DIR as _OUTPUTS_DIR

# Static files and templates directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# Output directory for brochures (TRAVEL_OUTPUTS_DIR 可覆盖，默认 outputs/)
OUTPUTS_DIR = _OUTPUTS_DIR

# Data directory for database (TRAVEL_STATE_DIR 可覆盖，默认 data/)
DATA_DIR = STATE_DIR
DB_PATH = os.path.join(DATA_DIR, "tasks.db")

# Ensure required directories exist
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# CORS origins (environment configurable for security)
# Default: localhost only. Set CORS_ORIGINS="*" and CORS_ALLOW_ALL="1" to allow all origins (development only)
# Format: comma-separated list, e.g. "http://localhost:8080,http://127.0.0.1:8080"
_CORS_ENV = get_setting("CORS_ORIGINS")
if _CORS_ENV == "*" and get_setting("CORS_ALLOW_ALL") == "1":
    CORS_ORIGINS = ["*"]
elif _CORS_ENV and _CORS_ENV != "*":
    CORS_ORIGINS = [o.strip() for o in _CORS_ENV.split(",") if o.strip()]
else:
    CORS_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]

