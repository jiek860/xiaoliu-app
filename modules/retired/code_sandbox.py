# -*- coding: utf-8 -*-
"""v26-6.3: 代码执行沙箱 完整版"""
import subprocess, tempfile, os, shutil


class CodeSandbox:
    """Docker沙箱执行，带Docker检测和回退"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def _docker_available(self):
        """检测Docker是否可用"""
        try:
            r = subprocess.run(["docker", "version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def run_docker(self, code, timeout=15):
        """Docker沙箱执行"""
        if not self._docker_available():
            return {"错误": "Docker不可用", "回退": True}

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
        try:
            r = subprocess.run([
                "docker", "run", "--rm",
                "--network=none",
                "--memory=256m",
                "--cpus=1",
                "--read-only",
                "--tmpfs", "/tmp:rw,size=64m",
                "-v", tmp + ":/app/code.py:ro",
                "python:3.12-slim",
                "python", "/app/code.py"
            ], capture_output=True, text=True, timeout=timeout)
            return {
                "stdout": r.stdout[:500],
                "stderr": r.stderr[:500],
                "returncode": r.returncode,
                "沙箱": "Docker",
                "隔离": ["无网络", "256MB内存", "1CPU", "只读文件系统"],
            }
        except subprocess.TimeoutExpired:
            return {"错误": "执行超时", "沙箱": "Docker"}
        except Exception as e:
            return {"错误": str(e)[:80], "回退": True}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def run_subprocess(self, code, timeout=10):
        """回退：本地subprocess执行（带关键词过滤）"""
        dangerous = ["os.system", "shutil.rmtree", "subprocess.call", "eval(", "exec("]
        for d in dangerous:
            if d in code:
                return {"错误": "检测到危险操作: " + d}
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
        try:
            r = subprocess.run(["python", tmp], capture_output=True, text=True, timeout=timeout)
            return {
                "stdout": r.stdout[:500],
                "stderr": r.stderr[:500],
                "returncode": r.returncode,
                "沙箱": "本地subprocess（回退）",
            }
        except Exception as e:
            return {"错误": str(e)[:80]}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def run(self, code=None, timeout=10):
        """自动选择沙箱模式"""
        if code is None:
            return {"沙箱": "就绪", "Docker可用": self._docker_available()}
        # 先试Docker，不行回退本地
        r = self.run_docker(code, timeout)
        if not r.get("回退"):
            return r
        return self.run_subprocess(code, timeout)
