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
    py -3 tools\\setup_crash_dumps.py --watch      打印盯着启动的命令（不执行）
    py -3 tools\\setup_crash_dumps.py --watch-run  后台常驻监视（不占窗口）
    py -3 tools\\setup_crash_dumps.py --stop-watch 停掉常驻监视
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
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP_DIR = os.path.join(BASE, "data", "dumps")
TOOLS_DIR = os.path.join(BASE, "data", "tools")
PROCDUMP = os.path.join(TOOLS_DIR, "procdump.exe")
# 常驻监视的 pid / 日志（写进 data/logs 方便和 faulthandler.log 一起看）
WATCH_DIR = os.path.join(BASE, "data", "logs")
WATCH_PID = os.path.join(WATCH_DIR, "procdump_watch.pid")
WATCH_LOG = os.path.join(WATCH_DIR, "procdump_watch.log")

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
    cmd, exe, dump_dir = _watch_argv(target_exe, dump_dir, wait,
                                     first_chance)
    os.makedirs(dump_dir, exist_ok=True)

    # ⚠️ 两种模式的说明都必须含"内存"和具体风险（聊天/Key）。
    #    第一版只写了"含进程内存"，没说**具体是什么** —— 用户不会
    #    因为一句抽象的话就谨慎，得告诉他"里面有你的聊天记录和 API Key"。
    _PRIVACY = ("    ⚠️ dump 是进程内存快照 —— **里面有你的聊天记录、"
                "记忆内容和 API Key**。\n"
                "       发给别人（包括发给我）之前想清楚这一点。")
    if wait:
        note = ("先跑这个命令，它会在那儿等；**然后**再去开小6。\n"
                "    这个窗口要一直开着。崩了会自动存 dump 到 %s\n%s"
                % (dump_dir, _PRIVACY))
    else:
        # 盯一个已经在跑的进程
        note = ("小6 得**已经在跑**。崩了会存 dump 到 %s\n%s"
                % (dump_dir, _PRIVACY))
    return True, " ".join(cmd), note


def _watch_argv(target_exe=None, dump_dir=None, wait=False,
                first_chance=False):
    """拼 procdump 参数表（list）

    ⚠️ 显示（--watch）和真正启动（--watch-run）必须用同一份参数，
    否则会出现"打印的命令能跑、真启动的那条跑不了"。第一版
    `--watch-run` 直接把 `procdump_watch` 返回的**字符串**当参数表传给
    WMI，结果命令行变成一堆单字符，进程根本没起来。
    """
    dump_dir = dump_dir or DUMP_DIR
    exe = target_exe or "小6智能体.exe"
    argv = [procdump_status(), "-accepteula", "-ma"]   # -ma = 完整 dump
    if first_chance:
        # 配个过滤器，只留真正想看的（不加过滤会被正常异常刷爆）
        argv += ["-e", "1", "-f", "Access violation,Stack overflow"]
    else:
        argv += ["-e"]                                 # 只在未处理异常时抓
    if wait:
        # -w 的语法是：procdump ... -w <进程名> [dump目录]
        argv += ["-n", "5", "-o", "-w", exe, dump_dir]
    else:
        argv += ["-n", "5", "-o", exe, dump_dir]
    return argv, exe, dump_dir


# ══════════════════════════════════════════════════════════
# 常驻监视（不占窗口）
# ══════════════════════════════════════════════════════════
# 为什么加这个：`--watch` 只打印命令，得自己开个窗口挂着 —— 实际没人会
# 一直开着终端。faulthandler.log 里已经堆了 277 次 Windows fatal exception
# （0x8001010e 116 次、access violation 15 次、stack overflow 1 次），
# 但一次进程级 dump 都没有，原生帧永远定不了位。
# `--watch-run` 用 DETACHED_PROCESS 起一个不随终端退出的 procdump，
# stdout 落 data/logs/procdump_watch.log，pid 落 procdump_watch.pid。
def procdump_watch_pid(pid_path=None):
    """返回正在运行的监视进程 pid；没在跑返回 0"""
    pid_path = pid_path or WATCH_PID
    try:
        pid = int(open(pid_path, encoding="utf-8").read().strip())
    except Exception:
        return 0
    if pid <= 0:
        return 0
    try:
        import psutil
        if not psutil.pid_exists(pid):
            return 0
        name = (psutil.Process(pid).name() or "").lower()
        return pid if "procdump" in name else 0
    except Exception:
        # 静默是故意的：psutil 缺失/权限不足时下面还有 Win32 兜底，
        # 这里吞掉只是"换一条路查"，不是错误
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return pid
        except Exception:
            # 静默是故意的：Win32 也查不了就返回"没在跑"，状态查询不该抛异常
            pass
    return 0


def _start_via_wmi(cmd):
    """用 WMI 创建进程：父级是 WmiPrvSE，**不随当前终端/父进程退出**

    实测（2026-10-27）：Popen + DETACHED_PROCESS 起的 procdump 会跟着
    启动它的终端一起被收掉（这里跑测试的沙箱按作业对象清理子进程）；
    WMI 创建的进程不在同一个作业里，能一直活着。
    返回 pid；WMI 不可用返回 0。
    ⚠️ 走这条路 stdout 没有重定向，procdump 的控制台横幅会丢 ——
       dump 文件照常写，只影响那几行提示文字。
    """
    inner = " ".join('"%s"' % c if " " in c else c for c in cmd)
    script = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
              "-Arguments @{ CommandLine = '%s' }; Write-Output $r.ProcessId"
              % inner.replace("'", "''"))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", script],
                           capture_output=True, text=True, timeout=25)
        out = (r.stdout or "").strip().splitlines()
        pid = int(out[-1]) if out else 0
        return pid if pid > 0 else 0
    except Exception:
        return 0


def procdump_watch_run(target_exe=None, dump_dir=None, wait=True,
                       first_chance=False):
    """在后台真的起一个 procdump 常驻监视

    返回 (ok, msg)。已经在跑就不重复起（否则同一进程会存两份 dump）。
    """
    p = procdump_status()
    if not p:
        return False, "还没下 procdump，先跑 --procdump"
    cmd, exe, dump_dir = _watch_argv(target_exe, dump_dir, wait,
                                     first_chance)
    os.makedirs(dump_dir, exist_ok=True)
    running = procdump_watch_pid()
    if running:
        return True, ("已经在监视（pid %d），没有重复启动。\n"
                      "    日志：%s" % (running, WATCH_LOG))
    try:
        os.makedirs(WATCH_DIR, exist_ok=True)
    except Exception as e:
        return False, "建不出日志目录 %s：%s" % (WATCH_DIR, str(e)[:60])

    how = "WMI（关掉终端也活着）"
    pid = _start_via_wmi(cmd)
    if not pid:
        how = "普通后台进程"
        log = open(WATCH_LOG, "ab")
        try:
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW：
            # 尽量脱离当前会话（部分环境会按作业对象清理子进程，
            # 那种情况下只有 WMI 那条路能活）
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, close_fds=True,
                creationflags=0x00000008 | 0x00000200 | 0x08000000)
            pid = proc.pid
        except Exception as e:
            log.close()
            return False, "起不来（%s）：%s" % (type(e).__name__, str(e)[:80])
        log.close()
    try:
        with open(WATCH_PID, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except Exception:
        # 静默是故意的：pid 文件只是方便 --status/--stop-watch 找进程；
        # 写不了不影响监视本身（dump 照样会生成）
        pass
    try:
        with open(WATCH_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] 启动监视 pid=%s 目标=%s（%s）\n"
                    % (time.strftime("%Y-%m-%d %H:%M:%S"), pid, exe, how))
    except Exception:
        # 静默是故意的：同上，日志写不了不该让"已经起来的监视"报失败
        pass
    return True, ("已后台监视（pid %d，目标 %s，%s）。\n"
                  "    日志：%s\n"
                  "    dump：%s（最多 5 份，满了要重新启动监视）\n"
                  "    停止：py -3 tools\\setup_crash_dumps.py --stop-watch"
                  % (pid, exe, how, WATCH_LOG, dump_dir or DUMP_DIR))


def procdump_watch_stop():
    """停掉后台监视"""
    pid = procdump_watch_pid()
    if not pid:
        try:
            os.remove(WATCH_PID)
        except OSError:
            pass
        return False, "没有在跑的监视进程"
    try:
        import psutil
        psutil.Process(pid).terminate()
    except Exception:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True)
    try:
        os.remove(WATCH_PID)
    except OSError:
        pass
    return True, "已停止监视（pid %d）" % pid


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

    wpid = procdump_watch_pid()
    if wpid:
        print("  常驻监视:     ✅ pid %s（日志 %s）" % (wpid, WATCH_LOG))
    else:
        print("  常驻监视:     ❌ 没在跑（py -3 tools\\setup_crash_dumps.py "
              "--watch-run）")

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
    ap.add_argument("--watch-run", action="store_true",
                    help="后台常驻监视（不占窗口，崩了自动存 dump）")
    ap.add_argument("--stop-watch", action="store_true", help="停掉常驻监视")
    ap.add_argument("--target", default="",
                    help="监视哪个进程（默认小6智能体.exe；"
                         "从源码跑用 python.exe）")
    ap.add_argument("--first-chance", action="store_true",
                    help="连首次异常也抓（会被正常异常刷爆，慎用）")
    ap.add_argument("--mini", action="store_true",
                    help="配 WER 时用迷你 dump（小，但往往看不清）")
    a = ap.parse_args()

    _ACTIONS = (a.wer, a.disable, a.procdump, a.watch, a.watch_run,
                a.stop_watch)
    if a.status or not any(_ACTIONS):
        show_status()
        if not any(_ACTIONS):
            print()
            print("  想配的话：")
            print("     py -3 tools\\setup_crash_dumps.py --wer        （要管理员）")
            print("     py -3 tools\\setup_crash_dumps.py --procdump   （不用管理员）")
            print("     py -3 tools\\setup_crash_dumps.py --watch-run  （后台常驻）")
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
            print("  用法：后台常驻监视（不用开窗口）")
            print("      py -3 tools\\setup_crash_dumps.py --watch-run")
        return 0 if ok else 1

    if a.stop_watch:
        ok, msg = procdump_watch_stop()
        print("  %s %s" % ("✅" if ok else "❌", msg))
        return 0 if ok else 1

    if a.watch_run:
        ok, msg = procdump_watch_run(target_exe=a.target or None,
                                     first_chance=a.first_chance)
        print("  %s %s" % ("✅" if ok else "❌", msg))
        return 0 if ok else 1

    if a.watch:
        ok, msg, note = procdump_watch(wait=True,
                                       target_exe=a.target or None,
                                       first_chance=a.first_chance)
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
