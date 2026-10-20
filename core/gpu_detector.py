# -*- coding: utf-8 -*-
"""P2-20: GPU加速检测"""
import subprocess, platform

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class GPUDetector:
    """检测GPU并报告"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def detect(self):
        """检测GPU"""
        info = {
            "NVIDIA": False,
            "显存": "未知",
            "推荐后端": "CPU",
        }
        try:
            if platform.system() == "Windows":
                # 用nvidia-smi检测
                r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                   capture_output=True, timeout=5)
                if r.returncode == 0:
                    out = r.stdout.decode().strip()
                    info["NVIDIA"] = True
                    info["GPU型号"] = out.split(",")[0].strip()
                    info["显存"] = out.split(",")[1].strip()
                    info["推荐后端"] = "CUDA"
        except Exception as e:
            # 这里静默是**故意的，别改**（2026-10-13 审计时确认）：
            # 走这条分支的典型情况是"机器上没有 nvidia-smi / 不是 N 卡"——
            # 那是**正常结果**（没独显也是合法配置），不是错误。
            # 报出来只会让每次自检都刷一条无意义的告警，
            # 真正的"有卡但检测失败"会体现在返回值 info 里（NVIDIA=False）。
            _x6_swallowed(__name__, e, "best-effort fallback")
        return info

    def run(self, *a):
        return self.detect()
