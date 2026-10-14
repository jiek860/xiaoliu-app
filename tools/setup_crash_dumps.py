# -*- coding: utf-8 -*-
"""配崩溃转储（WER LocalDumps / procdump）

为什么需要这个
--------------
`core/crash_guard.py` 搞定了 faulthandler —— 崩溃时能把**Python 层**栈
写进日志。但它有硬局限：

    **看不到原生子帧** —— numpy / Qt / torch 的 C 层调用它看不见。

如果那次 access violation 是崩在 `c10.dll` 里某个偏移，
faulthandler 只能告诉你"崩在哪个 Python 函数调的"，看不到 DLL 内部。
要定位那种崩溃，必须拿到**进程级 dump**。

两条路（本工具都支持）
----------------------
  ① WER LocalDumps —— 系统自带，改注册表即可，**以后所有崩溃都自动存**
     优点：一次配好，长期有效
     缺点：要管理员权限写 HKLM；只对**未处理异常**生效
  ② procdump —— Sysinternals 官方工具，可以**盯着进程**
     优点：能抓"没崩但卡死"、能配多种触发条件
     缺点：要单独下载、要在启动程序时带上它

用法
----
    py -3 tools\\setup_crash_dumps.py --status     看当前配了什么
    py -3 tools\\setup_crash_dumps.py --wer        配 WER（要管理员）
    py -3 tools\\setup_crash_dumps.py --procdump   下载 procdump
    py -3 tools\\setup_crash_dumps.py --watch      用 procdump 盯着启动小6
    py -3 tools\\setup_crash_dumps.py --disable    撤掉 WER 配置

⚠️ 关于隐私：dump 文件里**包含进程内存**，可能有你的聊天内容和 API Key。
   所以：
     · dump 默认存到项目下 `data/dumps/`（不散落到系统目录）
     · **绝不自动上传**
     · 发给别人前先想清楚 —— 那等于把内存里的东西一起给了
"""
import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP_DIR = os.path.join(BASE, "data", "dumps")
TOOLS_DIR = os.path.join(BASE, "data", "tools")
PROCDUMP = os.path.join(TOOLS_DIR, "procdump.exe")

# WER 本地转储的注册表位置（HKLM，要管理员）
WER_KEY = (r"HKLM\SOFTWARE\Microsoft\Windows\Windows Error "
           r"Reporting\LocalDumps")
# 也可以按 exe 名单独配：LocalDumps\<exe名>

PROCDUMP_URLS = [
    # Sysinternals 官方直链（国内通常能通）
    "https://live.sysinternals.com/procdump.exe",
    "https://download.sysinternals.com/files/Procdump.zip",
]


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def is_admin():
    """当前是不是管理员（WER 要写 HKLM）"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
# WER LocalDumps
# ══════════════════════════════════════════════════════════
def wer_status():
    """读当前 WER 配置；没配返回空 dict"""
    r = _run(["reg", "query", WER_KEY])
    if r.returncode != 0:
        return {}
    out = {}
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in ("DumpFolder", "DumpType",
                                            "DumpCount"):
            out[parts[0]] = parts[-1]
    return out


def wer_enable(folder=None, dump_type=2, count=10):
    """配上 WER 本地转储

    dump_type: 1=迷你（小，栈为主）  2=完整（大，含内存）
    ⚠️ 默认给 2：那次崩溃是 C 层内存错误，迷你 dump 往往看不出所以然。
       代价是每个 dump 几十到几百 MB —— 所以 count 限 10 个。
    """
    folder = folder or DUMP_DIR
    if not is_admin():
        return False, ("配 WER 要**管理员权限**（它写的是 HKLM 系统级注册表）。\n"
                       "    做法：右键点「开始」→ 终端(管理员)，然后重跑这条命令。\n"
                       "    或者直接用 procdump（不用管理员）："
                       "py -3 tools\\setup_crash_dumps.py --procdump")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        return False, "建不出 dump 目录 %s：%s" % (folder, str(e)[:60])

    for name, val, typ in (("DumpFolder", folder, "REG_EXPAND_SZ"),
                           ("DumpType", str(dump_type), "REG_DWORD"),
                           ("DumpCount", str(count), "REG_DWORD")):
        r = _run(["reg", "add", WER_KEY, "/v", name, "/t", typ,
                  "/d", val, "/f"])
        if r.returncode != 0:
            return False, ("写注册表失败（%s）：%s"
                           % (name, (r.stderr or r.stdout or "")[:100]))
    return True, "已配上，dump 会存到 %s" % folder


def wer_disable():
    r = _run(["reg", "delete", WER_KEY, "/f"])
    if r.returncode != 0:
        return False, "撤不掉（可能本来就没配）：%s" % (r.stderr or "")[:80]
    return True, "已撤掉 WER 本地转储配置"


# ══════════════════════════════════════════════════════════
# procdump
# ══════════════════════════════════════════════════════════
def procdump_status():
    return PROCDUMP if os.path.exists(PROCDUMP) else ""


def procdump_fetch():
    """下载 procdump（Sysinternals 官方）"""
    if os.path.exists(PROCDUMP):
        return True, "已经有了：%s" % PROCDUMP
    os.makedirs(TOOLS_DIR, exist_ok=True)
    import urllib.request
    last = ""
    for url in PROCDUMP_URLS:
        try:
            print("  下载 %s …" % url)
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 100000:
                last = "文件太小（%d 字节），不像是 procdump" % len(data)
                continue
            if url.endswith(".zip"):
                import io
                import zipfile
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for n in z.namelist():
                        if n.lower().endswith("procdump.exe"):
                            with open(PROCDUMP, "wb") as f:
                                f.write(z.read(n))
                            break
            else:
                with open(PROCDUMP, "wb") as f:
                    f.write(data)
            if os.path.exists(PROCDUMP):
                return True, ("下好了：%s（%.1f MB）"
                              % (PROCDUMP, os.path.getsize(PROCDUMP)
                                 / 1048576))
            last = "下载了但没找到 procdump.exe"
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:70])
    return False, ("下不下来（%s）。\n"
                   "    可以手动从 https://learn.microsoft.com/sysinternals/"
                   "downloads/procdump 下，\n"
                   "    把 procdump.exe 放到 %s" % (last, TOOLS_DIR))


def procdump_watch(target_exe=None, dump_dir=None, wait=False,
                   first_chance=False):
    """用 procdump 盯着启动小6（抓崩溃）

    参数
        wait          True = 等进程**启动**就挂上（-w），
                      适合"先开监视窗口，再开程序"
        first_chance  默认 False，只抓**未处理**异常（-e）
                      ⚠️ 别轻易开 True（-e 1）：那会**每个异常都抓**，
                         而 Python 内部大量使用异常做流程控制 ——
                         结果是被正常异常刷爆，d盘几秒钟就满。
                         而且真正的崩溃（access violation 杀掉进程）
                         一定是**未处理**异常，-e 就够。
                         只有排查"异常被吞掉了"的场景才需要 -e 1，
                         那时也务必配 -f 过滤器。
    """
    p = procdump_status()
    if not p:
        return False, "还没下 procdump，先跑 --procdump", ""
    dump_dir = dump_dir or DUMP_DIR
    os.makedirs(dump_dir, exist_ok=True)
    exe = target_exe or "小6智能体.exe"

    cmd = [p, "-accepteula", "-ma"]          # -ma = 完整 dump
    if first_chance:
        # 配个过滤器，只留真正想看的（不加过滤会被正常异常刷爆）
        cmd += ["-e", "1", "-f", "Access violation,Stack overflow"]
    else:
        cmd += ["-e"]                         # 只在未处理异常时抓

    # ⚠️ 两种模式的说明都必须含"内存"和具体风险（聊天/Key）。
    #    第一版只写了"含进程内存"，没说**具体是什么** —— 用户不会
    #    因为一句抽象的话就谨慎，得告诉他"里面有你的聊天记录和 API Key"。
    _PRIVACY = ("    ⚠️ dump 是进程内存快照 —— **里面有你的聊天记录、"
                "记忆内容和 API Key**。\n"
                "       发给别人（包括发给我）之前想清楚这一点。")
    if wait:
        # -w 的语法是：procdump ... -w <进程名> [dump目录]
        cmd += ["-n", "5", "-o", "-w", exe, dump_dir]
        note = ("先跑这个命令，它会在那儿等；**然后**再去开小6。\n"
                "    这个窗口要一直开着。崩了会自动存 dump 到 %s\n%s"
                % (dump_dir, _PRIVACY))
    else:
        # 盯一个已经在跑的进程
        cmd += ["-n", "5", "-o", exe, dump_dir]
        note = ("小6 得**已经在跑**。崩了会存 dump 到 %s\n%s"
                % (dump_dir, _PRIVACY))
    return True, " ".join(cmd), note


# ══════════════════════════════════════════════════════════
def show_status():
    print("=" * 74)
    print("崩溃转储配置现状")
    print("=" * 74)
    print("  管理员权限: %s" % ("是" if is_admin() else "**不是**（配 WER 需要）"))

    st = wer_status()
    if st:
        print("  WER 本地转储: ✅ 已配")
        for k, v in sorted(st.items()):
            print("      %-12s %s" % (k, v))
        print("      ⚠️ dump 里含进程内存 —— 可能有聊天内容和 Key，")
        print("         发给别人前想清楚")
    else:
        print("  WER 本地转储: ❌ 没配")
        print("      （好处：一次配好，以后**所有**崩溃自动存盘）")

    p = procdump_status()
    if p:
        print("  procdump:     ✅ %s" % p)
    else:
        print("  procdump:     ❌ 没有（%s）" % PROCDUMP)

    fd = os.path.join(BASE, "data", "logs", "faulthandler.log")
    print("  faulthandler: %s"
          % ("✅ %s（%.1f KB）" % (fd, os.path.getsize(fd) / 1024)
             if os.path.exists(fd) else "❌ 还没有日志"))

    print()
    print("  建议组合：")
    print("    faulthandler  → 崩了先看它（Python 层栈，秒级就能看）")
    print("    WER/procdump  → 栈不够时看原生帧（DLL 级定位）")


def main():
    ap = argparse.ArgumentParser(description="配崩溃转储")
    ap.add_argument("--status", action="store_true", help="看现状")
    ap.add_argument("--wer", action="store_true", help="配 WER（要管理员）")
    ap.add_argument("--disable", action="store_true", help="撤掉 WER 配置")
    ap.add_argument("--procdump", action="store_true", help="下载 procdump")
    ap.add_argument("--watch", action="store_true",
                    help="打印盯着启动的命令（不真执行）")
    ap.add_argument("--mini", action="store_true",
                    help="配 WER 时用迷你 dump（小，但往往看不清）")
    a = ap.parse_args()

    if a.status or not any([a.wer, a.disable, a.procdump, a.watch]):
        show_status()
        if not any([a.wer, a.disable, a.procdump, a.watch]):
            print()
            print("  想配的话：")
            print("     py -3 tools\\setup_crash_dumps.py --wer        （要管理员）")
            print("     py -3 tools\\setup_crash_dumps.py --procdump   （不用管理员）")
        return 0

    if a.wer:
        ok, msg = wer_enable(dump_type=1 if a.mini else 2)
        print("  %s %s" % ("✅" if ok else "❌", msg))
        return 0 if ok else 1

    if a.disable:
        ok, msg = wer_disable()
        print("  %s %s" % ("✅" if ok else "❌", msg))
        return 0 if ok else 1

    if a.procdump:
        ok, msg = procdump_fetch()
        print("  %s %s" % ("✅" if ok else "❌", msg))
        if ok:
            print()
            print("  用法：先开监视窗口，再启动小6")
            print("      py -3 tools\\setup_crash_dumps.py --watch")
        return 0 if ok else 1

    if a.watch:
        ok, msg, note = procdump_watch(wait=True)
        if not ok:
            print("  ❌ %s" % msg)
            return 1
        print("  要跑的命令（本工具不替你执行 —— 它要一直占着窗口）：")
        print()
        print("      %s" % msg)
        print()
        print("  %s" % note)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
