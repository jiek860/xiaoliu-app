# -*- coding: utf-8 -*-
"""P1-5: Docker 沙箱 - 代码执行隔离环境

用法：
  sandbox = DockerSandbox()
  sandbox.run("python script.py")

可选组件：没装 Docker 就自动降级到本地执行。
"""
import subprocess, shutil


class DockerSandbox:
    """Docker 容器沙箱（可选组件）"""
    def __init__(self, image="python:3.12-slim", timeout=30):
        self.image = image
        self.timeout = timeout
        self._available = None

    @property
    def available(self):
        """检测 Docker 是否可用"""
        if self._available is not None:
            return self._available
        if not shutil.which("docker"):
            self._available = False
            return False
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            self._available = r.returncode == 0
        except Exception:
            self._available = False
        return self._available

    def run(self, cmd, workdir=None):
        """在容器里跑命令"""
        if not self.available:
            return {"ok": False, "error": "Docker 不可用，降级到本地", "fallback": True}
        docker_cmd = ["docker", "run", "--rm", "-i"]
        if workdir:
            docker_cmd += ["-v", f"{workdir}:/work", "-w", "/work"]
        docker_cmd += [self.image, "sh", "-c", cmd]
        try:
            r = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=self.timeout)
            return {
                "ok": r.returncode == 0,
                "stdout": r.stdout[:2000],
                "stderr": r.stderr[:2000],
                "returncode": r.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "超时"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def pull(self):
        """拉取镜像"""
        try:
            r = subprocess.run(["docker", "pull", self.image], capture_output=True, timeout=120)
            return {"ok": r.returncode == 0}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
