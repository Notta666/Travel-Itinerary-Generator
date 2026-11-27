# -*- coding: utf-8 -*-
"""路径集中（utils/paths）与 .env 单一读法（utils/config）。"""
import logging
import os

from utils import config, paths


def test_project_root_is_repo_root():
    assert os.path.isfile(os.path.join(paths.PROJECT_ROOT, "utils", "paths.py"))
    assert config.BASE_DIR == paths.PROJECT_ROOT
    assert paths.ENV_FILE == os.path.join(paths.PROJECT_ROOT, ".env")


def test_readonly_data_stays_in_repo():
    assert paths.DEFAULT_POIS_PATH == os.path.join(paths.PROJECT_ROOT, "data", "default_pois.json")
    assert paths.REFERENCES_DIR == os.path.join(paths.PROJECT_ROOT, "data", "references")
    assert os.path.isdir(paths.REFERENCES_DIR)


def test_writable_dirs_follow_env():
    assert paths.STATE_DIR == os.environ["TRAVEL_STATE_DIR"]
    assert paths.OUTPUTS_DIR == os.environ["TRAVEL_OUTPUTS_DIR"]
    assert paths.CACHE_DIR == os.path.join(paths.STATE_DIR, "cache")
    assert config.STATE_DIR == paths.STATE_DIR and config.OUTPUTS_DIR == paths.OUTPUTS_DIR


def test_dotenv_first_value_wins_and_warns_on_duplicates(tmp_path, caplog):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nAMAP_KEY=first\nDEEPSEEK_API_KEY='ds'\nAMAP_KEY=second\nOPENAI_API_KEY=***\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="utils.config"):
        values = config._read_dotenv(str(env))
    assert values["AMAP_KEY"] == "first"
    assert values["DEEPSEEK_API_KEY"] == "ds"
    assert "OPENAI_API_KEY" not in values, "*** 是占位符"
    warnings = [r.getMessage() for r in caplog.records]
    assert any("AMAP_KEY" in m and "2" in m for m in warnings)
    assert not any("first" in m or "second" in m for m in warnings), "警告里不能带值"
    assert env.read_text(encoding="utf-8").count("AMAP_KEY") == 2, "不改 .env"


def test_dotenv_placeholder_then_real_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AMAP_KEY=***\nAMAP_KEY=real\n", encoding="utf-8")
    assert config._read_dotenv(str(env))["AMAP_KEY"] == "real"


def test_get_setting_env_over_dotenv(monkeypatch):
    monkeypatch.setitem(config._DOTENV, "SOME_SETTING", "from-dotenv")
    assert config.get_setting("SOME_SETTING") == "from-dotenv"
    monkeypatch.setenv("SOME_SETTING", "from-env")
    assert config.get_setting("SOME_SETTING") == "from-env"
    assert config.get_setting("MISSING_SETTING_X", "dflt") == "dflt"


def test_no_python_dotenv_dependency():
    src = open(os.path.join(paths.PROJECT_ROOT, "webapp", "config.py"), encoding="utf-8").read()
    assert "dotenv" not in src
