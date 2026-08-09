import pytest
from pipeline.steps.planner import _normalize_name as planner_normalize
from utils.brochure import _normalize_name as brochure_normalize, _deduplicate_itinerary


def test_normalize_name():
    # 测试 3：normalize 函数单元测试
    # "西街" vs "西街（景点）" 视为重复
    assert planner_normalize("西街") == planner_normalize("西街（景点）") == "西街"
    assert brochure_normalize("西街") == brochure_normalize("西街(景点)") == "西街"

    # "开元寺" vs "开元寺东西塔" 不视为重复
    assert planner_normalize("开元寺") != planner_normalize("开元寺东西塔")
    assert brochure_normalize("开元寺") != brochure_normalize("开元寺东西塔")

    # 包含中英文标点、空格、大小写
    assert planner_normalize(" 菜头酸（老字号） ") == "菜头酸"
    assert brochure_normalize("面线糊(庄阿姨)") == "面线糊"


def test_assembly_dedup():
    # 测试 1：构造含重复 slots 的 days 数据 → 模拟组装逻辑去重
    days_out = [
        {
            "day": 1,
            "label": "Day 1 泉州古城",
            "slots": [
                {"type": "sight", "name": "西街", "time_slot": "09:00-11:00"},
                {"type": "food", "name": "面线糊", "time_slot": "12:00-13:00"},
                {"type": "food", "name": "菜头酸", "time_slot": "15:00-16:00"},
            ],
        },
        {
            "day": 2,
            "label": "Day 2 经典再访",
            "slots": [
                {"type": "sight", "name": "西街（景点）", "time_slot": "09:00-11:00"},  # 重复景点
                {"type": "sight", "name": "开元寺", "time_slot": "11:00-13:00"},
                {"type": "food", "name": "面线糊", "time_slot": "13:00-14:00"},       # 重复美食
                {"type": "food", "name": "石花膏", "time_slot": "16:00-17:00"},
            ],
        },
    ]

    # 模拟 planner.py step_6 组装层的去重逻辑
    seen_sights = set()
    seen_foods = set()
    itinerary = []

    for d in days_out:
        day_pois, day_foods = [], []
        for s in d.get("slots", []):
            s_type = s.get("type", "sight")
            name = s["name"]
            norm_name = planner_normalize(name)
            if s_type == "food":
                if norm_name in seen_foods:
                    continue
                seen_foods.add(norm_name)
                day_foods.append({"name": name, "type": s_type})
            else:
                if norm_name in seen_sights:
                    continue
                seen_sights.add(norm_name)
                day_pois.append({"name": name, "type": s_type})
        itinerary.append({"day": d["day"], "pois": day_pois, "foods": day_foods})

    # 断言 Day 1 包含 西街 / 面线糊, 菜头酸
    assert [p["name"] for p in itinerary[0]["pois"]] == ["西街"]
    assert [f["name"] for f in itinerary[0]["foods"]] == ["面线糊", "菜头酸"]

    # 断言 Day 2 重复的 西街（景点） 和 面线糊 被过滤
    assert [p["name"] for p in itinerary[1]["pois"]] == ["开元寺"]
    assert [f["name"] for f in itinerary[1]["foods"]] == ["石花膏"]


def test_brochure_dedup():
    # 测试 2：构造含重复 itinerary → 调用 brochure 的 _deduplicate_itinerary 函数
    raw_itinerary = [
        {
            "day": 1,
            "pois": [{"name": "西街"}, {"name": "开元寺"}],
            "foods": [{"name": "面线糊"}, {"name": "菜头酸"}],
        },
        {
            "day": 2,
            "pois": [{"name": "西街（景点）"}, {"name": "清源山"}],  # 西街重复
            "foods": [{"name": "菜头酸（老字号）"}, {"name": "土笋冻"}],  # 菜头酸重复
        },
    ]

    deduped = _deduplicate_itinerary(raw_itinerary)

    # Day 1 保持不变
    assert [p["name"] for p in deduped[0]["pois"]] == ["西街", "开元寺"]
    assert [f["name"] for f in deduped[0]["foods"]] == ["面线糊", "菜头酸"]

    # Day 2 重复项被清洗，只保留 清源山 和 土笋冻
    assert [p["name"] for p in deduped[1]["pois"]] == ["清源山"]
    assert [f["name"] for f in deduped[1]["foods"]] == ["土笋冻"]
