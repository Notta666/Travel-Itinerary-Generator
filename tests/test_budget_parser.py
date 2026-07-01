"""
Test: _parse_budget() — budget string parsing
==============================================
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from utils.parsers import _parse_budget


class TestParseBudget(unittest.TestCase):
    """Test boundary conditions of _parse_budget()"""

    def test_empty_or_none(self):
        self.assertEqual(_parse_budget(""), (None, None))
        self.assertEqual(_parse_budget(None), (None, None))
        self.assertEqual(_parse_budget("   "), (None, None))

    def test_no_budget_numbers(self):
        """String with no numbers >=100 returns None"""
        self.assertEqual(_parse_budget("随便"), (None, None))
        self.assertEqual(_parse_budget("便宜点"), (None, None))

    def test_total_budget_only(self):
        """A single large number is treated as total budget"""
        daily, total = _parse_budget("共5000元", days=2, people_count=2)
        self.assertEqual(daily, 5000 // (2 * 2))  # 1250
        self.assertEqual(total, 1250 * 2 * 2)

    def test_daily_budget(self):
        """'每天3000' → daily budget"""
        daily, total = _parse_budget("每天3000元", days=3, people_count=2)
        # is_daily=True, not per-person -> daily_per_person = 3000 // 2 = 1500
        self.assertEqual(daily, 1500)
        self.assertEqual(total, 1500 * 3 * 2)

    def test_per_person_budget(self):
        """'人均2000' → per-person budget for the whole trip"""
        daily, total = _parse_budget("人均2000", days=2, people_count=2)
        # is_per_person=True, not daily -> daily_per_person = 2000 // 2 = 1000
        self.assertEqual(daily, 1000)
        self.assertEqual(total, 1000 * 2 * 2)

    def test_daily_per_person(self):
        """'每人每天500' → daily per person"""
        daily, total = _parse_budget("每人每天500", days=3, people_count=4)
        # is_daily=True, is_per_person=True -> daily_per_person = 500
        self.assertEqual(daily, 500)
        self.assertEqual(total, 500 * 3 * 4)

    def test_budget_with_people_in_string(self):
        """'两人共3000' → 2 people, 3000 total"""
        daily, total = _parse_budget("两人共3000", days=2, people_count=2)
        # Not daily, not per-person -> daily_per_person = 3000 // (2*2) = 750
        self.assertEqual(daily, 750)
        self.assertEqual(total, 750 * 2 * 2)

    def test_large_budget(self):
        daily, total = _parse_budget("预算100000", days=7, people_count=2)
        self.assertIsNotNone(daily)
        self.assertGreater(total, 0)

    def test_small_number_returns_none(self):
        """Numbers smaller than 100 should be ignored (returns None)"""
        daily, total = _parse_budget("每天1元", days=1, people_count=1)
        self.assertEqual(daily, None)

    def test_zero_days(self):
        """Edge case: zero days should not cause division by zero"""
        daily, total = _parse_budget("共5000元", days=0, people_count=2)
        # max(days,1) -> 1
        self.assertIsNotNone(daily)

    def test_zero_people(self):
        """Edge case: zero people should not cause division by zero"""
        daily, total = _parse_budget("共5000元", days=2, people_count=0)
        # max(people_count,1) -> 1
        self.assertIsNotNone(daily)

    def test_chinese_number_people(self):
        """'三人' in budget string should parse correctly"""
        daily, total = _parse_budget("三人共6000", days=2, people_count=3)
        # specified_people=3, not daily, not per-person
        # daily_per_person = 6000 // (3*2) = 1000
        self.assertEqual(daily, 1000)


class TestParseBudgetEdgeCases(unittest.TestCase):
    """Additional edge cases"""

    def test_commas_in_number(self):
        """Numbers with commas"""
        daily, total = _parse_budget("共10,000元", days=2, people_count=2)
        self.assertIsNotNone(daily)
        self.assertGreater(total, 0)

    def test_multiple_numbers_only_large_one(self):
        """Only the largest number >=100 should be used"""
        daily, total = _parse_budget("我们2个人去玩3天预算5000元", days=3, people_count=2)
        # Numbers found: 2, 3, 5000. Only 5000 >= 100
        self.assertIsNotNone(daily)

    def test_daily_per_person_exact(self):
        """每人每天800元"""
        daily, total = _parse_budget("每人每天800元", days=4, people_count=2)
        self.assertEqual(daily, 800)
        self.assertEqual(total, 800 * 4 * 2)


if __name__ == "__main__":
    unittest.main()
