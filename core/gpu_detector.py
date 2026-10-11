# -*- coding: utf-8 -*-
"""P2-20: GPU加速检测"""
import subprocess, platform


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
        except Exception:
            pass
        return info

    def run(self, *a):
        return self.detect()
