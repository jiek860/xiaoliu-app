# -*- coding: utf-8 -*-
"""反馈时自动收集的日志摘要（脱敏 + 截断 + 给出日志路径）

为什么只挑错误行、不整包发
--------------------------
  - trunk.log / app.log 里可能有用户聊天内容，整包发等于把隐私传出去
  - 飞书群机器人单条消息有长度上限
  - 排查真正需要的是：最后几条错误 + 崩溃现场 + 系统信息 + 日志路径

所以这里只做三件事：
  1. 从 data/logs/ 挑 ERROR/WARN/崩溃现场（只读文件尾部，不加载整个大文件）
  2. 把密钥类内容脱敏（webhook / sk- / Bearer / key=... 等）
  3. 截断到安全长度，并给出**日志文件的绝对路径**（方便定位）
"""
import os
import platform
import re
import threading
import time

MAX_CHARS = 3000            # 摘要正文上限
TAIL_BYTES = 200 * 1024     # 每个文件最多读尾部 200 KB

# (标签, 文件名, 取法, 最多行)
LOG_SPECS = [
    ("崩溃", "crashes.log", "error", 30),
    ("GUI崩溃", "gui_crashes.log", "error", 30),
    ("线程现场", "faulthandler.log", "faulthandler", 30),
    ("运行日志", "app.log", "error", 25),
    ("主日志", "trunk.log", "error", 25),
    ("电脑控制", "computer_controller.log", "error", 15),
]

_ERR_HINT = re.compile(
    r"(\[ERROR\]|\[WARN|Traceback|Exception|Error|失败|错误|异常|崩溃|超时|timeout)",
    re.I)

# (正则, 替换)  按"长得像什么"脱敏，不按名单，避免将来加新密钥时漏
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.I), r"\1***"),
    (re.compile(r"((?:key|token|secret|passwd|password)=)[^&\s\"']+", re.I),
     r"\1***"),
    (re.compile(r"(/hook/)[A-Za-z0-9\-]{8,}"), r"\1***"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "***"),
]


def redact(text):
    """把文本里的密钥类内容打码"""
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _read_tail(path, max_bytes=TAIL_BYTES):
    """只读文件尾部（trunk.log 有 3~4 MB，没必要整读）"""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", "replace")


def _pick(text, mode, max_lines):
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if mode == "error":
        lines = [ln for ln in lines if _ERR_HINT.search(ln)]
    elif mode == "faulthandler":
        # 只取最近一次启动之后的内容。测试进程和主程序共用这个文件，
        # 如果直接取文件末尾，可能把 pytest 的历史栈误当成这次启动的崩溃现场。
        starts = list(re.finditer(r"(?m)^启动 \d{4}-\d{2}-\d{2} .*?pid=\d+.*$",
                                  text))
        section = text[starts[-1].start():] if starts else text
        # 最近一次启动后只有分隔线 / 启动信息，没有线程栈，说明这次没崩。
        # 注意：faulthandler 的栈标志是 "Current thread" / "Thread 0x"；
        # 手动 dump 则带 "[手动 dump]"。
        stack_marks = ("Current thread", "Thread 0x", "[手动 dump]")
        if not any(m in section for m in stack_marks):
            return []
        lines = [ln.rstrip() for ln in section.splitlines() if ln.strip()]
    # 单行太长（比如整段 JSON 打一行）就截断，免得一条顶满额度
    lines = [ln[:220] for ln in lines]
    return lines[-max_lines:]


def _kb(n):
    return "%.1f KB" % (n / 1024.0)


def collect(base, max_chars=MAX_CHARS):
    """收集日志摘要

    返回 {"ok", "text", "files", "logs_dir", "truncated"}
        text   : 已脱敏 + 已截断的摘要正文
        files  : [{"name","path","size","exists"}]  这就是"定位地址"
    """
    logs_dir = os.path.join(base, "data", "logs")
    files = []
    chunks = []

    try:
        from core.version import __version__
    except ImportError:
        __version__ = "?"

    chunks.append("==== 日志摘要（自动附带）====")
    chunks.append("系统: %s" % platform.platform())
    chunks.append("Python: %s" % platform.python_version())
    chunks.append("小6版本: %s" % __version__)
    chunks.append("时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    chunks.append("线程数: %d" % threading.active_count())
    chunks.append("日志目录: %s" % logs_dir)
    chunks.append("")

    for label, fname, mode, n in LOG_SPECS:
        p = os.path.join(logs_dir, fname)
        if not os.path.exists(p):
            files.append({"name": fname, "path": p, "size": 0, "exists": False})
            continue
        size = os.path.getsize(p)
        files.append({"name": fname, "path": p, "size": size, "exists": True})
        if size == 0:
            chunks.append("[%s] %s（空文件，没崩过）" % (label, fname))
            continue
        try:
            tail = _read_tail(p)
        except OSError as e:
            chunks.append("[%s] %s（读不了：%s）" % (label, fname, str(e)[:40]))
            continue
        picked = _pick(tail, mode, n)
        if not picked:
            chunks.append("[%s] %s（%s，最近没有错误）" % (label, fname, _kb(size)))
            continue
        chunks.append("[%s] %s（%s，最后 %d 条）："
                      % (label, fname, _kb(size), len(picked)))
        chunks.extend("  " + ln for ln in picked)
        chunks.append("")

    # 位置信息单独拼，**不参与截断** 
    # 用户要"定位地址"，这段被截掉就白做了
    footer = ["==== 日志位置 ====", logs_dir]
    for f in files:
        footer.append("  %-24s %s"
                      % (f["name"], _kb(f["size"]) if f["exists"] else "不存在"))

    body = redact("\n".join(chunks)).rstrip()
    foot = redact("\n".join(footer))
    room = max_chars - len(foot) - 40
    truncated = len(body) > room
    if truncated:
        body = body[:max(0, room)] + "\n（摘要已截断）"
    text = body + "\n\n" + foot
    return {"ok": True, "text": text, "files": files,
            "logs_dir": logs_dir, "truncated": truncated}
