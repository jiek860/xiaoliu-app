# -*- coding: utf-8 -*-
r"""模型配置自检：判断现在到底能不能用起来，以及该怎么修

为什么单独抽出来
----------------
"朋友打开后问它话没反应" 是这套程序最劝退的一件事。根因通常是三种之一：
    1. 云端模式但 API Key 是空的（会报一个看不懂的 API 错误）
    2. 本地模式但 Ollama 没装 / 没启动 / 里面没有那个模型
    3. 模型名对不上（自己训的模型名，别人机器上当然没有）
所以需要一处统一的自检逻辑，首次运行引导和设置界面共用，避免两边判断不一致。

本模块不依赖 Qt，可单独测试。
"""
import json
import urllib.request

DEFAULT_OLLAMA = "http://localhost:11434"
RECOMMENDED_LOCAL_MODEL = "qwen2.5:3b"
OLLAMA_DOWNLOAD = "https://ollama.com/download"


def probe_ollama(url=None, timeout=3):
    """探测 Ollama 是否在跑、装了哪些模型。不抛异常，失败也返回结构化结果。"""
    url = (url or DEFAULT_OLLAMA).rstrip("/")
    out = {"url": url, "reachable": False, "models": [], "error": ""}
    try:
        req = urllib.request.Request(url + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        out["reachable"] = True
        out["models"] = [str(m.get("name", "")) for m in (data.get("models") or [])]
    except Exception as e:
        out["error"] = str(e)[:100]
    return out


def check(trunk):
    """汇总当前模型可用性。

    返回:
        mode      当前模式
        ollama    probe_ollama 的结果
        cloud     {url, model, key_set}
        local_model / 配置里写的本地模型名
        ready     现在能不能正常对话
        problems  中文问题列表（空=可用）
        advice    给用户看的一句话建议
    """
    cfg = getattr(trunk, "config", {}) or {}
    mode = str(cfg.get("model_mode", "本地模型") or "本地模型")

    cloud = {
        "url": str(cfg.get("cloud_url", "") or "").strip(),
        "model": str(cfg.get("cloud_model", "") or "").strip(),
        "key_set": bool(str(cfg.get("cloud_key", "") or "").strip()),
    }
    local_model = str(cfg.get("local_model", "") or "").strip()

    # 只有本地/双模型模式才去探 Ollama。
    # 纯云端模式下不探，省掉最长 3 秒的等待（首次启动会调这个函数）。
    need_local = ("本地" in mode) or ("双" in mode)
    if need_local:
        ollama = probe_ollama(cfg.get("ollama_url") or DEFAULT_OLLAMA)
    else:
        ollama = {"url": str(cfg.get("ollama_url") or DEFAULT_OLLAMA),
                  "reachable": False, "models": [],
                  "error": "当前不是本地模式，未检测"}

    problems = []
    cloud_ok = bool(cloud["key_set"] and cloud["url"])
    local_ok = False

    if ollama["reachable"]:
        if not ollama["models"]:
            local_ok = False
        elif not local_model:
            local_ok = True                      # 没指定就随便用一个已有的
        else:
            local_ok = local_model in ollama["models"]
    if cloud["key_set"] and not cloud["url"]:
        problems.append("填了 API Key，但没填云端 API 地址")
    if not cloud["key_set"] and not cloud["url"]:
        pass                                     # 没配云端不算错，看模式

    if "双" in mode:
        # 双模型：任一路可用即可
        if not (cloud_ok or local_ok):
            if not ollama["reachable"]:
                problems.append("连不上本地 Ollama（%s）" % ollama["url"])
            elif not ollama["models"]:
                problems.append("Ollama 里还没有任何模型")
            elif not local_ok:
                problems.append("Ollama 里没有「%s」这个模型" % local_model)
            if not cloud_ok:
                problems.append("云端模型没配好（缺少 API 地址或 Key）")
    elif "云端" in mode:
        if not cloud["url"]:
            problems.append("云端模式但没填 API 地址")
        if not cloud["key_set"]:
            problems.append("云端模式但没填 API Key")
    else:  # 本地
        if not ollama["reachable"]:
            problems.append("连不上本地 Ollama（%s）" % ollama["url"])
            if ollama["error"]:
                problems.append("原因：%s" % ollama["error"])
        elif not ollama["models"]:
            problems.append("Ollama 在跑，但里面还没下载任何模型")
        elif not local_ok:
            problems.append("Ollama 里没有「%s」这个模型" % local_model)

    ready = not problems
    if ready:
        advice = "配置没问题，可以直接聊天了。"
    elif "云端" in mode:
        advice = "去填上云端 API 地址和 Key，或改用免费的本地 Ollama。"
    elif not ollama["reachable"]:
        advice = ("装一个 Ollama 就能免费用：%s\n"
                  "装完执行：ollama run %s" % (OLLAMA_DOWNLOAD, RECOMMENDED_LOCAL_MODEL))
    else:
        advice = "在命令行执行：ollama run %s" % (local_model or RECOMMENDED_LOCAL_MODEL)

    return {
        "mode": mode,
        "ollama": ollama,
        "cloud": cloud,
        "local_model": local_model,
        "ready": ready,
        "problems": problems,
        "advice": advice,
    }


def apply_local(trunk, url=None, model=None):
    """切到本地模式并写盘。返回 save_config 的结果。"""
    cfg = trunk.config
    if url:
        cfg["ollama_url"] = str(url).strip().rstrip("/")
    if model:
        cfg["local_model"] = str(model).strip()
        cfg["small_model"] = cfg["local_model"]
    cfg["model_mode"] = "本地模型"
    try:
        return trunk.save_config()
    except Exception:
        return False


def apply_cloud(trunk, url=None, model=None, key=None):
    """切到云端模式并写盘。

    注意 key 为空时不覆盖已有值 —— 用户可能只是想改地址，不希望 Key 被清掉。
    """
    cfg = trunk.config
    if url:
        cfg["cloud_url"] = str(url).strip()
    if model:
        cfg["cloud_model"] = str(model).strip()
    if key:
        cfg["cloud_key"] = str(key).strip()
    cfg["model_mode"] = "云端模型"
    try:
        return trunk.save_config()
    except Exception:
        return False
