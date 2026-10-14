# -*- coding: utf-8 -*-
"""把技术异常翻译成"人能看懂 + 知道下一步"的话

为什么需要
----------
实测项目里报错长这样：
    「识别图片文字」执行出错：TypeError: OCR.available() takes 1 positional
    argument but 2 were given

这句话对**开发者**有用（一眼看出参数传错了），但对**用户**没用 ——
他既不知道发生了什么，也不知道该做什么。而这是个人自用+朋友分发的程序，
大部分时候"用户"就是自己或朋友。

翻译原则
--------
① 先说**人话**（发生了什么），再说**下一步**（能做什么）
② 原文**不丢** —— 技术细节附在后面，排查时还要用
③ 拿不准就不猜（宁可保留原文，也不要给一个错误的建议）

用法
----
    from core.error_text import friendly
    what, todo = friendly(exc)          # 也可以直接传字符串
    # what = "这个功能缺一个可选组件（xxx）"
    # todo = "装上它：pip install xxx"
"""
import re

# ── 装依赖的命令统一从这里出 ──
# 为什么单独抽出来：实测全项目 17 处 "pip install" 提示里
# **只有 1 处**带国内镜像，其余 16 处都让用户直接跑 `pip install xxx` ——
# 那会走 PyPI 官方源，国内经常慢到以为卡死（PyQt5 那种大包尤其明显）。
#
# 清华源实测可用，是 pip 官方文档推荐的国内镜像之一。
PIP_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def install_cmd(pkg, target="optional_libs"):
    """生成一条**能直接粘**的安装命令（带国内源）

    target 默认指向项目的 optional_libs —— 装进项目目录而不是系统 Python，
    这样卸载程序时不会在系统里留一堆包（install_optional.bat 也是这个约定）。
    传 None 就装到当前环境。
    """
    pkg = str(pkg).strip() if pkg else ""
    if not pkg or pkg == "None":
        return ""
    parts = ["py", "-3", "-m", "pip", "install"]
    if target:
        parts += ["--target", target]
    parts += [pkg, "-i", PIP_MIRROR]
    return " ".join(parts)


def install_hint(pkg):
    """给用户看的一句话安装提示（命令 + 图形界面的替代路径）

    两条路都给：
        · 命令行 —— 复制粘贴就能用
        · 图形界面 —— 不想碰命令行的人走「设置 → 扩展 → 功能扩展组件」
    """
    cmd = install_cmd(pkg)
    if not cmd:
        return "到「设置 → 扩展 → 功能扩展组件」里找找"
    return ("装上它（走国内源，快）：\n    %s\n"
            "不想用命令行的话：设置 → 扩展 → 功能扩展组件，找到它点「安装」"
            % cmd)


# ── 从错误文本里认出"缺的是哪个包" ──
# import 名和 pip 名不一致的那些（反过来用：文本里出现 import 名 -> 换成 pip 名）
# 和 core/optional_deps.py 里那张表是同一份对应关系，这里反着写一遍 ——
# 那边是"要装的时候按 pip 名装"，这边是"报错里给的是 import 名，得换回 pip 名"。
_IMPORT_TO_PIP = {
    "PIL": "Pillow",
    "win32api": "pywin32",
    "edge_tts": "edge-tts",
    "faster_whisper": "faster-whisper",
    "cv2": "opencv-python",
    "huggingface_hub": "huggingface-hub",
    "pyaudio": "pyaudio",
    "pyautogui": "pyautogui",
    "playwright": "playwright",
    "uiautomation": "uiautomation",
    "comtypes": "comtypes",
    "jedi": "jedi",
    "pyperclip": "pyperclip",
    "cryptography": "cryptography",
    "psutil": "psutil",
    "requests": "requests",
    "numpy": "numpy",
    "pywin32": "pywin32",
}

# 出现这些词说明**可能**是"依赖没装"（只在兜底那一步用）
_MISSING_SIGNALS = (
    "No module named",
    "ModuleNotFoundError",
    "缺一个可选组件",
    "依赖缺失",
    "需要装",
    "需要",          # 覆盖"需要 cryptography 库"这种没带"装"字的
    "没装",
    "未装",
    "未检测到",      # 覆盖"未检测到语音识别后端"
    "缺少",
    "not installed",
    "No module",
)


def missing_package(text):
    """从一段错误文本里认出**缺的是哪个 pip 包**；认不出返回 ""

    用途：聊天里出现了"缺依赖"的错误时，好弹一个框问用户
    "要不要现在装" —— 而不是只留一句让你自己复制命令的文字。

    ⚠️ 认不出就返回空字符串，**不猜** —— 猜错会让用户装一个不相干的包，
    比不提示更糟（这条和 friendly() 的"拿不准就不猜"是同一个原则）。

    ⚠️ **顺序很重要**（第一版写错过）：明确模式要**先**匹配，
    "信号词闸门"只留给最后的兜底那一步。
    第一版把闸门放在最前面，结果
        "未检测到语音识别后端。py -3 -m pip install ... faster-whisper"
    被挡掉了 —— 明明**明写了 pip 命令**，却因为句子里没有闸门认得的词
    而返回空。明写的命令本身就是最强的信号，不该再过闸门。
    """
    s = _text_of(text) if not isinstance(text, str) else str(text)
    if not s:
        return ""

    # ① 最可靠：No module named 'xxx'
    m = re.search(r"No module named ['\"]?([\w\-.]+)", s)
    if m:
        return _IMPORT_TO_PIP.get(m.group(1), m.group(1))

    # ② describe() 产出的人话：「xxx」缺一个可选组件（pkg），当前没装
    m = re.search(r"缺一个可选组件（([\w\-.]+)）", s)
    if m:
        return _IMPORT_TO_PIP.get(m.group(1), m.group(1))

    # ③ 提示里的 pip install 命令（自己生成的提示就长这样）
    #    这一条不需要任何信号词 —— 出现 pip install 就是装了才用的东西
    m = re.search(r"pip\s+install\s+(?:--target\s+\S+\s+)?([\w\-.]+)", s)
    if m:
        pkg = m.group(1)
        if pkg not in ("install", "run", "-r", "upgrade", "list"):
            return _IMPORT_TO_PIP.get(pkg, pkg)

    # ④ 兜底：**先过信号词闸门**，再找常见包名 ——
    #    这一步容易误报（"缺少参数"也会命中"缺少"），所以要闸门压着
    if not any(k in s for k in _MISSING_SIGNALS):
        return ""
    for imp, pip in _IMPORT_TO_PIP.items():
        if re.search(r"\b%s\b" % re.escape(imp), s):
            return pip
    return ""


# (正则, 人话, 下一步)  —— 按顺序匹配，第一个命中的生效
_RULES = [
    # ── 缺组件 ──
    (r"No module named ['\"]?([\w\-.]+)",
     "这个功能依赖一个可选组件（%s），当前没装",
     install_hint("%s")),
    (r"cannot import name ['\"]?(\w+)",
     "组件版本可能不对（装的是旧版或缺少 %s）",
     "升级相关组件，或到「设置 → 扩展」看看"),
    (r"DLL load failed|找不到指定的模块",
     "缺少系统运行库（多半是 VC++ 运行库）",
     "装上 Microsoft Visual C++ Redistributable 再试"),

    # ── 网络与服务 ──
    (r"Connection refused|WinError 10061|拒绝连接",
     "连不上这个服务（服务没启动，或地址/端口不对）",
     "确认服务已启动；本地模型请看「设置 → 模型」里的地址"),
    (r"Name or service not known|getaddrinfo failed|Temporary failure in name",
     "域名解析不了（通常是网络断了）",
     "检查网络连接"),
    (r"timed out|TimeoutError|Read timed out",
     "等太久了（对方没在预期时间内回应）",
     "重试一次；如果一直这样，检查网络或把超时调大"),
    (r"SSL|CERTIFICATE_VERIFY_FAILED|证书",
     "安全连接建立失败（证书问题或代理拦截）",
     "检查代理设置；公司网络可能需要装证书"),
    (r"\b(429)\b|rate limit|too many requests",
     "请求太频繁被限流了",
     "等一会儿再试"),

    # ── 文件与权限 ──
    (r"No such file or directory: ['\"]([^'\"]+)",
     "找不到文件：%s",
     "确认路径写对了、文件还在"),
    (r"Permission denied|WinError 5|拒绝访问",
     "没有权限（文件被占用，或需要管理员）",
     "关掉正在用这个文件的程序，或换个目录"),
    (r"No space left|磁盘空间不足",
     "磁盘满了",
     "清理一些空间再试"),
    (r"Is a directory|是一个目录",
     "把目录当文件用了",
     "检查路径 —— 那里是个文件夹"),

    # ── 数据格式 ──
    (r"JSONDecodeError|Expecting value|Expecting property name",
     "数据文件坏了（内容不是合法 JSON）",
     "找到对应的 .json 文件看看，或从备份恢复"),
    (r"UnicodeDecodeError|codec can't decode",
     "文件编码不对（多半不是 UTF-8）",
     "另存为 UTF-8 再试"),
    (r"KeyError: ['\"]?(\w+)",
     "数据里少了必要字段（%s）",
     "多半是版本不一致导致的数据格式变化，可试试数据迁移"),

    # ── 内部不一致 ──
    (r"takes (\d+) positional argument.*but (\d+) (?:was|were) given",
     "这个功能和当前版本对不上（内部接口不一致）",
     "多半是模块版本旧了 —— 到插件市场看看有没有更新"),
    (r"not subscriptable|not iterable|has no attribute ['\"]?(\w+)",
     "内部数据结构对不上（可能是版本不一致）",
     "重启程序再试；还不行就反馈这条信息"),

    # ── 资源 ──
    (r"MemoryError|out of memory|内存不足",
     "内存不够了",
     "关掉一些程序再试；本地大模型很吃内存"),
    (r"CUDA|GPU|out of memory on device",
     "显卡相关错误（显存不足或驱动不匹配）",
     "换小一点的模型，或改用 CPU 模式"),
]


def _text_of(err):
    """把异常或字符串统一成 '类型: 描述' 文本"""
    if err is None:
        return ""
    if isinstance(err, str):
        return err
    if isinstance(err, BaseException):
        return "%s: %s" % (type(err).__name__, err)
    return str(err)


def friendly(err, keep_original=True):
    """翻译一个异常/错误文本

    返回 (人话, 下一步)。拿不准时人话为空字符串，调用方应保留原文。
        what  = "这个功能依赖一个可选组件（pyautogui），当前没装"
        todo  = "装上它试试：pip install pyautogui"
    """
    s = _text_of(err)
    if not s:
        return "", ""
    for pat, what, todo in _RULES:
        m = re.search(pat, s, re.I)
        if not m:
            continue
        groups = [g for g in (m.groups() or ()) if g]
        try:
            what_s = what % tuple(groups) if groups and "%s" in what else what
        except Exception:
            what_s = what
        try:
            todo_s = todo % tuple(groups) if groups and "%s" in todo else todo
        except Exception:
            todo_s = todo
        return what_s, todo_s
    return "", ""


def describe(err, subject="", keep_original=True):
    """给用户看的一整句（含对象名与原始信息）

    subject 例："识别图片文字"。产出形如：
        「识别图片文字」缺一个可选组件（pyautogui），当前没装
        下一步：装上它试试：pip install pyautogui
        （技术细节：ModuleNotFoundError: No module named 'pyautogui'）
    """
    what, todo = friendly(err)
    head = ("「%s」" % subject) if subject else ""
    if not what:
        # 拿不准就别编 —— 保留原文
        return "%s出错了：%s" % (head, _text_of(err)[:160])
    lines = ["%s%s" % (head, what)]
    if todo:
        lines.append("下一步：%s" % todo)
    if keep_original:
        raw = _text_of(err)
        if raw and raw[:40] not in "\n".join(lines):
            lines.append("（技术细节：%s）" % raw[:160])
    return "\n".join(lines)
