"""
项目路径集中定义
================
项目根、只读参考数据、可写状态与产物的位置都在这里，其他模块从这里取，
不再各自用 dirname 往上数。

可写目录可用环境变量改到别处（默认就在项目里，与以往一致）：
- TRAVEL_STATE_DIR：偏好、任务库、缓存（默认 <项目>/data）
- TRAVEL_OUTPUTS_DIR：手册、行程等产物（默认 <项目>/outputs）

只读参考数据（references、default_pois.json、custom_images）始终在项目 data/ 下。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只读参考数据（随仓库发布）
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
REFERENCES_DIR = os.path.join(DATA_DIR, "references")
DEFAULT_POIS_PATH = os.path.join(DATA_DIR, "default_pois.json")
CUSTOM_IMAGES_DIR = os.path.join(DATA_DIR, "custom_images")

# 可写目录
STATE_DIR = os.environ.get("TRAVEL_STATE_DIR") or DATA_DIR
OUTPUTS_DIR = os.environ.get("TRAVEL_OUTPUTS_DIR") or os.path.join(PROJECT_ROOT, "outputs")
CACHE_DIR = os.path.join(STATE_DIR, "cache")
IMAGE_CACHE_DIR = os.path.join(STATE_DIR, "image_cache")

ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
