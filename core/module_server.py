# -*- coding: utf-8 -*-
"""模块服务器 v1.0 - 模块仓库 HTTP 服务
所有可下载模块放在 modules_repo/ 目录，本服务提供：
  GET /api/modules          全部模块清单（名称/类/描述/分组/大小/按钮/模型需求/版本）
  GET /api/modules/<name>   单个模块详情
  GET /modules/<name>.py    模块文件下载
默认端口 8899，GUI 启动时自动内嵌启动；也可独立运行：python core/module_server.py
"""
import os, json, threading, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler


class ModuleServer:
    def __init__(self, trunk=None, port=8899):
        self.trunk = trunk
        self.port = int(os.environ.get("MODULE_SERVER_PORT", port))
        self.base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.repo_dir = os.path.join(self.base, "modules_repo")
        self.manifest_path = os.path.join(self.repo_dir, "manifest.json")
        self.server = None
        self._manifest = None

    # ---------- 清单 ----------
    def _load_manifest(self):
        """读 manifest.json（基础信息），实时补 size"""
        if not os.path.exists(self.manifest_path):
            return []
        try:
            # utf-8-sig：兼容被记事本/PowerShell 存成带 BOM 的清单
            data = json.load(open(self.manifest_path, encoding="utf-8-sig"))
        except Exception:
            return []
        for m in data:
            fp = os.path.join(self.repo_dir, m.get("file", ""))
            m["size"] = os.path.getsize(fp) if os.path.exists(fp) else 0
        return data

    def list_modules(self):
        if self._manifest is None:
            self._manifest = self._load_manifest()
        return self._manifest

    def refresh(self):
        """BUG-11: 刷新清单缓存"""
        self._manifest = None
        return self.list_modules()

    def get_module(self, name):
        for m in self.list_modules():
            if m.get("name") == name:
                return m
        return None

    # ---------- HTTP ----------
    def start(self):
        if self.server:
            return "模块服务器已在运行 (端口 %d)" % self.port
        if not os.path.isdir(self.repo_dir):
            os.makedirs(self.repo_dir, exist_ok=True)
        srv = self
        class H(BaseHTTPRequestHandler):
            def _send_json(self, obj, code=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, path):
                if not os.path.exists(path):
                    self._send_json({"error": "模块文件不存在"}, 404)
                    return
                size = os.path.getsize(path)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(size))
                # 文件名可能含中文，必须用 RFC 5987 编码（filename*=UTF-8''...）
                # 直接写中文到 Content-Disposition 会因 latin-1 编码失败导致下载中断
                try:
                    fname = urllib.parse.quote(os.path.basename(path))
                except Exception:
                    fname = "module.py"
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''" + fname)
                self.end_headers()
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)

            def _send_index(self):
                """首页：列出所有模块"""
                mods = srv.list_modules()
                # 按分组聚合
                groups = {}
                for m in mods:
                    g = m.get("group", "其他")
                    groups.setdefault(g, []).append(m)
                rows = []
                for g, ms in sorted(groups.items()):
                    rows.append('<h2>%s <span class="cnt">%d</span></h2>' % (g, len(ms)))
                    for m in ms:
                        kb = m.get("size", 0) / 1024
                        need_model = "🧠" if m.get("needs_model") else ""
                        btn = '<a class="dl" href="/modules/%s.py">下载</a>' % m["name"]
                        rows.append(
                            '<div class="mod"><div class="t">%s %s</div>'
                            '<div class="d">%s</div>'
                            '<div class="m">%.1f KB %s %s</div></div>'
                            % (m.get("title", m["name"]), need_model,
                               m.get("desc", "")[:60], kb, m.get("name", ""), btn))
                html = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>小6模块服务器</title>
<style>
body{font-family:"Microsoft YaHei",sans-serif;max-width:900px;margin:30px auto;padding:0 20px;background:#f7f8fa;color:#1a1a2e}
h1{font-size:24px} h2{font-size:17px;margin:22px 0 8px;color:#334155;border-bottom:1px solid #e2e8f0;padding-bottom:4px}
.cnt{font-size:12px;color:#94a3b8;font-weight:normal}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.mod{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px}
.t{font-weight:600;font-size:15px}
.d{font-size:12px;color:#64748b;margin:4px 0;min-height:16px}
.m{font-size:11px;color:#94a3b8}
.dl{display:inline-block;margin-left:8px;color:#4a9eff;text-decoration:none;border:1px solid #4a9eff;padding:1px 8px;border-radius:4px;font-size:11px}
.dl:hover{background:#4a9eff;color:#fff}
.ok{color:#16a34a}
</style></head><body>
<h1>📦 小6模块服务器 <span class="ok">● 运行中</span></h1>
<p>仓库共 <b>%d</b> 个模块。GUI 里的插件市场会自动从这里下载。</p>
%s
</body></html>""" % (len(mods), "\n".join(rows))
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                try:
                    path = urllib.parse.urlparse(self.path).path
                    if path == "/":
                        self._send_index()
                    elif path == "/api/modules":
                        self._send_json({"modules": srv.list_modules(), "server": "ok"})
                    elif path.startswith("/api/modules/"):
                        name = urllib.parse.unquote(path[len("/api/modules/"):])
                        m = srv.get_module(name)
                        if m:
                            self._send_json(m)
                        else:
                            self._send_json({"error": "模块不存在: " + name}, 404)
                    elif path.startswith("/modules/") and path.endswith(".py"):
                        name = urllib.parse.unquote(path[len("/modules/"):-3])
                        m = srv.get_module(name)
                        fp = os.path.join(srv.repo_dir, m["file"]) if m else ""
                        if m and os.path.exists(fp):
                            self._send_file(fp)
                        else:
                            self._send_json({"error": "文件不存在"}, 404)
                    elif path == "/api/health":
                        self._send_json({"ok": True, "port": srv.port, "repo": srv.repo_dir})
                    else:
                        self._send_json({"error": "未知接口"}, 404)
                except Exception as e:
                    try:
                        self._send_json({"error": str(e)[:100]}, 500)
                    except Exception:
                        pass

            def log_message(self, *a):
                pass
        try:
            self.server = HTTPServer(("127.0.0.1", self.port), H)
        except OSError as e:
            return "模块服务器启动失败: %s" % str(e)[:80]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return "模块服务器已启动: http://127.0.0.1:%d （仓库 %d 个模块）" % (self.port, len(self.list_modules()))

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server = None

    def search_modules(self, keyword):
        """搜索模块"""
        all_mods = self.list_modules()
        found = [m for m in all_mods
                 if keyword in m.get("name", "") or keyword in m.get("desc", "")]
        return {"找到": len(found), "结果": found}

    def get_module_stats(self):
        """模块统计"""
        all_mods = self.list_modules()
        total_size = sum(m.get("size", 0) for m in all_mods)
        return {"模块总数": len(all_mods), "总大小KB": total_size // 1024}

    def is_running(self):
        """检查服务器是否运行"""
        return self.server is not None

    def run(self, *a):
        if a and a[0] == "stop":
            self.stop()
            return "模块服务器已停止"
        return self.start()


if __name__ == "__main__":
    s = ModuleServer()
    print(s.start())
    print("按 Ctrl+C 停止")
    import time
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        s.stop()
        print("已停止")
