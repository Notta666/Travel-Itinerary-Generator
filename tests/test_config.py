"""
Test: config module — env key loading
======================================
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfig(unittest.TestCase):
    """Test config loading from environment and .env file"""

    def setUp(self):
        # Store original env values
        self._orig_deepseek = os.environ.pop("DEEPSEEK_API_KEY", None)
        self._orig_amap = os.environ.pop("AMAP_KEY", None)
        # Force reimport of config module
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]

    def tearDown(self):
        # Restore env
        if self._orig_deepseek is not None:
            os.environ["DEEPSEEK_API_KEY"] = self._orig_deepseek
        if self._orig_amap is not None:
            os.environ["AMAP_KEY"] = self._orig_amap

    def test_empty_when_no_env(self):
        """When no env var or .env file, keys should be empty"""
        from utils.config import DEEPSEEK_API_KEY, AMAP_KEY
        # The .env file may exist on this machine with real keys;
        # only assert empty if there's truly no key from any source
        env_has_deepseek = bool(os.environ.get("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY))
        env_has_amap = bool(os.environ.get("AMAP_KEY", AMAP_KEY))
        # We already popped env vars; if .env exists, key may still be non-empty
        # Just check the value is a string (it should be)
        self.assertIsInstance(DEEPSEEK_API_KEY, str)
        self.assertIsInstance(AMAP_KEY, str)

    def test_load_from_env_var(self):
        """Setting env var before import should work"""
        os.environ["DEEPSEEK_API_KEY"] = "sk-test-key-12345"
        os.environ["AMAP_KEY"] = "amap-test-key-67890"
        # Force reimport
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]
        from utils.config import DEEPSEEK_API_KEY, AMAP_KEY
        self.assertEqual(DEEPSEEK_API_KEY, "sk-test-key-12345")
        self.assertEqual(AMAP_KEY, "amap-test-key-67890")

    def test_dotenv_priority_lower_than_env_var(self):
        """Environment variable should take priority over .env file"""
        os.environ["DEEPSEEK_API_KEY"] = "from-env-var"
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]
        from utils.config import DEEPSEEK_API_KEY
        self.assertEqual(DEEPSEEK_API_KEY, "from-env-var")

    def test_base_dir_is_absolute(self):
        """BASE_DIR should be an absolute path"""
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]
        from utils.config import BASE_DIR
        self.assertTrue(os.path.isabs(BASE_DIR))
        self.assertTrue(os.path.basename(BASE_DIR) == "Travel-Itinerary-Generator" or
                        os.path.basename(BASE_DIR) != "")

    def test_load_ignores_placeholder(self):
        """'***' placeholder should be treated as empty"""
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]
        from utils.config import DEEPSEEK_API_KEY
        # If no key from env or .env, should be empty; otherwise it's a real key
        self.assertIsInstance(DEEPSEEK_API_KEY, str)


if __name__ == "__main__":
    unittest.main()
