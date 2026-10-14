# -*- coding: utf-8 -*-
"""可选依赖：功能 → 依赖映射 + 状态登记（DSH runtime.json 的对应物）

要解决什么
----------
小6 其实**已经有正确的安装机制**：
    requirements.txt           5 个核心依赖，必装
    requirements-optional.txt  可选依赖，按功能分好组，注释里还记着硬坑
                               （av 必须 <19、huggingface-hub <2、
                                torch 与 PyQt5 的 DLL 加载顺序冲突）
    scripts/install_optional.bat + 设置里的「功能扩展组件」都能按需装
    run.py 会把 optional_libs/ 加进 sys.path

**真正的缺口是"看不见"**：
    · optional_libs/ 里已经装了 1050 MB，但没有任何地方记录"装了什么、什么版本"
    · 用户问"我这个环境哪些功能能用"没有答案
    · 分发时不知道该不该拷 optional_libs/（拷了就多 1 GB）
    · 出问题时（某个可选包版本不对）没有对照依据

DSH 用 dsh-runtimes/<runtime>/runtime.json 记这些（含 payloadDigest 校验）。
这里做对应物：**扫描实际装了什么 → 生成登记表 → 提供状态查询**。

注意：本模块**只读不装**。装依赖仍走 pip / install_optional.bat ——
"按需安装"这件事小6 已经做好了，缺的是"按需**知道**"。
"""
import importlib.util
import json
import os
import sys
import time

# 功能 -> 该功能需要的可选依赖（与 requirements-optional.txt 对应）
# 值是 pip 包名；import 名不同的用 (pip名, import名) 表示
FEATURES = {
    "电脑控制": ["Pillow", "pyautogui", "pyperclip", "pywin32"],
    "语音合成": ["edge-tts"],
    # av / huggingface-hub 本来是 faster-whisper 的传递依赖，但它们在
    # requirements-optional.txt 里被**显式钉了版本**（av<19、hub<2），
    # 因为不钉就直接报错。所以这里也要列出来 —— 否则"缺依赖"的判断
    # 会漏掉"装是装了、但版本是坏的那个"这种情况的排查线索。
    "语音识别": ["faster-whisper", "pyaudio", "av", "huggingface-hub"],
    "图像理解": ["opencv-python"],
    "浏览器自动化": ["playwright"],
    "代码补全": ["jedi"],
    "界面组件": ["uiautomation", "comtypes"],
}

# pip 名 -> import 名（名字不一致的那些）
_IMPORT_NAME = {
    "Pillow": "PIL",
    "pywin32": "win32api",
    "edge-tts": "edge_tts",
    "faster-whisper": "faster_whisper",
    "opencv-python": "cv2",
    "huggingface-hub": "huggingface_hub",
}

# 已知的版本约束（来自 requirements-optional.txt 的注释，都是踩过的坑）
KNOWN_PINS = {
    "av": "必须 <19：faster-whisper 1.2.1 调用 av.open(metadata_errors=...)，"
          "PyAV 19 去掉了这个参数",
    "huggingface-hub": "必须 <2：tokenizers 声明 huggingface-hub<2.0",
    "openai-whisper": "需 torch；且与 PyQt5 有 DLL 加载顺序冲突"
                      "（先 import PyQt5 再 import torch 会 WinError 1114）",
}

_REL = os.path.join("data", "optional_deps.json")


def _import_name(pkg):
    return _IMPORT_NAME.get(pkg, pkg.replace("-", "_"))


def _find(pkg, base):
    """这个包能不能 import 到；返回 (能否, 位置)"""
    name = _import_name(pkg)
    try:
        spec = importlib.util.find_spec(name)
    # 静默是故意的：find_spec 对坏包/半装的包会抛各种异常，
    # 而这里的问题是"能不能用"—— 抛异常就等于不能用，直接当缺失处理
    except Exception:
        spec = None
    if spec is None:
        return False, ""
    origin = spec.origin or ""
    # 判断是从哪来的
    if origin and os.path.abspath(origin).startswith(
            os.path.abspath(os.path.join(base or ".", "optional_libs"))):
        return True, "optional_libs"
    if origin and os.path.abspath(origin).startswith(
            os.path.abspath(os.path.join(base or ".", "libs"))):
        return True, "libs"
    return True, "系统 Python" if origin else "内置"


def _version(pkg):
    """尽力取版本号（不 import 包本体，避免副作用）"""
    try:
        from importlib.metadata import version as _v
        return _v(pkg)
    # 静默是故意的：取不到版本不是错误（有的包不注册 metadata），
    # 下面还有第二条路（读 __version__），两条都不行就返回空串
    except Exception:
        pass
    try:
        mod = __import__(_import_name(pkg))
        return str(getattr(mod, "__version__", "") or "")
    except Exception:
        return ""


def _hint(missing):
    """缺依赖时给用户的安装提示（走统一入口，带国内源）

    为什么要有这个：原来这里写的是
        "py -3 -m pip install --target optional_libs %s" % " ".join(missing)
    —— **不带国内源**，用户照着跑会走 PyPI 官方源，国内经常慢到以为卡死。
    全项目 17 处 pip 提示里只有 1 处带了镜像，这就是其中漏掉的一处。
    """
    if not missing:
        return ""
    pkgs = " ".join(missing)
    try:
        from core.error_text import install_cmd
        return install_cmd(pkgs)
    # 静默是故意的：只是"生成一句提示"失败，退回手写命令即可 ——
    # 不该因为拼提示失败就让整个状态查询挂掉
    except Exception:
        return ("py -3 -m pip install --target optional_libs %s "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkgs)


def scan(base=None, with_version=True):
    """扫描每个功能当前是否可用

    返回 {功能: {"可用": bool, "缺": [...], "位置": {...}, "版本": {...}}}
    """
    base = base or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = {}
    for feat, pkgs in FEATURES.items():
        missing, where, vers = [], {}, {}
        for p in pkgs:
            ok, loc = _find(p, base)
            if not ok:
                missing.append(p)
                continue
            where[p] = loc
            if with_version:
                v = _version(p)
                if v:
                    vers[p] = v
        out[feat] = {
            "可用": not missing,
            "缺": missing,
            "位置": where,
            "版本": vers,
            "装法": _hint(missing),
        }
    return out


def status(base=None):
    """一句话摘要（给自检/界面用）"""
    s = scan(base, with_version=False)
    ok = [f for f, v in s.items() if v["可用"]]
    bad = {f: v["缺"] for f, v in s.items() if not v["可用"]}
    return {"可用功能": ok, "缺依赖": bad,
            "摘要": "%d/%d 个可选功能可用%s"
                    % (len(ok), len(s),
                       ("；缺：" + "、".join(bad)) if bad else "")}


def record(base=None):
    """生成登记表 -> data/optional_deps.json（类比 DSH 的 runtime.json）

    记什么：每个功能的可用状态、每个包的版本与来源位置、环境信息。
    为什么值得记：
        · 用户问"我这环境哪些功能能用"—— 有答案
        · 某个可选包版本不对导致诡异报错 —— 有对照
        · 分发时判断要不要带 optional_libs/ —— 有依据
        · 换机器后对比"原来是什么版本" —— 有基准
    """
    base = base or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    s = scan(base)
    sizes = _dir_sizes(base)
    data = {
        "_说明": "可选依赖登记表。只读生成，不参与运行；用来回答"
                 "『哪些可选功能可用 / 装在哪 / 什么版本』。",
        "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
        "平台": sys.platform,
        "功能": {f: {"可用": v["可用"], "缺": v["缺"], "版本": v["版本"],
                     "位置": sorted(set(v["位置"].values()))}
                 for f, v in s.items()},
        "占用": sizes,
        "已知版本约束": KNOWN_PINS,
    }
    p = os.path.join(base, _REL)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return {"ok": True, "文件": p, "摘要": status(base)["摘要"]}
    except Exception as e:
        return {"ok": False, "错误": "%s: %s" % (type(e).__name__,
                                                str(e)[:60])}


def _dir_sizes(base):
    out = {}
    for d in ("optional_libs", "libs"):
        p = os.path.join(base, d)
        if not os.path.isdir(p):
            continue
        n = sz = 0
        for r, _ds, fs in os.walk(p):
            for f in fs:
                try:
                    sz += os.path.getsize(os.path.join(r, f))
                    n += 1
                # 静默是故意的：统计体积时遇到读不到的单个文件（权限/被占用），
                # 跳过它继续数就行 —— 少算一个文件不影响"大概多大"这个用途
                except Exception:
                    pass
        out[d] = {"文件数": n, "MB": round(sz / 1024.0 / 1024, 1)}
    return out


def distribution_hint(base=None):
    """分发建议：optional_libs/ 该不该跟着拷

    这是省 1 GB 的关键 —— 它可以在新机器上重新装（见 requirements-optional.txt）。
    """
    base = base or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sizes = _dir_sizes(base)
    o = sizes.get("optional_libs", {})
    if not o:
        return {"建议": "没有 optional_libs/，直接拷即可"}
    return {
        "建议": "**分发时不要拷 optional_libs/**（%.1f MB）—— 对方需要哪些功能，"
                "在自己机器上跑 scripts\\install_optional.bat 或"
                " `pip install --target optional_libs "
                "-r requirements-optional.txt "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple`"
                "（⚠️ 最后那个 -i 别省 —— 不带会走 PyPI 官方源，国内很慢）"
                % o.get("MB", 0),
        "可省": "%.1f MB" % o.get("MB", 0),
        "另需注意": "data/browsers（chromium）同样可省，第一次用浏览器时再装",
    }
