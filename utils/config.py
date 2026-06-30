"""
统一配置管理
=============
集中管理所有 API Key 加载与环境配置，消除重复代码。

使用方式:
    from utils.config import DEEPSEEK_API_KEY, AMAP_KEY, BASE_DIR
"""
import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env_key(key_name: str) -> str:
    """从环境变量或 .env 文件加载 API Key"""
    val = os.environ.get(key_name, "")
    if val:
        return val
    env_path = os.path.join(_BASE_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key_name}="):
                        v = line.split("=", 1)[1].strip().strip("\"'")
                        if v and v != "***":
                            return v
        except Exception:
            pass
    return ""


DEEPSEEK_API_KEY = _load_env_key("DEEPSEEK_API_KEY")
AMAP_KEY = _load_env_key("AMAP_KEY")

# 可选：无水印图片源 API Keys（不配置则自动跳过）
UNSPLASH_ACCESS_KEY = _load_env_key("UNSPLASH_ACCESS_KEY")     # https://unsplash.com/developers
PIXABAY_API_KEY = _load_env_key("PIXABAY_API_KEY")              # https://pixabay.com/api/docs/

BASE_DIR = _BASE_DIR
