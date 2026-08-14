# -*- coding: utf-8 -*-
"""
Test: network fault tolerance & interruption behavior
=====================================================
- Mock urllib returning 429, 502, socket.timeout
- Verify AMap _request 3-attempt retry & safe empty dict fallback
- Verify AMapQuotaError on QPS/LIMIT exceeded
- Verify LLM retry backoff & rapid exit on cancel_event
- Verify weather API network failure handling
"""
import os
import sys
import time
import socket
import threading
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from utils.amap_api import _request, AMapClient, AmapQuotaError, AmapApiError
from utils.llm import LLMClient
from utils.weather import get_weather, get_weather_for_dates


class TestAmapNetworkTolerance(unittest.TestCase):
    """Test AMap network error recovery, retries, and fallback behavior"""

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen")
    def test_amap_request_502_bad_gateway_retries_and_returns_empty(self, mock_urlopen, mock_sleep):
        """AMap _request retries 3 times on HTTP 502 and returns empty dict without crash"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://restapi.amap.com",
            code=502,
            msg="Bad Gateway",
            hdrs=None,
            fp=None,
        )
        res = _request("https://restapi.amap.com/v3/geocode/geo?key=test&address=test")
        self.assertEqual(res, {})
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen")
    def test_amap_request_socket_timeout_retries_and_returns_empty(self, mock_urlopen, mock_sleep):
        """AMap _request retries 3 times on socket.timeout and returns empty dict without crash"""
        mock_urlopen.side_effect = socket.timeout("timed out")
        res = _request("https://restapi.amap.com/v3/geocode/geo?key=test&address=test")
        self.assertEqual(res, {})
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen")
    def test_amap_request_qps_limit_raises_quota_error(self, mock_urlopen, mock_sleep):
        """AMap _request detects QPS limit, retries twice, and raises AmapQuotaError on 3rd attempt"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "0", "info": "USERKEY_PLAT_NOMORE_QPS"}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with self.assertRaises(AmapQuotaError):
            _request("https://restapi.amap.com/v3/geocode/geo?key=test&address=test")

        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("utils.amap_api._request")
    def test_amap_client_geocode_handles_network_failure_safely(self, mock_request):
        """AMapClient.geocode gracefully returns None when underlying network fails"""
        mock_request.return_value = {}
        client = AMapClient(key="test-key")
        res = client.geocode("东方明珠", "上海")
        self.assertIsNone(res)


class TestLLMNetworkTolerance(unittest.TestCase):
    """Test LLM network retry, backoff, and rapid cancellation"""

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen")
    def test_llm_retries_on_502_and_raises_runtime_error(self, mock_urlopen, mock_sleep):
        """LLMClient retries on HTTP 502/URLError and raises RuntimeError when retries exhausted"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.deepseek.com",
            code=502,
            msg="Bad Gateway",
            hdrs=None,
            fp=None,
        )
        client = LLMClient(provider="deepseek", api_key="sk-test")
        with self.assertRaises(RuntimeError) as ctx:
            client.call("System", "User", max_retries=3)
        self.assertIn("DeepSeek API call failed", str(ctx.exception))
        self.assertEqual(mock_urlopen.call_count, 3)

    def test_llm_cancel_event_triggers_immediate_exit_before_call(self):
        """LLMClient immediately raises InterruptedError if cancel_event is already set"""
        cancel_evt = threading.Event()
        cancel_evt.set()

        client = LLMClient(provider="deepseek", api_key="sk-test")
        t0 = time.time()
        with self.assertRaises(InterruptedError):
            client.call("System", "User", cancel_event=cancel_evt)
        self.assertLess(time.time() - t0, 0.2, "Cancellation must abort immediately")

    @patch("urllib.request.urlopen")
    def test_llm_cancel_event_interrupts_during_retry_backoff(self, mock_urlopen):
        """LLMClient quickly aborts during retry sleep when cancel_event is signalled"""
        mock_urlopen.side_effect = urllib.error.URLError("Connection reset by peer")
        cancel_evt = threading.Event()

        client = LLMClient(provider="deepseek", api_key="sk-test")

        # Background thread signals cancel after 0.05s
        def _cancel_later():
            time.sleep(0.05)
            cancel_evt.set()

        threading.Thread(target=_cancel_later, daemon=True).start()

        t0 = time.time()
        with self.assertRaises(InterruptedError):
            client.call("System", "User", max_retries=3, cancel_event=cancel_evt)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 1.0, "Should abort during retry wait when cancel_event is set")


class TestWeatherNetworkTolerance(unittest.TestCase):
    """Test weather module handling of HTTP 429/500/timeout"""

    @patch("urllib.request.urlopen")
    def test_weather_http_500_safe_error_return(self, mock_urlopen):
        """get_weather handles 500 error and returns structured error dict"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://restapi.amap.com",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=None,
        )
        res = get_weather("上海")
        self.assertIn("error", res)
        self.assertIn("地理编码失败", res["error"])

    @patch("urllib.request.urlopen")
    def test_weather_for_dates_socket_timeout_safe_fallback(self, mock_urlopen):
        """get_weather_for_dates handles socket.timeout and falls back honestly"""
        mock_urlopen.side_effect = socket.timeout("timed out")
        res = get_weather_for_dates("杭州", days=2)
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("type"), "unavailable")
        self.assertEqual(res.get("forecast"), [])


if __name__ == "__main__":
    unittest.main()
