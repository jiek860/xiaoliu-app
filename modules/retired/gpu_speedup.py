# -*- coding: utf-8 -*-
"""v26-5.1: GPU加速自动检测"""
import subprocess, platform


class GPUSpeedup:
    """检测GPU并自动配置加速"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def detect(self):
        result = {"cuda": False, "gpu_name": "", "recommend": "CPU"}
        try:
            import torch
            if torch.cuda.is_available():
                result["cuda"] = True
                result["gpu_name"] = torch.cuda.get_device_name(0)
                result["recommend"] = "CUDA"
        except ImportError:
            pass

        # 检测nvidia-smi
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                result["cuda"] = True
                result["gpu_name"] = r.stdout.decode().strip()
                result["recommend"] = "CUDA"
        except Exception:
            pass

        return result

    def run(self, *a):
        return self.detect()
