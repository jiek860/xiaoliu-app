# -*- coding: utf-8 -*-
"""P2-20: GPU 加速检测（完整版）

原来只有三个键（NVIDIA / 显存 / 推荐后端），失败时一律返回"没卡" ——
于是「这台机器真的没有 N 卡」和「有卡但 nvidia-smi 卡住/报错」在结果里
长得一模一样，用户问"我能跑本地模型吗"时拿到的是同等模糊的答案。

现在返回结构化状态（2026-11-02 补）：

    {"NVIDIA": False, "GPU型号": ..., "显存": ..., "推荐后端": "CPU",
     "状态": "ok" | "无显卡" | "检测失败", "检测方式": "nvidia-smi",
     "说明": 可选}

- ``ok``      查到卡了，可跑 CUDA
- ``无显卡``  没有 nvidia-smi（不是 N 卡 / 没装驱动）—— **正常结果**
- ``检测失败`` 有工具但超时/输出看不懂（这个值得看一眼）

结果按实例缓存 ``CACHE_TTL`` 秒：``detect()`` 会被自检、设置页、工具调用
各调一遍，每次都跑一次子进程没必要；想强制刷新就传 ``refresh=True``。

仍然**不抛异常**：调用方（自检/工具）不该因为显卡检测把整条链路带崩。
"""
import platform
import subprocess
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

CACHE_TTL = 300          # 秒；显卡不会在会话中途插拔
CMD_TIMEOUT = 5


class GPUDetector:
    """检测 GPU 并报告（结构化 + 实例级缓存）"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self._cache = None
        self._cache_at = 0.0

    # ------------------------------------------------------------------
    def _blank(self):
        return {"NVIDIA": False, "GPU型号": "未知", "显存": "未知",
                "推荐后端": "CPU", "检测方式": "nvidia-smi",
                "状态": "无显卡"}

    def _detect_once(self):
        info = self._blank()
        system = platform.system()
        if system not in ("Windows", "Linux"):
            info["说明"] = "%s 上不做 GPU 检测（按 CPU 规划）" % system
            return info
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader"],
                capture_output=True, timeout=CMD_TIMEOUT)
        except FileNotFoundError:
            info["说明"] = ("没找到 nvidia-smi（没装 N 卡驱动，或本来就不是 N 卡）"
                            "—— 这是正常结果，不影响使用")
            return info
        except subprocess.TimeoutExpired:
            info["状态"] = "检测失败"
            info["说明"] = "nvidia-smi 超时 %d 秒（驱动卡住了？）" % CMD_TIMEOUT
            return info
        except Exception as e:
            # 这里静默是**故意的，别改**（2026-10-13 审计确认 + 2026-11-02 复核）：
            # 典型情况就是"没有 nvidia-smi / 不是 N 卡"，那是**正常结果**，
            # 报出来只会让每次自检都刷一条无意义告警。
            # 真正需要人看的情况现在由返回值里的「状态」表达（无显卡 / 检测失败）。
            _x6_swallowed(__name__, e, "gpu detect")
            info["说明"] = "检测没跑起来：%s" % type(e).__name__
            return info

        if r.returncode != 0:
            info["状态"] = "检测失败"
            detail = (r.stderr or b"").decode("utf-8", "ignore").strip()
            info["说明"] = "nvidia-smi 返回 %d：%s" % (
                r.returncode, (detail or "无输出")[:100])
            return info

        out = (r.stdout or b"").decode("utf-8", "ignore").strip()
        first = out.splitlines()[0] if out else ""
        parts = [p.strip() for p in first.split(",")]
        if not parts or not parts[0]:
            info["状态"] = "检测失败"
            info["说明"] = "nvidia-smi 输出看不懂：%s" % (out[:100] or "空")
            return info

        info["NVIDIA"] = True
        info["GPU型号"] = parts[0]
        info["显存"] = parts[1] if len(parts) > 1 and parts[1] else "未知"
        info["推荐后端"] = "CUDA"
        info["状态"] = "ok"
        return info

    # ------------------------------------------------------------------
    def detect(self, refresh=False):
        """检测（默认走 5 分钟缓存；``refresh=True`` 强制重跑）"""
        now = time.time()
        if (not refresh and self._cache is not None
                and now - self._cache_at < CACHE_TTL):
            cached = dict(self._cache)
            cached["缓存"] = True
            return cached
        info = self._detect_once()
        self._cache = dict(info)
        self._cache_at = now
        return info

    def recommend(self, refresh=False):
        """只取「推荐后端」（CUDA / CPU）"""
        return self.detect(refresh=refresh).get("推荐后端", "CPU")

    def summary(self, refresh=False):
        """一句人话，给设置页/自检用"""
        info = self.detect(refresh=refresh)
        if info.get("状态") == "ok":
            return "%s（%s），可以跑 CUDA" % (info.get("GPU型号"), info.get("显存"))
        if info.get("状态") == "检测失败":
            return "显卡检测失败：%s" % str(info.get("说明") or "")
        return "没有可用 N 卡，按 CPU 跑"

    def run(self, *a):
        return self.detect()
