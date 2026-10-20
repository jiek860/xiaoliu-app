# -*- coding: utf-8 -*-
"""ComputerController 的文件工具 mixin：白名单路径、读写、搜索与编辑。"""
from __future__ import annotations

import json
import os
import re
import shutil
import time


class ComputerFileToolsMixin:
    _TEXT_EXT = (".py", ".md", ".txt", ".json", ".js", ".ts", ".html", ".css",
                 ".yml", ".yaml", ".toml", ".ini", ".cfg", ".bat", ".ps1",
                 ".vbs", ".sql", ".sh", ".log", ".csv", ".xml", ".jsx", ".tsx")
    _SKIP_DIRS = ("__pycache__", ".git", "node_modules", "libs",
                  "optional_libs", "backups", "staging", "browsers", ".venv",
                  "venv", "dist", "build", "data\\_trash_20261010")

    # ---------- 文件操作（白名单） ----------
    def list_dir(self, path=None):
        p = self._safe_path(path or self.base)
        if not p:
            return False, "路径不在白名单内（仅允许项目目录/桌面/下载/文档）"
        try:
            items = os.listdir(p)
            lines = []
            for it in sorted(items)[:50]:
                full = os.path.join(p, it)
                tag = "📁" if os.path.isdir(full) else "  "
                lines.append("%s %s" % (tag, it))
            return True, "目录 %s 共 %d 项：\n%s" % (p, len(items), "\n".join(lines))
        except Exception as e:
            return False, str(e)[:60]

    def create_file(self, path, content=""):
        p = self._safe_path(path)
        if not p:
            return False, "路径不在白名单内"
        # D4: 覆盖已存在文件必须弹窗确认（写错会丢数据）
        if os.path.exists(p) and not self._confirm("覆盖文件", p):
            return False, "已取消覆盖"
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            self._log("create_file", p)
            return True, "已创建文件: " + p
        except Exception as e:
            return False, str(e)[:60]

    def delete_file(self, path):
        p = self._safe_path(path)
        if not p:
            return False, "路径不在白名单内"
        if not os.path.exists(p):
            return False, "文件不存在: " + p
        if not self._confirm("删除文件", p):
            return False, "已取消删除"
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            self._log("delete_file", p, True, "已确认")
            return True, "已删除: " + p
        except Exception as e:
            return False, str(e)[:60]

    def copy_file(self, src, dst):
        s = self._safe_path(src)
        d = self._safe_path(dst)
        if not s or not d:
            return False, "路径不在白名单内"
        # D4: 覆盖已存在目标必须弹窗确认
        if os.path.exists(d) and not self._confirm("覆盖目标文件", d):
            return False, "已取消覆盖"
        try:
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
            self._log("copy_file", "%s -> %s" % (s, d))
            return True, "已复制: %s → %s" % (s, d)
        except Exception as e:
            return False, str(e)[:60]

    def move_file(self, src, dst):
        s = self._safe_path(src)
        d = self._safe_path(dst)
        if not s or not d:
            return False, "路径不在白名单内"
        # D4: 覆盖已存在目标必须弹窗确认
        if os.path.exists(d) and not self._confirm("覆盖目标文件", d):
            return False, "已取消覆盖"
        try:
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.move(s, d)
            self._log("move_file", "%s -> %s" % (s, d))
            return True, "已移动: %s → %s" % (s, d)
        except Exception as e:
            return False, str(e)[:60]

    # ---------- 开发者文件工具：读 / 搜 / 改 ----------
    #
    # 为什么加在这个模块里、而不是新建一个 file_tools 模块：
    # 白名单（self.whitelist）才是"AI 能碰哪些文件"的安全边界，
    # 另起模块就得复制一份白名单策略，两份策略迟早漂移 ——
    # 安全边界只该有一处定义。所以读/搜/改统一走这里的 _safe_path。

    _TEXT_EXT = (".py", ".md", ".txt", ".json", ".js", ".ts", ".html", ".css",
                 ".yml", ".yaml", ".toml", ".ini", ".cfg", ".bat", ".ps1",
                 ".vbs", ".sql", ".sh", ".log", ".csv", ".xml", ".jsx", ".tsx")
    _SKIP_DIRS = ("__pycache__", ".git", "node_modules", "libs", "optional_libs",
                  "backups", "staging", "browsers", ".venv", "venv", "dist",
                  "build", "data\\_trash_20261010")

    def read_text(self, path, start=1, limit=400):
        """读文件内容（带行号）

        必须支持只读一段 —— 长文件一次全读进来会直接塞爆上下文。
        返回 {"ok", "文件", "总行数", "范围", "内容"}。
        """
        p = self._safe_path(str(path or "").strip().strip('"'))
        if not p:
            return {"ok": False, "错误": "路径不在白名单内（仅允许项目目录/桌面/下载/文档；"
                                        "可在 config 的『文件白名单』里加根目录）"}
        if not os.path.isfile(p):
            return {"ok": False, "错误": "不是文件或不存在: " + p}
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception as e:
            return {"ok": False, "错误": "读失败: " + str(e)[:60]}
        try:
            start = max(1, int(start))
            limit = max(1, min(4000, int(limit)))
        except Exception:
            start, limit = 1, 400
        seg = lines[start - 1:start - 1 + limit]
        numbered = "\n".join("%5d| %s" % (start + i, s) for i, s in enumerate(seg))
        self._log("read_text", "%s [%d,%d]" % (p, start, start + len(seg) - 1))
        return {"ok": True, "文件": p, "总行数": len(lines),
                "范围": "%d-%d" % (start, start + len(seg) - 1),
                "内容": numbered}

    def search_text(self, keyword, path=None, max_hits=60):
        """在目录里搜文件内容，返回「文件:行号: 内容」

        纯 Python 实现（os.walk + re），不引入新依赖。
        只搜文本类扩展名、跳过依赖/备份/缓存目录、跳过 >2MB 的大文件。
        """
        kw = str(keyword or "").strip()
        if not kw:
            return {"ok": False, "错误": "没给关键词"}
        root = self._safe_path(str(path).strip()) if path else self.base
        if not root or not os.path.isdir(root):
            return {"ok": False, "错误": "目录不在白名单内或不存在: " + str(path)}
        try:
            pat = re.compile(kw, re.I)
        except Exception:
            pat = re.compile(re.escape(kw), re.I)

        hits, scanned = [], 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in self._SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if not fn.lower().endswith(self._TEXT_EXT):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(fp) > 2 * 1024 * 1024:
                        continue
                except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                    continue
                scanned += 1
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if pat.search(line):
                                hits.append("%s:%d: %s"
                                            % (os.path.relpath(fp, root), i, line.strip()[:120]))
                                if len(hits) >= max_hits:
                                    raise StopIteration
                except StopIteration:
                    break
                except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                    continue
            if len(hits) >= max_hits:
                break
        self._log("search_text", "%s in %s -> %d 命中" % (kw, root, len(hits)))
        return {"ok": True, "根目录": root, "扫描文件数": scanned,
                "命中数": len(hits), "结果": hits}

    def edit_text(self, spec):
        """精确替换文件内容（改前自动备份）

        spec 可以是 dict，也可以是 JSON 字符串（工具调用只传得进一个参数，
        见 tool_caller 的分发方式）：
            {"path": "a.py", "old": "原文", "new": "新文"}
        安全规则：old 必须在文件里**恰好出现一次** —— 出现 0 次或多次都拒绝，
        免得改错地方。这是 DSH edit 的核心语义，比"整体重写文件"安全得多。
        """
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except Exception as e:
                return {"ok": False, "错误": "参数不是合法 JSON: " + str(e)[:50]}
        if not isinstance(spec, dict):
            return {"ok": False, "错误": "参数应为 {path, old, new}"}
        p = self._safe_path(str(spec.get("path", "")).strip().strip('"'))
        old = spec.get("old", "")
        new = spec.get("new", "")
        if not p:
            return {"ok": False, "错误": "路径不在白名单内"}
        if not old:
            return {"ok": False, "错误": "old 不能为空（空串会匹配到任何位置）"}
        if not os.path.isfile(p):
            return {"ok": False, "错误": "文件不存在: " + p}
        try:
            content = open(p, encoding="utf-8").read()
        except Exception as e:
            return {"ok": False, "错误": "读失败: " + str(e)[:60]}
        n = content.count(old)
        if n == 0:
            return {"ok": False, "错误": "原文没找到（注意缩进和换行要完全一致）"}
        if n > 1:
            return {"ok": False, "错误": "原文出现 %d 次，不唯一；请多带几行上下文让它唯一" % n}
        # 备份
        try:
            bdir = os.path.join(self.base, "data", "backups")
            os.makedirs(bdir, exist_ok=True)
            bp = os.path.join(bdir, "%s.%s.bak"
                              % (os.path.basename(p), time.strftime("%Y%m%d_%H%M%S")))
            shutil.copy2(p, bp)
        except Exception as e:
            return {"ok": False, "错误": "备份失败，已放弃修改: " + str(e)[:50]}
        try:
            open(p, "w", encoding="utf-8").write(content.replace(old, new, 1))
        except Exception as e:
            return {"ok": False, "错误": "写入失败: " + str(e)[:60], "备份": bp}
        line_no = content[:content.index(old)].count("\n") + 1
        self._log("edit_text", "%s @L%d" % (p, line_no))
        return {"ok": True, "文件": p, "行": line_no, "备份": bp}

    def try_file(self, text):
        """文件工具的统一入口（收一句话自己解析）

        和 computer_controller.try_handle 同一形状 —— tool_caller 分发时
        只传 list(args.values())[0]，第二个参数传不进来。
        """
        t = str(text or "").strip()
        if not t:
            return {"ok": False, "错误": "没给指令"}
        # 改文件：{"path":…,"old":…,"new":…} 直接吃 JSON
        m = re.search(r"\{.*\}", t, re.S)
        if m and re.search(r"替换|改|修改|edit", t):
            return self.edit_text(m.group(0))
        # 搜内容
        m = re.search(r"(?:搜索|搜|查找|找一下|grep)\s*[：:]?\s*(.+)$", t)
        if m:
            kw = m.group(1).strip().strip('"')
            return self.search_text(kw)
        # 读文件
        m = re.search(r"(?:读|看看|打开|查看|read)\s*[：:]?\s*(.+)$", t)
        if m:
            return self.read_text(m.group(1).strip().strip('"'))
        return {"ok": False, "错误": "没听懂这条文件指令: " + t[:40],
                "可用": "读<路径> / 搜索<关键词> / 替换<JSON:{path,old,new}>"}

    def open_path(self, path):
        p = self._safe_path(path)
        if p and os.path.exists(p):
            try:
                os.startfile(p)
                self._log("open_path", p)
                return True, "已打开: " + p
            except Exception as e:
                return False, str(e)[:60]
        if p:
            return False, "路径不存在: " + p
        return False, "路径不在白名单内"

    def open_url(self, url):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            os.startfile(url)
            self._log("open_url", url)
            return True, "已在浏览器打开: " + url
        except Exception as e:
            return False, str(e)[:60]

