# -*- coding: utf-8 -*-
"""PR4：网页端默认只本机访问；免 Key 图片源开关。"""
import importlib

import pytest

from utils import config, image_fetcher


def _reload_webapp_config(monkeypatch, host=None):
    monkeypatch.delitem(config._DOTENV, "HOST", raising=False)
    if host is None:
        monkeypatch.delenv("HOST", raising=False)
    else:
        monkeypatch.setenv("HOST", host)
    import webapp.config as wcfg
    return importlib.reload(wcfg)


@pytest.fixture(autouse=True)
def _restore_webapp_config():
    yield
    import webapp.config as wcfg
    importlib.reload(wcfg)


def test_default_host_is_localhost(monkeypatch):
    assert _reload_webapp_config(monkeypatch).HOST == "127.0.0.1"


def test_host_can_be_opened_to_lan(monkeypatch):
    assert _reload_webapp_config(monkeypatch, "0.0.0.0").HOST == "0.0.0.0"


def _names():
    return [n for n, _ in image_fetcher._engine_chain()]


def test_free_sources_on_by_default(monkeypatch):
    monkeypatch.delenv("IMAGE_FREE_SOURCES", raising=False)
    monkeypatch.delitem(config._DOTENV, "IMAGE_FREE_SOURCES", raising=False)
    assert _names() == ["Gaode", "Wikimedia", "360", "Baidu", "Bing", "Pixabay", "Unsplash"]


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no"])
def test_free_sources_can_be_turned_off(monkeypatch, value):
    monkeypatch.setenv("IMAGE_FREE_SOURCES", value)
    assert _names() == ["Gaode", "Wikimedia", "Pixabay", "Unsplash"]


def test_user_agent_has_no_agent_name():
    src = open(image_fetcher.__file__, encoding="utf-8").read()
    assert "hermes" not in src
