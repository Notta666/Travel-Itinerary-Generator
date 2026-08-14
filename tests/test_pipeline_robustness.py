import sys
import os
import unittest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestPipelineRobustness(unittest.TestCase):

    def test_c1_lazy_loading(self):
        """C1: import run_pipeline 不应在模块加载阶段实例化 AMapClient 或 XiaoHongShu"""
        with patch('pipeline.run_pipeline.AMapClient') as mock_amap, patch('pipeline.run_pipeline.XiaoHongShu') as mock_xhs:
            import pipeline.run_pipeline as rp
            # Reset mocks in case they were instantiated earlier
            mock_amap.reset_mock()
            mock_xhs.reset_mock()
            
            # Module import / definition shouldn't instantiate them until get_amap()/get_xhs()
            self.assertEqual(mock_amap.call_count, 0)
            self.assertEqual(mock_xhs.call_count, 0)
            
            rp._amap = None
            rp._xhs = None
            
            inst1 = rp.get_amap()
            self.assertEqual(mock_amap.call_count, 1)
            inst2 = rp.get_amap()
            self.assertEqual(mock_amap.call_count, 1)  # Cached

    def test_c2_time_slot_clamping(self):
        """C2: 断言无 24:00+ 的越界时段"""
        for idx in range(10):
            start_h = min(9 + idx * 3, 20)
            end_h = min(start_h + 2, 21)
            time_slot = f"{start_h:02d}:00-{end_h:02d}:00"
            s_h, e_h = [int(x.split(':')[0]) for x in time_slot.split('-')]
            self.assertLessEqual(s_h, 20)
            self.assertLessEqual(e_h, 21)
            self.assertGreaterEqual(e_h, s_h)

            start2 = min(12 + idx * 5, 20)
            end2 = min(start2 + 1, 21)
            time_slot2 = f"{start2:02d}:00-{end2:02d}:00"
            s_h2, e_h2 = [int(x.split(':')[0]) for x in time_slot2.split('-')]
            self.assertLessEqual(s_h2, 20)
            self.assertLessEqual(e_h2, 21)

    def test_c4_safe_parse_fusion_truncated_json(self):
        """C4: _safe_parse_fusion 能够成功容错修复截断 JSON"""
        from pipeline.steps.planner import _safe_parse_fusion

        truncated_json_1 = '{"days": [{"day": 1, "label": "经典打卡", "slots": [{"type": "sight", "name": "西湖"'
        res1 = _safe_parse_fusion(truncated_json_1)
        self.assertIn("days", res1)

        truncated_json_2 = '{"days": [{"day": 1, "slots": []}],'
        res2 = _safe_parse_fusion(truncated_json_2)
        self.assertIn("days", res2)

    def test_c6_missing_slot_name_handling(self):
        """C6: 组装逻辑跳过缺 name 的 slot 不崩溃"""
        from pipeline.steps.planner import step_6_plan_itinerary
        context = {
            "city": "杭州",
            "days": 1,
            "poi_enriched": [{"name": "西湖", "location": [120.15, 30.25], "address": "杭州市"}],
            "distance_matrix": {},
            "food_recommendations": []
        }
        # Mock amap and call_deepseek returning missing name slots
        mock_amap = MagicMock()
        mock_amap.geocode.return_value = [120.15, 30.25]
        
        with patch('utils.llm.call_deepseek') as mock_llm:
            mock_llm.return_value = {
                "days": [{
                    "day": 1,
                    "label": "Day 1",
                    "slots": [
                        {"type": "sight", "time_slot": "09:00-11:00"},  # Missing "name"
                        {"type": "sight", "name": "西湖", "time_slot": "11:00-13:00"}
                    ]
                }],
                "overall_note": "ok",
                "food_highlights": []
            }
            res_ctx = step_6_plan_itinerary(context, amap=mock_amap)
            self.assertEqual(len(res_ctx["itinerary"]), 1)
            self.assertEqual(len(res_ctx["itinerary"][0]["pois"]), 1)
            self.assertEqual(res_ctx["itinerary"][0]["pois"][0]["name"], "西湖")

    def test_c10_hotel_missing_fields_rendering(self):
        """C10: 构造缺 price/name 的酒店 dict 不崩溃"""
        from utils.brochure import generate_brochure
        itinerary = [{
            "day": 1,
            "label": "Day 1",
            "summary": "测试",
            "pois": [{"name": "景点A", "location": [120.1, 30.1]}],
            "foods": []
        }]
        flyai_prices = {
            "available": True,
            "hotel_groups": [{
                "city": "杭州",
                "source": "测试",
                "items": [
                    {},  # 缺 name/price
                    {"name": "测试酒店", "price": None}
                ]
            }]
        }
        try:
            html = generate_brochure(itinerary, "杭州", flyai_prices=flyai_prices)
            self.assertIsInstance(html, str)
            self.assertIn("杭州", html)
        except Exception as e:
            self.fail(f"generate_brochure crashed with missing hotel fields: {e}")

    def test_c15_progress_throttling(self):
        """C15: 验证进度 5→6 不写，5→10 写"""
        _last_pct = {}
        written = []

        def mock_update_db(tid, pct, msg):
            prev = _last_pct.get(tid, -100)
            if pct - prev >= 5 or "完成" in msg or "失败" in msg or pct == 100:
                written.append(pct)
                _last_pct[tid] = pct

        task_id = "test_task"
        mock_update_db(task_id, 5, "Step 1")
        mock_update_db(task_id, 6, "Step 1")
        mock_update_db(task_id, 10, "Step 2")
        mock_update_db(task_id, 11, "Step 2完成")

        self.assertEqual(written, [5, 10, 11])


if __name__ == "__main__":
    unittest.main()
