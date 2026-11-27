import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Project root path
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Static files and templates directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
from utils.config import STATE_DIR, OUTPUTS_DIR as _OUTPUTS_DIR  # noqa: E402

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
_CORS_ENV = os.environ.get("CORS_ORIGINS", "")
if _CORS_ENV == "*" and os.environ.get("CORS_ALLOW_ALL") == "1":
    CORS_ORIGINS = ["*"]
elif _CORS_ENV and _CORS_ENV != "*":
    CORS_ORIGINS = [o.strip() for o in _CORS_ENV.split(",") if o.strip()]
else:
    CORS_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]

