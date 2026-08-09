"""
Test: 地理编码数据诚信 (O1)
============================
验证 step_3_geocode 在编码失败时不再注入「城市中心+哈希偏移」伪坐标，
而是 location=None 且 geo_status="unresolved"，由下游地图/手册跳过并提示用户。
"""
import os, sys, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["AMAP_KEY"] = "test-key"


class TestGeocodeIntegrity(unittest.TestCase):
    """编码失败应标记 unresolved，绝不伪造坐标"""

    def test_failed_geocode_marks_unresolved_no_mock_coord(self):
        from pipeline.steps import geocode as geocode_mod
        context = {"city": "上海", "manual_pois": ["乱码地点xyz123"], "xhs_sight_names": []}
        # 模拟高德全部返回 None（编码失败）
        with patch.object(geocode_mod.amap, "geocode", return_value=None):
            ctx = geocode_mod.step_3_geocode(context, manual_pois=["乱码地点xyz123"])
        pois = ctx["poi_geocoded"]
        self.assertEqual(len(pois), 1)
        self.assertIsNone(pois[0]["location"], "编码失败不应生成伪坐标")
        self.assertEqual(pois[0]["geo_status"], "unresolved")

    def test_resolved_geocode_keeps_coord(self):
        from pipeline.steps import geocode as geocode_mod
        context = {"city": "上海", "manual_pois": ["外滩"], "xhs_sight_names": []}
        fake = (121.49, 31.24)
        with patch.object(geocode_mod.amap, "geocode", return_value=fake):
            ctx = geocode_mod.step_3_geocode(context, manual_pois=["外滩"])
        pois = ctx["poi_geocoded"]
        self.assertEqual(pois[0]["location"], fake)
        self.assertEqual(pois[0]["geo_status"], "resolved")


if __name__ == "__main__":
    unittest.main()
