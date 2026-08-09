"""
Test: planner 对未解析坐标(None)的鲁棒性 (O1 回归保护)
========================================================
step_6_plan_itinerary 在构建 LLM 输入时对 p["location"] 下标访问(loc[0])。
O1 让 geocode 失败返回 location=None，若 planner 未防护，只要任一 POI
解析失败，整条 pipeline 会在 Step 6 抛 TypeError 崩溃。此测试锁死该回归。
"""
import os, sys, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["AMAP_KEY"] = "test-key"
os.environ["DEEPSEEK_API_KEY"] = "test-key"


class FakeAmap:
    def geocode(self, *a, **k):
        return None  # 城市中心编码也返回 None，避免真实网络


class TestPlannerNoneCoord(unittest.TestCase):
    def test_null_location_poi_does_not_crash(self):
        from pipeline.steps import planner
        context = {
            "city": "上海",
            "days": 1,
            "poi_enriched": [
                {"name": "外滩", "location": [121.49, 31.24], "address": "",
                 "district": "", "nearby_food": []},
                # 故意放入一个未解析 POI（O1 之后的真实场景）
                {"name": "乱码地点xyz", "location": None, "address": "",
                 "district": "", "nearby_food": []},
            ],
            "distance_matrix": {"matrix": [], "labels": []},
            "food_recommendations": [],
            "flyai_prices": {},
        }
        fusion_json = ('{"days":[{"day":1,"label":"测试","summary":"",'
                       '"accommodation_city":"","slots":[]}],'
                       '"overall_note":"","food_highlights":[]}')
        # 关键：call_deepseek 在 step_6 函数体内 `from utils.llm import`，
        # 故 patch 源模块，函数入口重新绑定时会取到 mock
        with patch("utils.llm.call_deepseek", return_value=fusion_json):
            ctx = planner.step_6_plan_itinerary(context, amap=FakeAmap())
        # 不应抛 TypeError；函数应正常返回 context
        self.assertIn("poi_enriched", ctx)
        # 下游 entry 构建对 None 坐标应保持 None，不伪造
        self.assertIsNone(ctx["poi_enriched"][1]["location"])


if __name__ == "__main__":
    unittest.main()
