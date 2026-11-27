# -*- coding: utf-8 -*-
"""测试隔离自检：写入路径都在临时目录，CLI 被禁用，Key 是假值。"""
import os
import subprocess

import pytest

from utils import config


def _under(path, root):
    return os.path.abspath(path).startswith(os.path.abspath(root) + os.sep) or \
        os.path.abspath(path) == os.path.abspath(root)


def test_state_and_outputs_point_to_temp():
    state = os.environ["TRAVEL_STATE_DIR"]
    outputs = os.environ["TRAVEL_OUTPUTS_DIR"]
    assert config.STATE_DIR == state
    assert config.OUTPUTS_DIR == outputs
    assert not _under(state, config.BASE_DIR)
    assert not _under(outputs, config.BASE_DIR)


def test_module_write_paths_are_isolated():
    from utils import user_prefs, image_fetcher, flyai_api
    import webapp.config as wcfg

    state = os.environ["TRAVEL_STATE_DIR"]
    assert _under(user_prefs.PREFS_FILE, state)
    assert _under(image_fetcher.CACHE_DIR, state)
    assert _under(flyai_api._default_cache_dir(), state)
    assert _under(wcfg.DB_PATH, state)
    assert wcfg.OUTPUTS_DIR == os.environ["TRAVEL_OUTPUTS_DIR"]


def test_keys_never_come_from_dotenv():
    # 环境变量里总有假 Key（conftest 设 test-dummy，个别测试模块改成 test-key），
    # 所以 _load_env_key 永远不会去读本机 .env
    for k in ("AMAP_KEY", "DEEPSEEK_API_KEY"):
        assert os.environ[k] in ("test-dummy", "test-key")
        assert config._load_env_key(k) == os.environ[k]


@pytest.mark.parametrize("cmd", [["opencli", "profile", "list"], ["flyai", "--help"],
                                 [r"C:\npm\opencli.cmd", "x"]])
def test_external_clis_blocked(cmd):
    with pytest.raises(FileNotFoundError):
        subprocess.run(cmd, capture_output=True)
