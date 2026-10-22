# -*- coding: utf-8 -*-
"""回复后处理：群聊合并 + 代码沙盒验证 + 触发后台闭环"""
import re
import threading


class PostProcessor:
    def __init__(self, trunk):
        self.trunk = trunk

    def merge_group(self, user_input: str, answer: str, prefetch=None) -> str:
        """合并群聊角色的补充发言

        prefetch: group_chat.start_roles() 的返回值 —— 那是**在生成主回复之前**
                  就发出去的角色回复，走到这里基本已经跑完，不用再等十几秒。
        """
        gc = None
        try:
            gc = self.trunk._load_lazy("group_chat")
        except Exception:
            return answer
        if not gc or not hasattr(gc, "compose"):
            return answer
        try:
            return gc.compose(user_input, answer, prefetch=prefetch)
        except TypeError:
            # 老版本的 compose 不认 prefetch —— 退回不带它调
            try:
                return gc.compose(user_input, answer)
            except Exception:
                return answer
        except Exception:
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
            # 兼容两种返回契约：新版有 "成功"，旧版只有 returncode。
            ok = res.get("成功")
            if ok is None:
                ok = res.get("returncode") == 0
            out = str(res.get("输出") or res.get("stdout") or "")
            err = str(res.get("错误") or res.get("stderr") or "")
            # ⚠️ 判断顺序很重要：先处理"成功但无输出"，
            #    因为 code_runner 对无输出会返回 "(无输出)" 占位字符串，
            #    只判断 not out.strip() 会漏掉它。
            if ok and (not out.strip() or out.strip() == "(无输出)"):
                # 只有函数定义、没有任何输出：代码本身没问题，
                # 但"验证"没有实际执行到逻辑，明确告知而不是报"失败"。
                v = "通过（仅定义未调用，未产生输出）"
            else:
                v = "运行成功" if ok else "运行失败"
            answer += "\n\n（沙盒验证%s：%s%s）" % (
                v, out[:120], err[:80])
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

