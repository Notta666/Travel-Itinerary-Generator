"""
Test: 手册渲染对未解析坐标的容错 (O1 + O3)
============================================
mock 掉网络（图片/酒店搜索），用含 1 个 unresolved POI 的行程渲染手册：
- 不应抛异常（模板已跳过空坐标 marker）
- 产物 HTML 应包含「位置待核实」标注
- research_source="default_pois" 时应渲染数据来源徽标
依赖 jinja2（项目渲染依赖，requirements.txt 已声明）。
"""
import os, sys, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("AMAP_KEY", "test-key")


class TestBrochureUnresolved(unittest.TestCase):
    def _build_itinerary(self):
        return [{
            "day": 1,
            "accommodation_city": "上海",
            "pois": [
                {"name": "外滩", "location": [121.49, 31.24], "address": "中山东一路",
                 "time_slot": "09:00-11:00", "geo_status": "resolved"},
                {"name": "乱码地点xyz", "location": None, "address": "",
                 "time_slot": "14:00-16:00", "geo_status": "unresolved"},
            ],
            "foods": [],
        }]

    def test_unresolved_poi_renders_with_marker_and_no_crash(self):
        from utils.brochure import generate_brochure
        itinerary = self._build_itinerary()
        with patch("utils.brochure._fetch_photos_batch", return_value={}), \
             patch("utils.brochure._search_hotels", return_value=[]):
            html = generate_brochure(
                itinerary, "上海",
                research_source="default_pois",
                weather={"forecast": [{"date": "2026-08-01", "day_weather": "晴",
                                       "night_weather": "多云", "temp_range": "28~35°C"}]},
                tips={},
            )
        self.assertIn('<span class="t tr">📍 位置待核实</span>', html, "未解析 POI 应在卡片标注「位置待核实」")
        self.assertIn("内置推荐库", html, "research_source=default_pois 应渲染数据来源徽标")
        self.assertIn("121.49", html, "已解析 POI 坐标仍应出现在地图数据中")

    def test_resolved_only_no_marker(self):
        from utils.brochure import generate_brochure
        itinerary = [{
            "day": 1, "accommodation_city": "上海",
            "pois": [{"name": "外滩", "location": [121.49, 31.24], "address": "中山东一路",
                      "time_slot": "09:00-11:00", "geo_status": "resolved"}],
            "foods": [],
        }]
        with patch("utils.brochure._fetch_photos_batch", return_value={}), \
             patch("utils.brochure._search_hotels", return_value=[]):
            html = generate_brochure(itinerary, "上海", research_source="xiaohongshu", tips={})
        self.assertNotIn('<span class="t tr">📍 位置待核实</span>', html)
        self.assertNotIn("内置推荐库", html)


if __name__ == "__main__":
    unittest.main()
