# -*- coding: utf-8 -*-
"""Ollama 一键下载安装（带进度）+ 国内加速源

为什么做这个
------------
对比同类程序后最明显的一条差距：它们把 Ollama 的下载安装做成了
**程序内一键完成 + 进度条**，小6 这边只给一句
"没装的话：下载 Ollama，装完执行 ollama run xxx" ——
用户得自己开浏览器、找官网、下 1.5GB、再开命令行。
"朋友打开后问它话没反应"是这套程序最劝退的一件事，这是其中一环。

源是**实测选出来的**（2026-10-13，本机）
----------------------------------------
    gh-proxy.com 加速     响应 0.49 秒   吞吐 6.46 MB/s   -> 1.5GB 约 4 分钟
    ghproxy.net 加速      响应 3.06 秒
    ghfast.top 加速       响应 3.82 秒
    GitHub Releases       响应 2.61 秒   吞吐 0.08 MB/s   -> 约 5 小时
    官网直链 ollama.com   响应 3.65 秒   吞吐 0.05 MB/s   -> 约 8 小时

**差距 130 倍**。所以默认走加速源，但保留官网作为兜底 ——
第三方加速随时可能挂，不能只留一条路。

⚠️ 安装包实测 **1509 MB**（不是几百 MB）—— 现在的 Ollama 把
GPU 运行库都打进去了。这一点必须提前告诉用户，否则会以为卡住了。

设计上只做两件事：**下载** 和 **启动安装程序**。
不静默安装（那是替用户做决定，而且装到哪、要不要管理员权限
都应该由系统安装向导说了算）。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# 实测可用的下载源。顺序 = 默认优先级（先加速，后官方兜底）。
# 每个都必须用 /releases/latest/download/ 这种**不带版本号**的地址 ——
# 钉了版本号就会随官方发版而失效。
SOURCES = [
    {"名字": "国内加速 gh-proxy.com",
     "url": "https://gh-proxy.com/https://github.com/ollama/ollama/"
            "releases/latest/download/OllamaSetup.exe",
     "实测": "6.46 MB/s（约 4 分钟）"},
    {"名字": "国内加速 ghproxy.net",
     "url": "https://ghproxy.net/https://github.com/ollama/ollama/"
            "releases/latest/download/OllamaSetup.exe",
     "实测": "响应 3.06 秒"},
    {"名字": "国内加速 ghfast.top",
     "url": "https://ghfast.top/https://github.com/ollama/ollama/"
            "releases/latest/download/OllamaSetup.exe",
     "实测": "响应 3.82 秒"},
    {"名字": "GitHub 官方",
     "url": "https://github.com/ollama/ollama/releases/latest/download/"
            "OllamaSetup.exe",
     "实测": "国内实测 0.08 MB/s，很慢，仅作兜底"},
    {"名字": "Ollama 官网",
     "url": "https://ollama.com/download/OllamaSetup.exe",
     "实测": "国内实测 0.05 MB/s，很慢，仅作兜底"},
]

HOME = "https://ollama.com/download"
# ⚠️ 实测值，不是估计 —— 写小了用户会以为下完了其实没有
APPROX_MB = 1509

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def probe(url, timeout=10):
    """探一个源：能不能拿到、返回的是不是真的 exe、包多大

    只看**前 1KB**（Range 请求）—— 探 5 个源不该等于下 5 遍 1.5GB。
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Range": "bytes=0-1023"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            head = r.read(1024)
            cr = r.headers.get("Content-Range") or ""
        sec = time.time() - t0
        total = 0
        if "/" in cr:
            try:
                total = int(cr.split("/")[-1])
            except Exception:
                total = 0
        # PE 可执行文件以 MZ 开头 —— 不是的话可能拿到的是错误页
        return {"ok": head[:2] == b"MZ", "秒": round(sec, 2),
                "字节": total, "MB": round(total / 1048576.0, 1) if total else 0}
    except Exception as e:
        return {"ok": False, "错误": "%s: %s" % (type(e).__name__, str(e)[:60])}


def pick_best(timeout=10, progress=None):
    """按顺序探，返回第一个能用的源

    不按"响应最快"排 —— 响应快不等于吞吐快（实测官网响应 3.65 秒
    但吞吐只有 0.05 MB/s）。所以顺序按**吞吐实测**排好的固定优先级来，
    探到第一个"确实能下到 exe"的就用它。
    """
    for i, s in enumerate(SOURCES):
        if progress:
            try:
                progress("正在检测下载源 %d/%d：%s" % (i + 1, len(SOURCES),
                                                  s["名字"]))
            # 静默是故意的：progress 是界面的回调，它挂了不该让"挑源"这件事失败
            except Exception:
                pass
        r = probe(s["url"], timeout=timeout)
        if r.get("ok"):
            out = dict(s)
            out.update(r)
            return out
    return None


def default_path():
    """安装包存哪：临时目录（装完就可以删，不占项目空间）"""
    return os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")


def download(url, dest=None, progress=None, chunk=256 * 1024,
             should_stop=None):
    """下载到 dest，边下边回调进度

    progress(已下字节, 总字节, 速度MBps, 剩余秒) —— 每秒最多调几次，
    不用每个 chunk 都刷界面。

    should_stop() 返回 True 就中断（用户点了取消）。
    """
    dest = dest or default_path()
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        t0 = time.time()
        got = 0
        total = 0
        last_cb = 0.0
        with urllib.request.urlopen(req, timeout=30) as r:
            try:
                total = int(r.headers.get("Content-Length") or 0)
            except Exception:
                total = 0
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(tmp, "wb") as f:
                while True:
                    if should_stop and should_stop():
                        raise InterruptedError("用户取消")
                    b = r.read(chunk)
                    if not b:
                        break
                    f.write(b)
                    got += len(b)
                    now = time.time()
                    if progress and (now - last_cb > 0.3):
                        last_cb = now
                        dt = max(now - t0, 0.001)
                        sp = got / 1048576.0 / dt
                        eta = ((total - got) / 1048576.0 / sp) if (sp > 0
                                                                   and total) else 0
                        try:
                            progress(got, total, sp, eta)
                        # 静默是故意的：同上 —— 界面回调失败不该中断下载，
                        # 下载本身才是正事（1.5GB 下到一半因为刷界面失败而停
                        # 是最糟的结果）
                        except Exception:
                            pass
        os.replace(tmp, dest)          # 下完才改名 —— 中途断了不会留半个 exe
        return {"ok": True, "路径": dest, "字节": got,
                "MB": round(got / 1048576.0, 1),
                "耗时秒": round(time.time() - t0, 1)}
    except InterruptedError:
        _cleanup(tmp)
        return {"ok": False, "取消": True, "错误": "已取消下载"}
    except Exception as e:
        _cleanup(tmp)
        return {"ok": False, "错误": "%s: %s" % (type(e).__name__, str(e)[:80])}


def _cleanup(p):
    try:
        if os.path.exists(p):
            os.remove(p)
    # 静默是故意的：删临时文件失败不影响结果 —— 调用方已经拿到了
    # "取消/失败"的结论，.part 留着下次下载会被覆盖。为它再抛一次异常
    # 只会把真正的失败原因（网络错误）盖掉。
    except Exception:
        pass


def run_installer(path=None, wait=False):
    """启动安装程序

    **不静默安装**：OllamaSetup.exe 自带向导（能选安装位置、要不要开机自启），
    替用户全自动做完是越权，而且装到 C 盘这点很多人想改。
    这里只负责把它拉起来，剩下的交给系统。
    """
    path = path or default_path()
    if not os.path.exists(path):
        return {"ok": False, "错误": "安装包不存在：%s" % path}
    if os.path.getsize(path) < 1024 * 1024:
        return {"ok": False, "错误": "安装包太小（%d 字节），可能没下完"
                                    % os.path.getsize(path)}
    try:
        if sys.platform.startswith("win"):
            # 用 ShellExecute 语义：让系统处理 UAC（安装需要管理员权限）
            os.startfile(path)                     # noqa: S606
        else:
            subprocess.Popen([path])
        return {"ok": True, "提示": "安装向导已弹出 —— 按它的提示点完即可"
                                    "（装到哪可以自己选）"}
    except Exception as e:
        return {"ok": False,
                "错误": "拉不起来（%s）。手动双击这个文件也能装：\n%s"
                        % (str(e)[:60], path)}


def detect_installed():
    """Ollama 装了没（看常见安装位置 + PATH）"""
    if shutil.which("ollama"):
        return {"已装": True, "来源": "PATH"}
    cands = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Ollama\ollama.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Ollama\ollama.exe"),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return {"已装": True, "来源": c}
    return {"已装": False, "来源": ""}


def info():
    """给界面用的一句话说明（含真实体积与源列表）"""
    return {
        "安装包大小": "约 %d MB" % APPROX_MB,
        "官网": HOME,
        "源": SOURCES,
        "说明": "安装包约 %d MB（现在的 Ollama 把 GPU 运行库也打进去了，"
                "比以前大很多）。默认走国内加速源，实测比官网快 100 倍以上；"
                "加速源挂了会自动退回官网。" % APPROX_MB,
    }
