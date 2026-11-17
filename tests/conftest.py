# -*- coding: utf-8 -*-
"""
pytest 全局夹具：测试离线化
===========================
- 默认禁止对非本机地址的 socket 连接（防止测试意外访问真实外部 API）。
- 默认把图片抓取入口 `utils.image_fetcher.get_photos` 替换为"无图"（返回 []，
  与真实抓取无结果时的返回值一致），并把图片抓取/手册渲染里的 time.sleep 置空。
- 设置环境变量 `TR_TESTS_ALLOW_NETWORK=1` 可跳过以上两项（留给手动集成测试）。
"""
import os
import socket
import sys
import time

import pytest


def _network_allowed():
    return os.environ.get("TR_TESTS_ALLOW_NETWORK") == "1"


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
