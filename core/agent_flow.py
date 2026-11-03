# -*- coding: utf-8 -*-
"""P1-06: 智能体执行流程记录与可视化（完整版）

2026-11-02 补的三件事
--------------------
1. **落盘**：原来纯内存（只留 50 条），程序一关就没了，用户/开发者
   都看不到"这轮到底走了哪些步骤"。现在每一步同时写
   ``data/agent_flow/<流程id>.jsonl``（一行一步）。
2. **按流程分开记**：原来一个 list 混着所有任务。现在 ``clear()``
   （``reply_pipeline`` 每轮回复前会调）会开一个新流程 id，
   一轮回复 = 一份流程记录，能单独回看/导出。
3. **步骤状态规范化**：``running/ok/fail/跳过/info``，其他值归到 ``info``，
   状态写错不会让可视化画不出来。

``record_step`` 每轮最多 200 步（超了丢最老的），落盘文件不截断 ——
文件是"这一轮发生了什么"的证据，不该被内存上限切掉。
"""
import json
import os
import time
from datetime import datetime

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

from core.path_safety import safe_join, safe_name

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

STATUSES = ("running", "ok", "fail", "跳过", "info")
MAX_MEMORY_STEPS = 200


class AgentFlow:
    """记录任务执行步骤，供可视化 / 导出"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.dir = data_path(trunk, "agent_flow")
        self.steps = []
        self.flow_id = ""
        self.title = ""
        self.last_error = ""

    # ------------------------------------------------------------------
    def _ensure_dir(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            return ""
        except Exception as e:
            _x6_swallowed(__name__, e, "agent_flow dir")
            return "建不出流程目录：%s: %s" % (type(e).__name__, str(e)[:60])

    def _path(self, flow_id):
        clean = safe_name(flow_id, default="")
        if not clean:
            return None
        return safe_join(self.dir, clean + ".jsonl")

    @staticmethod
    def _norm_status(status):
        text = str(status or "").strip()
        low = text.lower()
        if low in ("running", "ok", "fail"):
            return low
        if text == "跳过":
            return "跳过"
        return "info"

    def start(self, title="", flow_id=None):
        """开一份新流程（不调也行：第一次 record_step 会自动开）"""
        if not flow_id:
            # 带微秒：同一秒内连开两份流程（每轮回复都会 clear 一次）不能撞 id，
            # 撞了就会把这一轮的步骤追加进上一轮的文件里。
            # 注意不能用 strftime("%f")：Windows 的 strftime 不支持 %f。
            now = datetime.now()
            flow_id = now.strftime("flow_%Y%m%d_%H%M%S_") + "%06d" % now.microsecond
        flow_id = safe_name(flow_id, default="flow")
        if not flow_id:
            return {"ok": False, "错误": "流程 id 非法"}
        self.flow_id = flow_id
        self.title = str(title or "")[:80]
        self.steps = []
        return {"ok": True, "流程": flow_id, "标题": self.title}

    def _ensure_flow(self):
        if not self.flow_id:
            self.start()

    def record_step(self, name, status, detail=""):
        """记一步（自动开流程 + 落盘）。返回结构化结果，失败不影响主流程。"""
        self._ensure_flow()
        step_name = str(name or "").strip()
        if not step_name:
            return {"ok": False, "错误": "步骤名为空"}
        step = {"name": step_name[:60],
                "status": self._norm_status(status),
                "detail": str(detail or "")[:200],
                "time": time.strftime("%H:%M:%S"),
                "ts": round(time.time(), 3),
                "flow": self.flow_id}
        self.steps.append(step)
        if len(self.steps) > MAX_MEMORY_STEPS:
            self.steps = self.steps[-MAX_MEMORY_STEPS:]

        err = self._append(step)
        r = {"ok": not err, "步骤数": len(self.steps), "流程": self.flow_id}
        if err:
            r["说明"] = err              # 内存里记着了，只是没落盘
        return r

    def _append(self, step):
        """追加一行到流程文件；失败返回说明（内存记录仍然有效）"""
        path = self._path(self.flow_id)
        if not path:
            return "流程 id 非法，不能落盘"
        err = self._ensure_dir()
        if err:
            self.last_error = err
            return err
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(step, ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e, "agent_flow append")
            self.last_error = "写流程文件失败：%s" % type(e).__name__
            return self.last_error
        return ""

    # ------------------------------------------------------------------
    def get_flow(self, flow_id=None):
        """当前流程（或指定流程）的步骤列表。

        指定 id 时**优先读文件** —— 刚 ``start``、还没记步骤时内存是空的，
        但历史文件里可能已经有内容（导出/回看都靠这个）。
        """
        if flow_id is None:
            return self.steps
        if flow_id == self.flow_id and self.steps:
            return self.steps
        return self._read(flow_id).get("步骤", [])

    def _read(self, flow_id):
        """读一份历史流程；坏行计数但不让整份读不出来"""
        path = self._path(flow_id)
        if not path or not os.path.isfile(path):
            return {"ok": False, "说明": "流程不存在", "步骤": []}
        steps, bad = [], 0
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        step = json.loads(line)
                    except Exception:
                        bad += 1
                        continue
                    if isinstance(step, dict):
                        steps.append(step)
                    else:
                        bad += 1
        except Exception as e:
            return {"ok": False, "说明": "读流程失败：%s" % type(e).__name__,
                    "步骤": []}
        r = {"ok": True, "步骤": steps, "流程": flow_id}
        if bad:
            r["跳过"] = bad
            r["说明"] = "有 %d 行读不出来（已跳过）" % bad
        return r

    def list_flows(self):
        """历史流程清单：{流程, 步骤数, 开始, 更新}"""
        try:
            files = [f for f in os.listdir(self.dir)
                     if f.endswith(".jsonl") and not f.startswith(".")]
        except Exception as e:
            _x6_swallowed(__name__, e, "list flows")
            return []
        out = []
        for name in sorted(files):
            flow_id = name[:-6]
            got = self._read(flow_id)
            steps = got.get("步骤") or []
            first = steps[0].get("time", "") if steps else ""
            last = steps[-1].get("time", "") if steps else ""
            out.append({"流程": flow_id, "步骤数": len(steps),
                        "开始": first, "更新": last,
                        "说明": got.get("说明", "")})
        return out

    def clear(self):
        """每轮回复前清空内存并准备新流程（不动历史文件）"""
        self.steps = []
        self.flow_id = ""
        self.title = ""
        return {"ok": True}

    def delete_flow(self, flow_id):
        path = self._path(flow_id)
        if not path or not os.path.isfile(path):
            return {"ok": False, "错误": "流程不存在或 id 非法"}
        try:
            os.unlink(path)
        except Exception as e:
            _x6_swallowed(__name__, e, "delete flow")
            return {"ok": False, "错误": "删不掉：%s" % str(e)[:60]}
        if flow_id == self.flow_id:
            self.flow_id, self.steps = "", []
        return {"ok": True, "流程": flow_id}

    # ------------------------------------------------------------------
    def to_markdown(self, flow_id=None):
        """一轮流程的步骤表（可视化入口）"""
        target = flow_id or self.flow_id
        steps = self.get_flow(target) if target else []
        lines = ["# 智能体执行流程 %s\n" % (target or "（当前为空）")]
        if not steps:
            lines.append("- 还没有步骤记录\n")
            return "\n".join(lines) + "\n"
        lines.append("| 时间 | 步骤 | 状态 | 详情 |")
        lines.append("|---|---|---|---|")
        for s in steps:
            lines.append("| %s | %s | %s | %s |"
                         % (s.get("time", ""), s.get("name", ""),
                            s.get("status", ""), s.get("detail", "")))
        return "\n".join(lines) + "\n"

    def export_md(self, path=None, flow_id=None):
        """导出流程 md（默认 data/agent_flow_<流程>.md）"""
        target = flow_id or self.flow_id or (
            datetime.now().strftime("flow_%Y%m%d_%H%M%S"))
        path = path or data_path(self.trunk, "agent_flow_%s.md"
                                 % safe_name(target, default="flow"))
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self.to_markdown(target))
            os.replace(tmp, path)
        except Exception as e:
            _x6_swallowed(__name__, e, "export flow md")
            return {"ok": False, "错误": "写不出去：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "文件": path, "流程": target}

    def run(self, *a):
        return {"步骤数": len(self.steps), "当前流程": self.flow_id,
                "历史流程数": len(self.list_flows()),
                "最近": self.steps[-5:]}
