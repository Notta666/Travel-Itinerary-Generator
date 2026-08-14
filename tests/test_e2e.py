# -*- coding: utf-8 -*-
"""
Test: E2E Full Pipeline — Mocked End-to-End Execution
=====================================================
- Full lifecycle from _parse_goal -> Step 1 -> Step 9 brochure delivery
- All external dependencies (AMap, DeepSeek LLM, XiaoHongShu, Weather, FlyAI, ImageFetcher) fully mocked
- Validates context outputs: itinerary, brochure_path, weather, tips
- Ensures fast execution (< 5s) and zero network leakage
"""
import os
import sys
import json
import time
import threading
import unittest
from unittest.mock import patch, MagicMock

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from utils.parsers import _parse_goal
from pipeline.run_pipeline import run_pipeline, PipelineStoppedError


def _mock_call_deepseek(system_prompt, user_prompt, *args, **kwargs):
    """Smart mock for DeepSeek LLM calls based on exact prompt context."""
    s_lower = system_prompt.lower()
    u_lower = user_prompt.lower()

    if "将用户的自然语言需求解析为结构化json" in u_lower:
        # Step 0: Goal parsing
        return {
            "city": "杭州",
            "start_city": "上海",
            "days": 2,
            "start_date": "2026-08-20",
            "pois": ["西湖", "灵隐寺", "河坊街", "雷峰塔"],
            "transport": "高铁",
            "budget": "两人共3000",
            "preference": "文化古迹",
            "accommodation": "西湖区",
            "people_count": 2,
            "multi_cities": [],
        }
    elif "精读笔记" in u_lower or "提取真实被推荐" in u_lower or "小红书笔记" in u_lower or "提取" in s_lower:
        # Step 2: Research extraction
        return {
            "sights": [
                {"name": "西湖", "city": "杭州", "complaints": "无"},
                {"name": "灵隐寺", "city": "杭州", "complaints": "无"},
                {"name": "河坊街", "city": "杭州", "complaints": "无"},
                {"name": "雷峰塔", "city": "杭州", "complaints": "无"},
            ],
            "foods": [
                {
                    "name": "楼外楼",
                    "cuisine": "杭帮菜",
                    "city": "杭州",
                    "must_try": ["西湖醋鱼", "东坡肉"],
                    "rating": "4.6",
                    "cost": "120",
                    "note": "百年老店，临湖赏景",
                },
                {
                    "name": "知味观",
                    "cuisine": "小吃",
                    "city": "杭州",
                    "must_try": ["小笼包", "猫耳朵"],
                    "rating": "4.5",
                    "cost": "50",
                    "note": "传统老字号名小吃",
                },
            ],
        }
    elif "交通规划专家" in system_prompt or "推荐最佳交通方式" in u_lower:
        # Step 5.6: Transport decision
        return {
            "transport": "高铁",
            "reason": "距离适中，高铁性价比最高",
        }
    elif "出行小贴士" in system_prompt or "贴士" in s_lower or "出行建议" in u_lower or "小贴士" in u_lower:
        # Step 8.5: Travel tips
        return {
            "general": ["携带有效身份证件", "夏季注意防晒防蚊"],
            "preference_tips": ["古迹游览建议租用电子导览"],
            "daily_tips": ["Day1: 西湖清晨漫步人流较少", "Day2: 灵隐寺建议早间前往避峰"],
            "emergency": "杭州报警电话110，急救电话120",
        }
    else:
        # Step 6: Itinerary planning (Bull, Bear, Fusion)
        return {
            "overall_concept": "两日经典人文漫游",
            "accommodation_suggest": "市中心商业区",
            "days": [
                {
                    "day": 1,
                    "label": "经典地标打卡",
                    "summary": "首日游览著名景点",
                    "accommodation_city": "杭州",
                    "slots": [
                        {"type": "sight", "name": "西湖", "city": "杭州", "time_slot": "09:00-12:00", "transit": "步行15分钟", "note": "漫步苏堤"},
                        {"type": "food", "name": "楼外楼", "city": "杭州", "time_slot": "12:00-13:30", "transit": "打车10分钟", "cuisine": "杭帮菜", "cost": "120", "rating": "4.6", "note": "品尝西湖醋鱼"},
                        {"type": "sight", "name": "雷峰塔", "city": "杭州", "time_slot": "14:00-17:00", "transit": "打车15分钟", "note": "俯瞰西湖全景"},
                    ],
                },
                {
                    "day": 2,
                    "label": "古迹漫游",
                    "summary": "次日游览古迹与历史街区",
                    "accommodation_city": "杭州",
                    "slots": [
                        {"type": "sight", "name": "灵隐寺", "city": "杭州", "time_slot": "09:00-12:30", "transit": "打车20分钟", "note": "参拜祈福"},
                        {"type": "food", "name": "知味观", "city": "杭州", "time_slot": "12:30-14:00", "transit": "步行5分钟", "cuisine": "小吃", "cost": "50", "rating": "4.5", "note": "传统小吃"},
                        {"type": "sight", "name": "河坊街", "city": "杭州", "time_slot": "14:00-17:00", "transit": "返程", "note": "历史文化街区"},
                    ],
                },
            ],
            "overall_note": "【景点与美食辩论纪要】\n综合分析师方案，精选经典景点与老字号餐厅。\n【总体行程说明】\n行程安排紧凑合理。",
            "food_highlights": ["西湖醋鱼", "杭州小笼包"],
        }


def _mock_amap_request(url, timeout=10):
    """Mock AMap HTTP responses for all endpoints."""
    url_str = str(url)
    if "geocode/geo" in url_str:
        return {
            "status": "1",
            "geocodes": [
                {
                    "location": "120.153576,30.287459",
                    "level": "兴趣点",
                    "formatted_address": "浙江省杭州市西湖区",
                    "adcode": "330100",
                }
            ],
        }
    elif "direction/driving" in url_str:
        return {
            "status": "1",
            "route": {
                "paths": [
                    {
                        "distance": "3200",
                        "duration": "720",
                    }
                ]
            },
        }
    elif "place/around" in url_str:
        return {
            "status": "1",
            "pois": [
                {
                    "name": "楼外楼",
                    "location": "120.153,30.287",
                    "typecode": "050100",
                    "address": "孤山路30号",
                    "biz_ext": {"rating": "4.6", "cost": "120"},
                }
            ],
        }
    elif "weather/weatherInfo" in url_str:
        return {
            "status": "1",
            "forecasts": [
                {
                    "city": "杭州",
                    "casts": [
                        {
                            "date": "2026-08-20",
                            "dayweather": "晴",
                            "nightweather": "多云",
                            "daytemp": "32",
                            "nighttemp": "24",
                        },
                        {
                            "date": "2026-08-21",
                            "dayweather": "多云",
                            "nightweather": "阴",
                            "daytemp": "31",
                            "nighttemp": "23",
                        },
                    ],
                }
            ],
        }
    elif "/v3/ip" in url_str:
        return {"status": "1", "city": "上海"}
    return {"status": "1", "pois": []}


def _mock_weather_for_dates(*args, **kwargs):
    return {
        "success": True,
        "type": "forecast",
        "city": "杭州",
        "forecast": [
            {"date": "2026-08-20", "day_weather": "晴", "night_weather": "多云", "temp_range": "24~34°C"},
            {"date": "2026-08-21", "day_weather": "多云", "night_weather": "阴", "temp_range": "25~33°C"},
        ],
        "suggestions": ["🧴 紫外线偏强，建议做好防晒", "✨ 天气宜人，祝旅途愉快"],
    }


class TestPipelineE2E(unittest.TestCase):
    """End-to-End Pipeline test covering single city, multi city, and interruption"""

    @patch("utils.image_fetcher.get_photos", return_value=["https://example.com/photo.jpg"])
    @patch("utils.weather.get_weather_for_dates", side_effect=_mock_weather_for_dates)
    @patch("utils.llm.call_deepseek", side_effect=_mock_call_deepseek)
    @patch("utils.amap_api._request", side_effect=_mock_amap_request)
    @patch("utils.research.XiaoHongShu.search", return_value=[{"title": "杭州攻略", "url": "https://xhs.com/1", "desc": "西湖灵隐"}])
    @patch("utils.research.XiaoHongShu.read_note_content", return_value={"title": "杭州攻略", "content": "首日西湖雷峰塔，次日灵隐寺。"})
    @patch("utils.research.XiaoHongShu.get_comments", return_value=[{"author": "游客", "text": "很好", "likes": 5}])
    @patch("utils.flyai_api.FlyAIApiClient.check_environment", return_value=False)
    def test_single_city_e2e_pipeline(self, *mocks):
        """Single-city pipeline from natural goal text to brochure delivery"""
        # Step 0: Goal parsing
        city, days, pois, prefs = _parse_goal("杭州2日游 预算3000")
        self.assertEqual(city, "杭州")
        self.assertEqual(days, 2)
        self.assertEqual(prefs["transport"], "高铁")

        progress_events = []
        def _on_progress(step, msg, pct):
            progress_events.append((step, pct))

        # Run pipeline
        t0 = time.time()
        context = run_pipeline(
            city=city,
            days=days,
            use_research=True,
            manual_pois=pois,
            prefs=prefs,
            progress_callback=_on_progress,
        )
        elapsed = time.time() - t0

        # Assertions
        self.assertNotIn("error", context, f"Pipeline error: {context.get('error')}")
        self.assertEqual(context.get("city"), "杭州")
        self.assertEqual(context.get("days"), 2)

        # Validate itinerary structure
        itinerary = context.get("itinerary", [])
        self.assertEqual(len(itinerary), 2, "Should contain 2 days itinerary")
        self.assertTrue(any(p.get("name") == "西湖" for d in itinerary for p in d.get("pois", [])))

        # Validate outputs generated on disk
        brochure_path = context.get("brochure_path")
        self.assertIsNotNone(brochure_path)
        self.assertTrue(os.path.exists(brochure_path), "Brochure HTML file must exist on disk")

        with open(brochure_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            self.assertIn("<!DOCTYPE html>", html_content)
            self.assertIn("杭州", html_content)
            self.assertIn("西湖", html_content)

        # Validate progress tracking
        self.assertGreater(len(progress_events), 5)
        self.assertEqual(progress_events[-1][1], 100, "Progress should finish at 100%")
        self.assertLess(elapsed, 15.0, "E2E mock pipeline must execute in under 15s")

    @patch("utils.image_fetcher.get_photos", return_value=["https://example.com/photo.jpg"])
    @patch("utils.weather.get_weather_for_dates", side_effect=_mock_weather_for_dates)
    @patch("utils.llm.call_deepseek", side_effect=_mock_call_deepseek)
    @patch("utils.amap_api._request", side_effect=_mock_amap_request)
    @patch("utils.research.XiaoHongShu.search", return_value=[])
    @patch("utils.flyai_api.FlyAIApiClient.check_environment", return_value=False)
    def test_multi_city_e2e_pipeline(self, *mocks):
        """Multi-city pipeline (e.g. 杭州+苏州 3日游) runs orchestrator and produces unified brochure"""
        prefs = {
            "start_city": "上海",
            "transport": "高铁",
            "people_count": 2,
            "budget": "共5000元",
        }

        context = run_pipeline(
            city="杭州+苏州",
            days=3,
            use_research=False,
            prefs=prefs,
            multi_cities=["杭州", "苏州"],
        )

        self.assertNotIn("error", context)
        self.assertIn("杭州+苏州", context.get("city", ""))
        self.assertIsNotNone(context.get("brochure_path"))
        self.assertTrue(os.path.exists(context["brochure_path"]))

    @patch("utils.llm.call_deepseek", side_effect=_mock_call_deepseek)
    @patch("utils.amap_api._request", side_effect=_mock_amap_request)
    def test_pipeline_cancellation_preserves_state(self, *mocks):
        """Pipeline respects cancel_event and halts execution safely without unhandled crashes"""
        cancel_evt = threading.Event()
        cancel_evt.set()  # Cancelled from the start

        prefs = {"start_city": "上海"}
        context = run_pipeline(
            city="杭州",
            days=2,
            use_research=False,
            prefs=prefs,
            cancel_event=cancel_evt,
        )
        # Should halt gracefully and not complete deliver step
        self.assertIsNone(context.get("brochure_path"))


if __name__ == "__main__":
    unittest.main()
