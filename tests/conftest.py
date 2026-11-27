# -*- coding: utf-8 -*-
"""
pytest 全局夹具：测试离线化
===========================
- 默认禁止对非本机地址的 socket 连接（防止测试意外访问真实外部 API）。
- 默认把图片抓取入口 `utils.image_fetcher.get_photos` 替换为"无图"（返回 []，
  与真实抓取无结果时的返回值一致），并把图片抓取/手册渲染里的 time.sleep 置空。
- 设置环境变量 `TR_TESTS_ALLOW_NETWORK=1` 可跳过以上两项（留给手动集成测试）。

隔离（模块导入时就生效，早于任何 utils/webapp 导入）：
- 所有运行时写入（偏好、任务库、缓存、产物）引到本次会话的临时目录，
  通过 TRAVEL_STATE_DIR / TRAVEL_OUTPUTS_DIR（见 utils/config.py）。
- 清掉代理环境变量并让 urllib 不读系统代理：本机代理（如 127.0.0.1:7890）
  会让外部请求从"本机地址"绕过下面的网络拦截。
- API Key 一律设为假值，测试永远不读本机 .env 里的真 Key。
- 禁止调用 opencli / flyai 命令行（它们会驱动本机 Chrome 或访问外网）。
- 会话结束时检查项目自己的 data/ 和 outputs/ 没被改动，被改动则判失败。
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------- 写入隔离：临时目录 ----------
_TMP_ROOT = tempfile.mkdtemp(prefix="travel-tests-")
os.environ["TRAVEL_STATE_DIR"] = os.path.join(_TMP_ROOT, "data")
os.environ["TRAVEL_OUTPUTS_DIR"] = os.path.join(_TMP_ROOT, "outputs")
os.makedirs(os.environ["TRAVEL_STATE_DIR"], exist_ok=True)
os.makedirs(os.environ["TRAVEL_OUTPUTS_DIR"], exist_ok=True)

# ---------- 假 Key：不读本机 .env ----------
_DUMMY_KEYS = (
    "DEEPSEEK_API_KEY", "AMAP_KEY", "OPENAI_API_KEY", "QWEN_API_KEY",
    "VISION_API_KEY", "UNSPLASH_ACCESS_KEY", "PIXABAY_API_KEY",
)
for _k in _DUMMY_KEYS:
    os.environ[_k] = "test-dummy"


def _network_allowed():
    return os.environ.get("TR_TESTS_ALLOW_NETWORK") == "1"


# ---------- 代理：不让外部请求经本机代理绕过拦截 ----------
if not _network_allowed():
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(_k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    import urllib.request as _urllib_request

    # Windows 上 urllib 还会读注册表里的系统代理，这里一并关掉
    _urllib_request.getproxies = lambda: {}

# ---------- 禁止调用 opencli / flyai ----------
_BLOCKED_CLIS = {"opencli", "flyai"}
_RealPopen = subprocess.Popen


def _cli_name(args):
    first = args
    if isinstance(args, (list, tuple)):
        first = args[0] if args else ""
    elif isinstance(args, str):
        first = args.strip().split(" ", 1)[0].strip("\"'")
    # 统一按 / 切分，Windows 路径（C:\\npm\\opencli.cmd）在任何系统上都能识别
    name = os.fspath(first).replace("\\", "/").rsplit("/", 1)[-1].lower()
    for ext in (".cmd", ".exe", ".ps1", ".bat"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    return name


class _GuardedPopen(_RealPopen):
    def __init__(self, args, *a, **k):
        if _cli_name(args) in _BLOCKED_CLIS:
            raise FileNotFoundError(f"{_cli_name(args)} is disabled in tests")
        super().__init__(args, *a, **k)


subprocess.Popen = _GuardedPopen


# ---------- 会话结束时确认项目的 data/ 和 outputs/ 未被改动 ----------
_WATCHED_DIRS = ("data", "outputs")


def _snapshot():
    snap = {}
    for d in _WATCHED_DIRS:
        base = os.path.join(_PROJECT_ROOT, d)
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for f in files:
                path = os.path.join(root, f)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                snap[os.path.relpath(path, _PROJECT_ROOT)] = (st.st_size, st.st_mtime_ns)
    return snap


_SNAPSHOT_BEFORE = None


def pytest_sessionstart(session):
    global _SNAPSHOT_BEFORE
    _SNAPSHOT_BEFORE = _snapshot()


def pytest_sessionfinish(session, exitstatus):
    if _SNAPSHOT_BEFORE is not None:
        after = _snapshot()
        changed = sorted(
            set(_SNAPSHOT_BEFORE) ^ set(after)
            | {k for k in set(_SNAPSHOT_BEFORE) & set(after) if _SNAPSHOT_BEFORE[k] != after[k]}
        )
        if changed:
            shown = "\n  ".join(changed[:20])
            more = f"\n  ... 共 {len(changed)} 个" if len(changed) > 20 else ""
            sys.stderr.write(f"\n[conftest] 测试改动了项目里的 data/ 或 outputs/：\n  {shown}{more}\n")
            session.exitstatus = 1
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


# 依赖真实 sleep 做耗时断言的测试模块（不对 amap_api 的 sleep 置空）
_REAL_SLEEP_MODULES = {"test_amap_client"}

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0", ""}


def _is_local_address(address):
    """address 形如 (host, port) / (host, port, flowinfo, scope) / 其他（如 AF_UNIX 路径）。"""
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "ignore")
        return str(host).lower() in _LOCAL_HOSTS
    # 非 (host, port) 形式（如 Unix socket 路径）不属于对外网络
    return not isinstance(address, (tuple, list))


_REAL_SLEEP = time.sleep
# 这些模块里的 time.sleep 置空（按调用方模块名判断，而不是替换模块属性：
# test_amap_client 会把 utils.amap_api 从 sys.modules 删除重导入，按对象替换会漏掉旧模块对象）
_NO_SLEEP_CALLERS = {"utils.image_fetcher", "utils.brochure", "utils.amap_api"}


def _make_sleep(blocked):
    def _sleep(seconds=0, *a, **k):
        caller = sys._getframe(1).f_globals.get("__name__", "")
        if caller in blocked:
            return None
        return _REAL_SLEEP(seconds, *a, **k)
    return _sleep


@pytest.fixture(autouse=True, scope="session")
def _block_external_network():
    if _network_allowed():
        yield
        return

    mp = pytest.MonkeyPatch()
    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def guarded_connect(self, address):
        if not _is_local_address(address):
            raise OSError("network disabled in tests")
        return real_connect(self, address)

    def guarded_create_connection(address, *args, **kwargs):
        if not _is_local_address(address):
            raise OSError("network disabled in tests")
        return real_create_connection(address, *args, **kwargs)

    mp.setattr(socket.socket, "connect", guarded_connect)
    mp.setattr(socket, "create_connection", guarded_create_connection)
    try:
        yield
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def _offline_image_fetcher(monkeypatch, request):
    if _network_allowed():
        yield
        return

    import utils.image_fetcher as image_fetcher

    monkeypatch.setattr(image_fetcher, "get_photos", lambda *a, **k: [])
    # 网络被禁用后高德请求失败会触发"重试退避 sleep"，图片抓取也有抖动 sleep，大幅拖慢测试，这里置空。
    # 例外：test_amap_client 里的限流用例依赖真实 sleep 做耗时断言。
    blocked = set(_NO_SLEEP_CALLERS)
    if request.module.__name__.split(".")[-1] in _REAL_SLEEP_MODULES:
        blocked.discard("utils.amap_api")
    monkeypatch.setattr(time, "sleep", _make_sleep(blocked))
    yield
