# -*- coding: utf-8 -*-
"""conftest 的离线保护自检：外部地址被拒绝、本机地址放行、图片抓取返回无图。"""
import os
import socket

import pytest


@pytest.mark.skipif(os.environ.get("TR_TESTS_ALLOW_NETWORK") == "1", reason="network allowed")
def test_external_connect_blocked():
    with pytest.raises(OSError, match="network disabled in tests"):
        socket.create_connection(("example.com", 80), timeout=1)
    s = socket.socket()
    try:
        with pytest.raises(OSError, match="network disabled in tests"):
            s.connect(("93.184.216.34", 80))
    finally:
        s.close()


@pytest.mark.skipif(os.environ.get("TR_TESTS_ALLOW_NETWORK") == "1", reason="network allowed")
def test_localhost_not_blocked_by_guard():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        c = socket.create_connection(("127.0.0.1", srv.getsockname()[1]), timeout=2)
        c.close()
    finally:
        srv.close()


@pytest.mark.skipif(os.environ.get("TR_TESTS_ALLOW_NETWORK") == "1", reason="network allowed")
def test_image_fetcher_returns_no_photos():
    from utils.image_fetcher import get_photos
    assert get_photos("外滩", "上海", "sight") == []
