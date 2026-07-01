import os

# Project root path
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Static files and templates directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# Output directory for brochures
OUTPUTS_DIR = os.path.join(PROJECT, "outputs")

# Data directory for database
DATA_DIR = os.path.join(PROJECT, "data")
DB_PATH = os.path.join(DATA_DIR, "tasks.db")

# CORS origins (environment configurable for security)
# Default: localhost only. Set to "*" to allow all origins (development only)
# Format: comma-separated list, e.g. "http://localhost:8080,http://127.0.0.1:8080"
_CORS_ENV = os.environ.get("CORS_ORIGINS", "")
if _CORS_ENV and _CORS_ENV != "*":
    CORS_ORIGINS = [o.strip() for o in _CORS_ENV.split(",") if o.strip()]
elif _CORS_ENV == "*":
    CORS_ORIGINS = ["*"]
else:
    CORS_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]
