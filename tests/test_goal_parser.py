"""
Test: _parse_goal() — goal parsing with mocked LLM calls
=========================================================
Note: _parse_goal() does `from utils.llm import call_deepseek` inside the
function body, so we must patch at `utils.llm.call_deepseek`.
"""
import os, sys, json, unittest
from unittest.mock import patch, MagicMock

# Ensure project root is importable
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from utils.parsers import _parse_goal


class TestParseGoal(unittest.TestCase):
    """Test _parse_goal() with mocked call_deepseek at utils.llm"""

    @patch("utils.llm.call_deepseek")
    def test_basic_goal(self, mock_call):
        """A simple goal returns structured data"""
        mock_call.return_value = {
            "city": "杭州",
            "start_city": "",
            "days": 2,
            "start_date": "2026-07-01",
            "pois": ["西湖", "灵隐寺"],
            "transport": "自驾",
            "budget": "",
            "preference": "",
            "accommodation": "西湖区",
            "people_count": 2,
        }
        city, days, pois, prefs = _parse_goal("杭州周末自驾")
        self.assertEqual(city, "杭州")
        self.assertEqual(days, 2)
        self.assertIn("西湖", pois)
        self.assertEqual(prefs["transport"], "自驾")
        self.assertEqual(prefs["people_count"], 2)

    @patch("utils.llm.call_deepseek")
    def test_with_budget_and_people(self, mock_call):
        """Goal specifying budget and people count"""
        mock_call.return_value = {
            "city": "三亚",
            "start_city": "北京",
            "days": 5,
            "start_date": "2026-08-01",
            "pois": ["亚龙湾", "天涯海角"],
            "transport": "飞机",
            "budget": "两人共10000",
            "preference": "度假",
            "accommodation": "亚龙湾",
            "people_count": 2,
        }
        city, days, pois, prefs = _parse_goal("三亚五天四晚度假 预算10000")
        self.assertEqual(city, "三亚")
        self.assertEqual(days, 5)
        self.assertEqual(prefs["people_count"], 2)
        self.assertEqual(prefs["start_city"], "北京")
        self.assertIsNotNone(prefs.get("_budget_parsed"))

    @patch("utils.llm.call_deepseek")
    def test_llm_returns_empty_dict(self, mock_call):
        """LLM returning empty dict uses defaults"""
        mock_call.return_value = {}
        city, days, pois, prefs = _parse_goal("随便玩玩")
        self.assertEqual(city, "上海")
        self.assertEqual(days, 2)
        self.assertEqual(pois, [])
        # When LLM returns empty dict, _parse_goal falls back to defaults
        # which returns empty prefs dict
        self.assertIsInstance(prefs, dict)

    @patch("utils.llm.call_deepseek")
    def test_llm_raises_exception(self, mock_call):
        """Exception from LLM uses default fallback"""
        mock_call.side_effect = RuntimeError("API timeout")
        city, days, pois, prefs = _parse_goal("北京三日游")
        self.assertEqual(city, "上海")
        self.assertEqual(days, 2)

    @patch("utils.llm.call_deepseek")
    def test_goal_with_weekend(self, mock_call):
        """Weekend keyword sets days to 2"""
        mock_call.return_value = {
            "city": "莫干山",
            "start_city": "",
            "days": 2,
            "start_date": "2026-07-04",
            "pois": ["莫干山风景区"],
            "transport": "自驾",
            "budget": "",
            "preference": "避暑",
            "accommodation": "",
            "people_count": 4,
        }
        city, days, pois, prefs = _parse_goal("莫干山避暑自驾 一家四口")
        self.assertEqual(city, "莫干山")
        self.assertEqual(days, 2)
        self.assertEqual(prefs["people_count"], 4)

    @patch("utils.llm.call_deepseek")
    def test_goal_large_group(self, mock_call):
        """Large group parsing"""
        mock_call.return_value = {
            "city": "上海",
            "start_city": "",
            "days": 1,
            "start_date": "2026-07-02",
            "pois": ["迪士尼"],
            "transport": "高铁",
            "budget": "",
            "preference": "亲子",
            "accommodation": "",
            "people_count": 3,
        }
        city, days, pois, prefs = _parse_goal("上海迪士尼三口之家一日游")
        self.assertEqual(city, "上海")
        self.assertEqual(prefs["people_count"], 3)
        self.assertEqual(prefs["preference"], "亲子")


if __name__ == "__main__":
    unittest.main()
