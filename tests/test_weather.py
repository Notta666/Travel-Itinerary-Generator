# -*- coding: utf-8 -*-
"""
Test: weather module — real assertions & mock-based tests (no fake-green try/except pass)
========================================================================================
- Normal live weather and forecast parsing
- P2-7: Missing historical weather data marked as '缺测', never fake default 30/22°C
- P2-8: Invalid temperature strings (empty, non-numeric, None) do not crash
- Date range handling (today default, valid dates, invalid date fallback)
- Ultimate fallback honesty (success=False when APIs fail)
"""
import os
import sys
import datetime
import unittest
from unittest.mock import patch, MagicMock

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from utils.weather import get_weather, get_weather_for_dates


class TestWeatherLive(unittest.TestCase):
    """Test get_weather(extensions='base') live weather parsing"""

    @patch("utils.weather._fetch_json")
    def test_live_weather_normal(self, mock_fetch):
        """Valid live weather returns parsed float temperature and suggestions"""
        mock_fetch.side_effect = [
            # 1. Geocode response
            {"status": "1", "geocodes": [{"adcode": "310000"}]},
            # 2. Live weather response
            {
                "status": "1",
                "lives": [
                    {
                        "city": "上海",
                        "weather": "晴",
                        "temperature": "28",
                        "humidity": "60",
                        "winddirection": "东南",
                        "windpower": "3",
                    }
                ],
            },
        ]
        res = get_weather("上海", extensions="base")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("type"), "live")
        self.assertEqual(res.get("city"), "上海")
        self.assertEqual(res.get("temperature"), "28.0°C")
        self.assertIn("🍀 气温宜人", "".join(res.get("suggestions", [])))

    @patch("utils.weather._fetch_json")
    def test_live_weather_invalid_temperature_p2_8(self, mock_fetch):
        """P2-8: Invalid or non-numeric temperature does not crash and formats safely"""
        # Scenario A: Non-numeric temperature string
        mock_fetch.side_effect = [
            {"status": "1", "geocodes": [{"adcode": "310000"}]},
            {
                "status": "1",
                "lives": [
                    {
                        "city": "上海",
                        "weather": "多云",
                        "temperature": "N/A",
                    }
                ],
            },
        ]
        res = get_weather("上海", extensions="base")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("temperature"), "N/A°C")

        # Scenario B: Empty temperature string -> '缺测'
        mock_fetch.side_effect = [
            {"status": "1", "geocodes": [{"adcode": "310000"}]},
            {
                "status": "1",
                "lives": [
                    {
                        "city": "上海",
                        "weather": "阴",
                        "temperature": "",
                    }
                ],
            },
        ]
        res2 = get_weather("上海", extensions="base")
        self.assertTrue(res2.get("success"))
        self.assertEqual(res2.get("temperature"), "缺测")


class TestWeatherForecast(unittest.TestCase):
    """Test get_weather(extensions='all') forecast parsing"""

    @patch("utils.weather._fetch_json")
    def test_forecast_weather_normal(self, mock_fetch):
        """Valid forecast returns parsed temperatures and forecast list"""
        mock_fetch.side_effect = [
            {"status": "1", "geocodes": [{"adcode": "330100"}]},
            {
                "status": "1",
                "forecasts": [
                    {
                        "city": "杭州",
                        "casts": [
                            {
                                "date": "2026-08-14",
                                "dayweather": "雷阵雨",
                                "nightweather": "多云",
                                "daytemp": "35",
                                "nighttemp": "24",
                            },
                            {
                                "date": "2026-08-15",
                                "dayweather": "晴",
                                "nightweather": "晴",
                                "daytemp": "33",
                                "nighttemp": "23",
                            },
                        ],
                    }
                ],
            },
        ]
        res = get_weather("杭州", extensions="all")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("type"), "forecast")
        self.assertEqual(len(res.get("forecast", [])), 2)
        self.assertEqual(res["forecast"][0]["temp_range"], "24~35°C")
        self.assertIn("☔ 今日预计有雨", "".join(res.get("suggestions", [])))

    @patch("utils.weather._fetch_json")
    def test_forecast_invalid_temperature_p2_8(self, mock_fetch):
        """P2-8: Invalid daytemp/nighttemp in casts does not crash and marks '缺测'"""
        mock_fetch.side_effect = [
            {"status": "1", "geocodes": [{"adcode": "330100"}]},
            {
                "status": "1",
                "forecasts": [
                    {
                        "city": "杭州",
                        "casts": [
                            {
                                "date": "2026-08-14",
                                "dayweather": "阴",
                                "nightweather": "阴",
                                "daytemp": None,
                                "nighttemp": "",
                            }
                        ],
                    }
                ],
            },
        ]
        res = get_weather("杭州", extensions="all")
        self.assertTrue(res.get("success"))
        self.assertEqual(res["forecast"][0]["temp_range"], "缺测")
        self.assertEqual(res["today"]["temp_range"], "缺测")


class TestWeatherForDates(unittest.TestCase):
    """Test get_weather_for_dates with near dates and historical fallbacks"""

    @patch("utils.weather.get_weather")
    def test_near_dates_uses_amap_forecast(self, mock_get_weather):
        """Dates within 0-3 days use AMap forecast"""
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        mock_get_weather.return_value = {
            "success": True,
            "type": "forecast",
            "city": "上海",
            "forecast": [
                {
                    "date": today_str,
                    "day_weather": "晴",
                    "night_weather": "多云",
                    "temp_range": "24~32°C",
                }
            ],
            "suggestions": ["✨ 天气宜人，祝旅途愉快"],
        }
        res = get_weather_for_dates("上海,苏州", start_date=today_str, days=1)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("city"), "上海")
        self.assertEqual(len(res.get("forecast", [])), 1)

    @patch("utils.weather._fetch_json")
    def test_historical_weather_normal(self, mock_fetch):
        """Far future dates query Open-Meteo historical data"""
        far_future = (datetime.date.today() + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        mock_fetch.side_effect = [
            # 1. Geocode location
            {"status": "1", "geocodes": [{"location": "120.153576,30.287459"}]},
            # 2. Open-Meteo archive response
            {
                "daily": {
                    "time": ["2025-09-14", "2025-09-15"],
                    "temperature_2m_max": [29.2, 28.1],
                    "temperature_2m_min": [19.8, 18.5],
                    "rain_sum": [0.0, 5.2],
                    "weather_code": [0, 61],
                }
            },
        ]
        res = get_weather_for_dates("杭州", start_date=far_future, days=2)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("type"), "historical")
        self.assertEqual(len(res.get("forecast", [])), 2)
        self.assertEqual(res["forecast"][0]["day_weather"], "晴")
        self.assertEqual(res["forecast"][0]["temp_range"], "20~29°C")
        self.assertEqual(res["forecast"][1]["day_weather"], "小雨")
        self.assertIn("☔ 往年同期有降水记录", "".join(res.get("suggestions", [])))

    @patch("utils.weather._fetch_json")
    def test_historical_weather_missing_data_p2_7(self, mock_fetch):
        """P2-7: Missing historical data is marked '缺测', never fake default 30/22°C"""
        far_future = (datetime.date.today() + datetime.timedelta(days=45)).strftime("%Y-%m-%d")
        mock_fetch.side_effect = [
            {"status": "1", "geocodes": [{"location": "120.153576,30.287459"}]},
            {
                "daily": {
                    "time": ["2025-09-29"],
                    "temperature_2m_max": [None],
                    "temperature_2m_min": [None],
                    "rain_sum": [None],
                    "weather_code": [None],
                }
            },
        ]
        res = get_weather_for_dates("杭州", start_date=far_future, days=1)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("type"), "historical")
        self.assertEqual(res["forecast"][0]["day_weather"], "缺测")
        self.assertEqual(res["forecast"][0]["temp_range"], "缺测")
        # Ensure fake 30/22 default is NOT injected
        self.assertNotIn("30~22", res["forecast"][0]["temp_range"])
        self.assertNotIn("22~30", res["forecast"][0]["temp_range"])

    @patch("utils.weather._fetch_json")
    def test_ultimate_fallback_when_all_fail(self, mock_fetch):
        """When external APIs fail, ultimate fallback returns honest success=False"""
        far_future = (datetime.date.today() + datetime.timedelta(days=60)).strftime("%Y-%m-%d")
        mock_fetch.side_effect = RuntimeError("Network unreachable")
        res = get_weather_for_dates("拉萨", start_date=far_future, days=2)
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("type"), "unavailable")
        self.assertEqual(res.get("forecast"), [])
        self.assertEqual(res.get("suggestions"), [])


class TestWeatherEdgeCases(unittest.TestCase):
    """Test date parsing edge cases and comma separated cities"""

    def test_invalid_start_date_string_falls_back_to_today(self):
        """Invalid date string should fall back to today without crashing"""
        with patch("utils.weather.get_weather") as mock_get_weather:
            mock_get_weather.return_value = {"success": True, "forecast": []}
            res = get_weather_for_dates("上海", start_date="not-a-valid-date", days=2)
            mock_get_weather.assert_called_once()
            self.assertEqual(mock_get_weather.call_args[0][0], "上海")

    @patch("utils.weather._fetch_json")
    def test_city_geocode_failure(self, mock_fetch):
        """Unknown city returns structured error"""
        mock_fetch.return_value = {"status": "0", "info": "INVALID_USER_KEY"}
        res = get_weather("未知神秘城市999")
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
