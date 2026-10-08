# -*- coding: utf-8 -*-
"""B8: 测试 rules_engine 规则注册"""
import unittest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rules_engine import RuleEngine


class TestRuleEngine(unittest.TestCase):
    def test_register_get(self):
        """注册规则后能取到"""
        re = RuleEngine()
        re.register("测试.开关", "测试组", "规则", "这是测试规则", True)
        self.assertTrue(re.get("测试.开关"))
        print("✅ 规则注册读取正常")

    def test_not_exist(self):
        """不存在的规则返回默认值"""
        re = RuleEngine()
        self.assertEqual(re.get("不存在.xxx", "默认"), "默认")
        print("✅ 不存在规则返回默认值正常")


if __name__ == "__main__":
    unittest.main()
