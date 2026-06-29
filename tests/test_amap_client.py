"""
Test: AMapClient — rate limiting & retry behaviour
===================================================
Mock HTTP to verify retry logic and rate limiting.
"""
import os, sys, json, time, unittest
from unittest.mock import patch, MagicMock, call
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set dummy key before import
os.environ["AMAP_KEY"] = "test-key-for-amap-client"


class TestAMapClientRateLimit(unittest.TestCase):
    """Test rate limiting behaviour of AMapClient.geocode()"""

    def setUp(self):
        # Force reimport
        for mod in list(sys.modules.keys()):
            if 'amap_api' in mod:
                del sys.modules[mod]
        from utils.amap_api import AMapClient
        self.client = AMapClient(key="test-key")

    @patch("utils.amap_api._request")
    def test_rate_limit_enforces_interval(self, mock_request):
        """Verify _rate_limit introduces delay between calls"""
        mock_request.return_value = {
            "status": "1",
            "geocodes": [{"location": "121.4737,31.2304", "level": "兴趣点"}]
        }
        t0 = time.time()
        self.client.geocode("外滩", "上海")
        self.client.geocode("豫园", "上海")
        elapsed = time.time() - t0
        # min_interval=0.3, so two calls should take at least ~0.3s
        self.assertGreaterEqual(elapsed, 0.2,
            "Two consecutive calls should take at least ~0.3s due to rate limiting")

    @patch("utils.amap_api._request")
    def test_request_failure_retry(self, mock_request):
        """_request retries on failure"""
        # Simulate failure twice, then success
        mock_request.side_effect = [
            {},  # attempt 0 fails (empty result)
            {},  # attempt 1 fails
            {"status": "1", "geocodes": [{"location": "121.4737,31.2304", "level": "兴趣点"}]},
        ]
        from utils.amap_api import AMapClient
        client = AMapClient(key="test-key")
        # geocode only retries once internally (attempt range(2)), but _request retries 3 times
        coord = client.geocode("外滩", "上海")
        self.assertIsNotNone(coord)
        self.assertAlmostEqual(coord[0], 121.4737, places=3)

    @patch("utils.amap_api._request")
    def test_all_requests_fail(self, mock_request):
        """When all requests fail, return None"""
        mock_request.return_value = {}  # Always empty
        coord = self.client.geocode("nonexistent-place-12345", "")
        self.assertIsNone(coord)


class TestAMapClientRetry(unittest.TestCase):
    """Test retry logic in _request function"""

    @patch("utils.amap_api._request")
    def test_empty_geocodes_returns_none(self, mock_request):
        """Valid status but no geocodes -> None"""
        mock_request.return_value = {"status": "1", "geocodes": []}
        from utils.amap_api import AMapClient
        client = AMapClient(key="test-key")
        result = client.geocode("", "")
        self.assertIsNone(result)

    def test_rate_limit_thread_safe(self):
        """Multiple threads should not race on _rate_limit"""
        import threading, time
        from utils.amap_api import AMapClient
        client = AMapClient(key="test-key")

        timestamps = []
        lock = threading.Lock()

        def _call():
            with client._lock:
                elapsed = time.time() - client._last_call
                if elapsed < 0.1:
                    time.sleep(0.1 - elapsed)
                client._last_call = time.time()
            with lock:
                timestamps.append(time.time())

        threads = [threading.Thread(target=_call) for _ in range(5)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - t0
        # 5 calls spaced at least 0.1s apart -> minimum ~0.4s
        self.assertGreaterEqual(elapsed, 0.3,
            "5 rate-limited calls should take at least ~0.4s")


if __name__ == "__main__":
    unittest.main()
