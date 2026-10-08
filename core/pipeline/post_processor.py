# -*- coding: utf-8 -*-
"""回复后处理：群聊合并 + 代码沙盒验证 + 触发后台闭环"""
import re
import threading


class PostProcessor:
    def __init__(self, trunk):
        self.trunk = trunk

    def merge_group(self, user_input: str, answer: str) -> str:
        try:
            gc = self.trunk._load_lazy("group_chat")
            if gc and hasattr(gc, "compose"):
                return gc.compose(user_input, answer)
        except Exception:
            pass
        return answer

    _CODE_TRIGGERS = ("写", "运行", "实现", "代码", "bug", "修复",
                      "脚本", "程序", "函数", "报错")

    def verify_code(self, user_input: str, answer: str) -> str:
        try:
            if not any(w in user_input for w in self._CODE_TRIGGERS):
                return answer
            if "```python" not in str(answer):
                return answer
            cr = self.trunk._load_lazy("code_runner")
            if not cr:
                return answer
            blocks = re.findall(r"```python\s*\n(.*?)```", str(answer), re.S)
            if not blocks:
                return answer
            res = cr.run(blocks[0][:2000], timeout=8)
            v = "运行成功" if res.get("成功") else "运行失败"
            answer += "\n\n（沙盒验证%s：%s%s）" % (
                v,
                str(res.get("输出", ""))[:120],
                str(res.get("错误", ""))[:80],
            )
            self.trunk._log(f"代码沙盒验证: {v}")
        except Exception as e:
            self.trunk._log(f"代码验证失败: {e}")
        return answer

    def kick_off_background(self, user_input: str, answer: str):
        threading.Thread(
            target=self.trunk._bg,
            args=(user_input, answer),
            daemon=True,
        ).start()

