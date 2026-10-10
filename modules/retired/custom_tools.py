# -*- coding: utf-8 -*-
"""v26-7.3: 自定义工具 完整版"""
import os, json, requests, subprocess


class CustomTools:
    """用户自定义HTTP/Python/Shell工具"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "custom_tools.json")
        self.tools = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self):
        tmp = self.path + ".tmp"
        json.dump(self.tools, open(tmp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def add_http(self, name, desc, url, method="GET"):
        self.tools.append({"name": name, "desc": desc, "type": "http",
                           "url": url, "method": method.upper()})
        self._save()
        return {"ok": True}

    def add_shell(self, name, desc, cmd):
        self.tools.append({"name": name, "desc": desc, "type": "shell", "cmd": cmd})
        self._save()
        return {"ok": True}

    def add_python(self, name, desc, code):
        self.tools.append({"name": name, "desc": desc, "type": "python", "code": code})
        self._save()
        return {"ok": True}

    def call(self, name, args=None):
        """调用自定义工具"""
        t = next((x for x in self.tools if x["name"] == name), None)
        if not t:
            return {"错误": "工具不存在"}
        args = args or {}
        if t["type"] == "http":
            return self._call_http(t, args)
        elif t["type"] == "shell":
            return self._call_shell(t, args)
        elif t["type"] == "python":
            return self._call_python(t, args)

    def _call_http(self, t, args):
        url = t["url"]
        for k, v in args.items():
            url = url.replace("{{%s}}" % k, str(v))
        try:
            if t["method"] == "GET":
                r = requests.get(url, timeout=15)
            else:
                r = requests.post(url, json=args, timeout=15)
            return {"status": r.status_code, "body": r.text[:500]}
        except Exception as e:
            return {"错误": str(e)[:80]}

    def _call_shell(self, t, args):
        cmd = t["cmd"]
        for k, v in args.items():
            cmd = cmd.replace("{{%s}}" % k, str(v))
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return {"stdout": r.stdout[:500], "stderr": r.stderr[:500], "code": r.returncode}
        except Exception as e:
            return {"错误": str(e)[:80]}

    def _call_python(self, t, args):
        try:
            loc = {"args": args}
            exec(t["code"], {"__builtins__": __builtins__}, loc)
            return {"result": loc.get("result", "执行完成")}
        except Exception as e:
            return {"错误": str(e)[:80]}

    def list_tools(self):
        return self.tools

    def delete(self, name):
        self.tools = [t for t in self.tools if t["name"] != name]
        self._save()
        return {"ok": True}

    def run(self, *a):
        return {"自定义工具数": len(self.tools), "类型": ["http", "shell", "python"]}
