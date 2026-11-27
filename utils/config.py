"""
统一配置管理
=============
集中管理所有 API Key 加载与环境配置，消除重复代码。

使用方式:
    from utils.config import DEEPSEEK_API_KEY, AMAP_KEY, BASE_DIR
"""
import logging
import os

from utils.paths import ENV_FILE, PROJECT_ROOT as _BASE_DIR, STATE_DIR, OUTPUTS_DIR  # noqa: F401

_logger = logging.getLogger(__name__)
_PLACEHOLDERS = {"", "***"}


def _read_dotenv(path=ENV_FILE):
    """读取 .env，返回 {键: 值}。

    同一个键出现多次时取第一条有效值（与以往一致），并打一条警告提示重复；
    不会改动 .env 文件本身。值 "***" 视为占位符，忽略。
    """
    values, counts = {}, {}
    if not os.path.exists(path):
        return values
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, v = line.split("=", 1)
                key = key.strip()
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                v = v.strip().strip("\"'")
                counts[key] = counts.get(key, 0) + 1
                if key not in values and v not in _PLACEHOLDERS:
                    values[key] = v
    except Exception:
        return {}
    for key, n in counts.items():
        if n > 1:
            _logger.warning(".env 里 %s 出现了 %d 次，使用第一条有效值", key, n)
    return values


_DOTENV = _read_dotenv()


def _load_env_key(key_name: str) -> str:
    """先看环境变量，再看 .env；都没有返回空字符串。"""
    val = os.environ.get(key_name, "")
    if val:
        return val
    return _DOTENV.get(key_name, "")


def get_setting(name: str, default: str = "") -> str:
    """读取一项配置（环境变量优先，其次 .env），没有时返回 default。"""
    return _load_env_key(name) or default


DEEPSEEK_API_KEY = _load_env_key("DEEPSEEK_API_KEY")
AMAP_KEY = _load_env_key("AMAP_KEY")
OPENAI_API_KEY = _load_env_key("OPENAI_API_KEY")
QWEN_API_KEY = _load_env_key("QWEN_API_KEY")

# 多模态视觉模型配置 (任意兼容 OpenAI 格式的模型，如 gpt-4o, qwen-vl-max 等)
VISION_API_KEY = _load_env_key("VISION_API_KEY") or OPENAI_API_KEY
VISION_API_BASE = _load_env_key("VISION_API_BASE") or "https://api.openai.com/v1"
VISION_MODEL = _load_env_key("VISION_MODEL") or "gpt-4o"

# 可选：无水印图片源 API Keys（不配置则自动跳过）
UNSPLASH_ACCESS_KEY = _load_env_key("UNSPLASH_ACCESS_KEY")     # https://unsplash.com/developers
PIXABAY_API_KEY = _load_env_key("PIXABAY_API_KEY")              # https://pixabay.com/api/docs/

BASE_DIR = _BASE_DIR

# 可写目录（STATE_DIR、OUTPUTS_DIR）见 utils/paths.py，这里只是为旧代码保留同名导出。
