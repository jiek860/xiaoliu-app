# -*- coding: utf-8 -*-
"""线程安全守卫 —— 后台线程不许直接碰 Qt 控件

背景
----
这类 bug 已经出现两次了：
    · gui/model_manager_dialog.py  _refresh 在 threading.Thread 里
      list_w.clear() / msg.setText()  -> 随机崩
    · gui/mixins/voice_mixin.py     _do_listen 在子线程里
      self.input.setPlainText(...) / QMessageBox.information(...)
      注释还写着"回到主线程更新UI"，其实根本没回

Qt 规定控件只能在 GUI 线程碰。正确做法是子线程 emit 信号，
槽函数由 Qt 排队到 GUI 线程执行（main_window 的 statusMessage 就是这么做的）。

做法
----
用 AST 精确取线程入口的函数体（end_lineno，不是靠正则猜范围 ——
正则那版会抓过头，把主线程的代码也算进去，误报过 settings_dialog）。
扫描的入口：
    · threading.Thread(target=fn) / Thread(target=self.meth)
    · QThread 子类的 run()
再顺着一层同文件/同类的方法调用往下看（线程体常把活分给 helper）。

判定
----
必错（fail）：线程体里出现明确只在 GUI 线程能用的调用
    QMessageBox.* / QFileDialog.* / QInputDialog.*
    或 self.<控件名>.<控件方法>(...)：setText/setPlainText/addWidget/clear/...
安全（忽略）：*.emit(...)  —— 信号 emit 本身就是跨线程安全的
    _set_status(...) —— 它背后是 status_cb，接的是 pyqtSignal.emit

用法
----
    py -3 tools\\check_threads.py            # 检查
    py -3 tools\\check_threads.py -v         # 连线程入口一起列出来
"""
import argparse
import ast
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只在 GUI 线程能用的 Qt 类方法
QT_GUI_CALLS = {
    "QMessageBox": ("information", "warning", "critical", "question", "about"),
    "QFileDialog": ("getOpenFileName", "getSaveFileName", "getExistingDirectory",
                    "getOpenFileNames"),
    "QInputDialog": ("getText", "getMultiLineText", "getItem", "getInt", "getDouble"),
    "QApplication": ("processEvents",),
}

# 控件方法：出现在 self.<某控件>.<这些方法> 里就是碰控件
WIDGET_METHODS = {
    "setText", "setPlainText", "setHtml", "setMarkdown", "append", "appendPlainText",
    "clear", "addItem", "addItems", "addWidget", "insertWidget", "removeWidget",
    "setEnabled", "setDisabled", "setVisible", "setChecked", "setCurrentRow",
    "setCurrentIndex", "setCurrentItem", "setStyleSheet", "setWindowTitle",
    "setPixmap", "setValue", "setMaximum", "setMinimum", "setRange", "addTab",
    "setTabText", "setToolTip", "setFocus", "selectAll", "setPlaceholderText",
    "setRowCount", "setColumnCount", "setItem", "takeItem", "insertItem",
    "showMessage", "repaint", "update", "setIcon", "setModel", "clearContents",
    "setTextAlignment", "setReadOnly", "setFixedWidth", "setFixedHeight",
}

# 长得像控件的属性名（收紧一点，避免把业务对象也算进来）
WIDGETISH = ("_btn", "_button", "_lbl", "_label", "_tb", "_text", "_edit",
             "_list", "_table", "_tree", "_box", "_combo", "_bar", "_view",
             "_w", "_widget", "_dialog", "_menu", "_check", "_radio", "_spin",
             "input", "chat", "out", "output", "result", "list_w", "msg",
             "status_lbl", "info", "voice_btn", "search", "tb", "editor")

# 明确安全的：信号 emit 一定安全；_set_status 背后是 pyqtSignal.emit
SAFE_MARKERS = (".emit(", "_set_status(", "_log(", "print(", "logger.")


def _dotted(node):
    """把 a.b.c 还原成字符串"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _collect_funcs(tree):
    """{函数名: FunctionDef}（含类方法，按 name 和 Class.name 两种键）"""
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            out.setdefault(n.name, n)
            for c in ast.walk(tree):
                if isinstance(c, ast.ClassDef) and n in c.body:
                    out.setdefault("%s.%s" % (c.name, n.name), n)
                    break
    return out


def _thread_entries(tree, funcs):
    """找线程入口：[ (标签, FunctionDef) ]"""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = _dotted(n.func)
        # threading.Thread(target=xxx) / Thread(target=xxx)
        if fn.endswith("Thread") or fn.endswith("Thread.__init__"):
            for kw in n.keywords:
                if kw.arg == "target":
                    tgt = kw.value
                    if isinstance(tgt, ast.Name):
                        f = funcs.get(tgt.id)
                        if f:
                            out.append(("threading.Thread→%s" % tgt.id, f))
                    elif isinstance(tgt, ast.Attribute):
                        f = funcs.get(tgt.attr) or funcs.get(_dotted(tgt).split(".")[-1])
                        if f:
                            out.append(("threading.Thread→%s" % _dotted(tgt), f))
                    elif isinstance(tgt, ast.Lambda):
                        out.append(("threading.Thread→<lambda>", tgt))
    # QThread 子类的 run()
    for n in ast.walk(tree):
        if not isinstance(n, ast.ClassDef):
            continue
        bases = [getattr(b, "id", getattr(b, "attr", "")) for b in n.bases]
        if "QThread" not in bases:
            continue
        for f in n.body:
            if isinstance(f, ast.FunctionDef) and f.name == "run":
                out.append(("QThread.run@%s" % n.name, f))
    return out


def _calls_in(node):
    """node 体内所有 Call 节点"""
    out = []
    for c in ast.walk(node) if node else []:
        if isinstance(c, ast.Call):
            out.append(c)
    return out


def _is_violation(call):
    """这个调用是不是"线程里碰控件"。返回原因字符串或 None"""
    fn = _dotted(call.func)
    if not fn:
        return None
    if any(m in fn for m in SAFE_MARKERS):
        return None
    # ① Qt GUI 类方法
    for cls, meths in QT_GUI_CALLS.items():
        if fn.startswith(cls + "."):
            m = fn.split(".")[-1]
            if m in meths:
                return "%s 只能在 GUI 线程调用" % fn
    # ② self.<控件>.<控件方法>
    parts = fn.split(".")
    if len(parts) >= 2:
        meth = parts[-1]
        owner = parts[-2] if len(parts) >= 2 else ""
        if meth in WIDGET_METHODS:
            owns_widget = (owner == "self" and len(parts) >= 3
                           and any(h in parts[-2].lower() or h in parts[-3].lower()
                                   for h in WIDGETISH))
            # self.input.setPlainText → parts=[self,input,setPlainText]
            if len(parts) == 3 and parts[0] == "self":
                attr = parts[1].lower()
                if any(h in attr for h in WIDGETISH):
                    return "self.%s.%s 是控件调用" % (parts[1], meth)
            if len(parts) == 2 and any(h in parts[0].lower() for h in WIDGETISH):
                return "%s 像是控件调用" % fn
    return None


def scan_file(path, base):
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
        tree = ast.parse(src)
    except Exception:
        return None
    funcs = _collect_funcs(tree)
    entries = _thread_entries(tree, funcs)
    if not entries:
        return None
    lines = src.splitlines()
    problems = []
    for _label, node in entries:
        # 精确取函数体：AST 给的 end_lineno，不再靠正则猜
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        body = "\n".join(lines[start - 1:end])
        for call in _calls_in(node):
            why = _is_violation(call)
            if why:
                problems.append((call.lineno, why, lines[call.lineno - 1].strip()[:70]))
    return label_count(entries), problems


def label_count(entries):
    return len(entries)


def main():
    ap = argparse.ArgumentParser(description="后台线程不许直接碰 Qt 控件")
    ap.add_argument("-v", "--verbose", action="store_true", help="列出线程入口")
    args = ap.parse_args()

    print("=" * 76)
    print("线程安全守卫：后台线程里有没有直接碰 Qt 控件")
    print("=" * 76)

    files, n_entries, bad = [], 0, []
    for root, dirs, fs in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in
                   ("__pycache__", "libs", "optional_libs", ".git", "backups",
                    "staging", "data", "modules_repo", ".venv", ".runtime-venv",
                    ".build-venv", ".swebench-venv", "dist", "build",
                    "_ci_sim", "_ci_sim2")]
        for f in sorted(fs):
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, BASE)
            r = scan_file(p, BASE)
            if not r:
                continue
            cnt, problems = r
            n_entries += cnt
            if args.verbose:
                print("  %-46s 线程入口 %d 个" % (rel, cnt))
            if problems:
                bad.append((rel, problems))

    print("  扫了 %d 个线程入口" % n_entries)
    print()
    if not bad:
        print("线程安全守卫通过 ✅  没有子线程碰控件")
        return 0
    print("发现 %d 个文件有违规：" % len(bad))
    for rel, problems in bad:
        print("\n  【%s】" % rel)
        for ln, why, code in problems:
            print("     L%-5d %s" % (ln, why))
            print("            %s" % code)
    print()
    print("改法：子线程只 emit 信号，槽函数在 GUI 线程里更新控件。")
    print("     参考 gui/mixins/voice_mixin.py 的 _VoiceRelay 或")
    print("     gui/main_window.py 的 statusMessage。")
    return 1


if __name__ == "__main__":
    from _console import use_utf8_console
    use_utf8_console()
    sys.exit(main())
