# -*- coding: utf-8 -*-
"""提交前检查 —— git hook 真正干活的地方（跨平台，Windows/Linux 都能跑）

为什么分两档
------------
实测各守卫耗时（本机）：
    check_version   0.2 秒      check_buttons  0.2 秒
    check_tools     1.4 秒      check_threads  1.6 秒
    check_signals   1.6 秒      compileall      ~2  秒
    check_dead_code 6.4 秒      check_shapes  11.9 秒
    pytest          ~70 秒

每次都跑全套的话，提交要等 90 秒 —— 那样的 hook 用户会想办法绕过去
（--no-verify），等于没有。所以分两档：

    pre-commit  只跑快检（约 45 秒） —— 拦"明显不该提交的"
    pre-push    跑全套（约 85 秒） —— 拦"能跑但有问题的"

用法
----
    py -3 tools\\pre_commit_check.py            # pre-commit 档（默认，10 项）
    py -3 tools\\pre_commit_check.py --full     # pre-push 档（13 项，含 pytest）
    py -3 tools\\pre_commit_check.py --install  # 装 hook 到本仓库

B7（2026-11-02）：`懒加载来源` 升为**关键守卫**（REQUIRED），和语法/版本/静默
一起固定住 —— 这几项被删掉时本脚本直接失败，避免"门禁被优化没了还是全绿"。
S4（2026-11-02）：新增 `死代码棘轮`（`check_dead_code.py`）与 `信号接线`
（`check_signals.py`），同样进 REQUIRED —— 这两类退化（零引用函数长回来、
假信号没人接）跑测试是看不出来的。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import argparse
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 必须是**字符串**：写成 [sys.executable] 再嵌进 CHECKS 的列表里会变成嵌套列表，
# subprocess 直接 TypeError: expected str, bytes or os.PathLike object, not list
PY = sys.executable or "py"

# (标签, 命令, 属于哪一档)  full=True 表示只在 --full 时跑
CHECKS = [
    ("语法检查", [PY, "-m", "compileall", "-q", "core", "gui", "modules",
                  "modules_repo", "tools", "scripts", "tests"], False),
    ("版本号一致性", [PY, "tools/check_version.py"], False),
    ("按钮预算", [PY, "tools/check_buttons.py"], False),
    ("工具/提示词预算", [PY, "tools/check_tools.py"], False),
    ("线程安全", [PY, "tools/check_threads.py"], False),
    # 静默失败棘轮：存量冻结（357 处），新增要说明理由。
    # 放 pre-commit 是因为它只做 AST 扫描，很快（约 1 秒）。
    ("静默失败棘轮", [PY, "tools/check_silent.py"], False),
    # 懒加载来源：核对 LAZY_MAP 每条登记的文件确实在对应目录（快，纯文件存在性）
    # B7 起列为**关键守卫**：它一挂，说明有模块登记错位/文件丢了，
    # 那种状态下跑测试也看不出"用户点按钮会加载失败"。见下面 REQUIRED。
    ("懒加载来源", [PY, "tools/check_lazy_sources.py"], False),
    # 数据路径棘轮（S2）：第一方代码里手拼 base/data 的处数只许降。
    # 起点 190 处 / 130 文件，迁移完 85 处后基线 105 / 79；新增一处就拦下。
    ("数据路径棘轮", [PY, "tools/check_data_paths.py"], False),
    # 死代码棘轮（S4）：可疑死模块 / 零引用函数 / 完全重复实现 只许降（基线 0/0/0）。
    # 6.4 秒（要 tokenize + ast 扫 790 个 .py），但仍比一次线上事故便宜。
    ("死代码棘轮", [PY, "tools/check_dead_code.py"], False),
    # 信号接线（S4）：pyqtSignal 定义了却全项目没人 .connect = 假接口。
    # 1.6 秒（读一遍 core/gui/modules/tools/tests 的文本 + 对定义侧做 AST 解析）。
    ("信号接线", [PY, "tools/check_signals.py"], False),
    ("结构契约", [PY, "tools/check_shapes.py"], True),      # 12 秒，放 pre-push
    # plugins_repo 是独立仓库、真的会推到 gitee，用户端拉它装插件。
    # 主仓库没有远程、没有 CI 兜着，所以"推送前"是唯一的关卡。
    ("插件仓库一致性", [PY, "tools/check_repo_sync.py"], True),
    ("提交前测试", [PY, "-m", "pytest", "tests/", "-q"], True),  # 70 秒
]

# 关键守卫：这几项一旦被从 CHECKS 里删掉（或改了名字），本脚本直接判失败。
# 理由：门禁最容易被"优化"掉，而删掉之后一切照旧显示绿色 —— 等于没有门禁。
REQUIRED = ("语法检查", "版本号一致性", "静默失败棘轮", "懒加载来源",
            "数据路径棘轮", "死代码棘轮", "信号接线")


def run(cmd):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run(cmd, cwd=BASE, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out
    except FileNotFoundError:
        return 127, "找不到命令：%s" % " ".join(cmd)


def install_hooks():
    """把 .githooks 挂上（git 的 hook 在 .git/hooks 里，不受版本控制，所以要指过去）"""
    hooks_dir = os.path.join(BASE, ".githooks")
    if not os.path.isdir(hooks_dir):
        print("[X] 没有 .githooks 目录")
        return 1
    r = subprocess.run(["git", "config", "core.hooksPath", ".githooks"],
                       cwd=BASE, capture_output=True, text=True)
    if r.returncode != 0:
        print("[X] 设置 core.hooksPath 失败：%s" % (r.stderr or "")[:100])
        return 1
    # 确保可执行位（Linux/macOS 需要；Windows 无所谓）
    for f in os.listdir(hooks_dir):
        p = os.path.join(hooks_dir, f)
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o755)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
    cur = subprocess.run(["git", "config", "core.hooksPath"], cwd=BASE,
                         capture_output=True, text=True).stdout.strip()
    print("✅ 已启用 git hook：core.hooksPath = %s" % cur)
    print("   pre-commit 跑快检（约 5 秒）；pre-push 跑全套（约 85 秒）")
    print("   撤销：git config --unset core.hooksPath")
    return 0


def main():
    ap = argparse.ArgumentParser(description="提交前检查")
    ap.add_argument("--full", action="store_true",
                    help="跑全套（含 check_shapes 与 pytest），pre-push 用")
    ap.add_argument("--install", action="store_true", help="安装 git hook")
    args = ap.parse_args()

    if args.install:
        return install_hooks()

    todo = [c for c in CHECKS if args.full or not c[2]]
    missing = [k for k in REQUIRED if k not in {c[0] for c in CHECKS}]
    if missing:
        print("=" * 70)
        print("[X] 关键守卫被删掉了：%s" % "、".join(missing))
        print("    这几项是 B7 固定的底线（见 REQUIRED），不允许静默移除。")
        return 1
    mode = "全套(pre-push)" if args.full else "快检(pre-commit)"
    print("=" * 70)
    print("提交前检查 · %s · 共 %d 项" % (mode, len(todo)))
    print("=" * 70)

    failed = []
    t_all = time.time()
    for label, cmd, _full in todo:
        t0 = time.time()
        code, out = run(cmd)
        dt = time.time() - t0
        if code == 0:
            print("  ✅ %-18s %5.1f 秒" % (label, dt))
            continue
        print("  ❌ %-18s %5.1f 秒（退出码 %d）" % (label, dt, code))
        failed.append((label, out))

    print("=" * 70)
    if not failed:
        print("全部通过 ✅  用时 %.1f 秒" % (time.time() - t_all))
        return 0

    print("有 %d 项没过，提交已拦下：" % len(failed))
    for label, out in failed:
        print()
        print("── %s ──" % label)
        lines = [l for l in out.strip().splitlines() if l.strip()]
        for l in lines[-18:]:                 # 尾部就是结论，别刷屏
            print("   " + l[:110])
    print()
    print("确实要跳过：git commit --no-verify（但请说明为什么）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
