"""
Tests for Batch B External API Fixes (B1-B5)
==============================================
"""
import os
import sys
import time
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.flyai_api import FlyAIApiClient
from utils.amap_api import AMapClient, AmapApiError, AmapQuotaError, _request
from utils.research import XiaoHongShu, _safe_jina_url


class TestB1FlyAiJsonParsing(unittest.TestCase):
    """B1: FlyAI JSON non-greedy parsing when log pollution occurs"""

    def setUp(self):
        self.client = FlyAIApiClient()

    @patch("subprocess.run")
    def test_json_parsing_with_log_prefix_and_suffix(self, mock_run):
        """Construct string with log prefix/suffix + valid JSON -> assert correct extraction"""
        mock_output = (
            "npm WARN notice line 1\n"
            "npm WARN notice line 2\n"
            '{"data": {"itemList": [{"ticketPrice": 200}]}}\n'
            "npm notice end\n"
        )
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = mock_output
        mock_res.stderr = ""
        mock_run.return_value = mock_res

        res = self.client._run_cli(["search-flight"])
        self.assertIsNotNone(res)
        self.assertIn("data", res)
        self.assertEqual(res["data"]["itemList"][0]["ticketPrice"], 200)

    @patch("subprocess.run")
    def test_json_parsing_multiple_json_blocks(self, mock_run):
        """Construct output with multiple JSON blocks -> returns last candidate object"""
        mock_output = (
            '{"level": "info", "msg": "starting search"}\n'
            '{"data": {"itemList": [{"price": 150}]}}\n'
        )
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = mock_output
        mock_res.stderr = ""
        mock_run.return_value = mock_res

        res = self.client._run_cli(["search-flight"])
        self.assertIsNotNone(res)
        self.assertIn("data", res)
        self.assertEqual(res["data"]["itemList"][0]["price"], 150)


class TestB2FlyAiRiskBlockedWindow(unittest.TestCase):
    """B2: FlyAI risk_blocked timestamp-based window check"""

    def setUp(self):
        self.client = FlyAIApiClient()

    def test_risk_blocked_until_past(self):
        """Past risk_blocked_until -> risk_blocked evaluates to False, allowing retry"""
        self.client._risk_blocked_until = time.time() - 10
        self.assertFalse(self.client.risk_blocked)
        # Verify property setter
        self.client.risk_blocked = False
        self.assertFalse(self.client.risk_blocked)

    def test_risk_blocked_until_future(self):
        """Future risk_blocked_until -> risk_blocked evaluates to True, fallback/degrade"""
        self.client._risk_blocked_until = time.time() + 1800
        self.assertTrue(self.client.risk_blocked)
        res = self.client._run_cli(["search-flight"])
        self.assertIsNone(res)

    def test_risk_blocked_property_setter(self):
        """Setting client.risk_blocked = True sets future window"""
        self.client.risk_blocked = True
        self.assertTrue(self.client.risk_blocked)
        self.assertGreater(self.client._risk_blocked_until, time.time() + 1700)


class TestB3ResearchXhsNoneGuard(unittest.TestCase):
    """B3: step_2_research xhs=None default guard"""

    @patch("utils.research.XiaoHongShu")
    def test_step_2_research_handles_none_xhs(self, mock_xhs_cls):
        """Passing xhs=None to step_2_research instantiates XiaoHongShu without AttributeError"""
        mock_instance = MagicMock()
        mock_instance.search.return_value = []
        mock_xhs_cls.return_value = mock_instance

        from pipeline.steps.research import step_2_research

        context = {"city": "上海", "multi_cities": ["上海"]}
        res_ctx = step_2_research(context, xhs=None)
        self.assertIsNotNone(res_ctx)
        self.assertTrue(mock_xhs_cls.called)


class TestB4JinaUrlValidation(unittest.TestCase):
    """B4: Jina URL validation and rejection of unsafe/invalid URLs"""

    def test_safe_jina_url_valid(self):
        self.assertEqual(_safe_jina_url("https://www.xiaohongshu.com/explore/123"), "https://www.xiaohongshu.com/explore/123")
        self.assertEqual(_safe_jina_url("http://example.com/note/1"), "http://example.com/note/1")

    def test_safe_jina_url_invalid_schemes(self):
        self.assertIsNone(_safe_jina_url("javascript:alert(1)"))
        self.assertIsNone(_safe_jina_url("file:///etc/passwd"))
        self.assertIsNone(_safe_jina_url("data:text/html,test"))

    def test_safe_jina_url_control_characters(self):
        self.assertIsNone(_safe_jina_url("https://example.com/test\x00"))
        self.assertIsNone(_safe_jina_url("https://example.com/test\r\n"))
        self.assertIsNone(_safe_jina_url(""))
        self.assertIsNone(_safe_jina_url(None))

    def test_read_note_content_rejects_unsafe_url(self):
        xhs = XiaoHongShu()
        res = xhs.read_note_content("javascript:alert(1)")
        self.assertIn("读取失败", res["content"])


class TestB5AmapApiErrorHandling(unittest.TestCase):
    """B5: Amap API error handling for status=0 response"""

    @patch("urllib.request.urlopen")
    def test_status_0_non_limit_raises_amap_api_error(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "0", "info": "INVALID_USER_KEY"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with self.assertRaises(AmapApiError):
            _request("https://restapi.amap.com/v3/geocode/geo?address=上海")

    @patch("urllib.request.urlopen")
    def test_status_0_limit_raises_amap_quota_error(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "0", "info": "USER_DAILY_QUERY_OVER_LIMIT"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch("time.sleep"):
            with self.assertRaises(AmapQuotaError):
                _request("https://restapi.amap.com/v3/geocode/geo?address=上海")


if __name__ == "__main__":
    unittest.main()
