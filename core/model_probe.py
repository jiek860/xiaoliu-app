# -*- coding: utf-8 -*-
"""模型配置真探测 —— 从 core/self_check.py 拆出（O5，2026-10-31）。

为什么单独成模块：`self_check.py` 已经到 700 行、超过 600 行硬上限；
「保存配置时到底能不能用」属于首配/重配流程，和「深度自检报告」是两条
使用路径，放在一起只会让两边都继续变长。

依赖说明：探测复用的 check_cloud / warmup_ollama / check_ollama 仍然住在
`core/self_check.py`。这里**在调用时**从模块上取属性（而不是 import 时绑定
名字）：`tests/test_model_setup.py` 会 monkeypatch `self_check.check_cloud`
一类的函数，只有动态取属性，打桩才能真正生效。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def _cloud_fallbacks():
    """探测失败时可改用的国内直连服务商（只用预设表，不联网）。"""
    try:
        from core import model_setup
        items = model_setup.CLOUD_PROVIDERS[:4]
        return "、".join("%s（%s）" % (p["名字"], p.get("备注", "")) for p in items)
    except Exception as e:  # 静默是故意的 - 提示文案缺失不该影响探测结果
        _x6_swallowed(__name__, e)
        return "智谱 GLM、DeepSeek、通义千问（都国内直连）"


def _fix_hint(why, mode="云端"):
    """把探测错误翻成「下一步做什么」，失败时优先给国内镜像/加速源。"""
    text = str(why or "")
    low = text.lower()
    try:
        from core.error_text import install_hint, missing_package
        pkg = missing_package(text)
        if pkg:
            return install_hint(pkg)
    except Exception as e:
        _x6_swallowed(__name__, e)
    if "401" in text or "403" in text or "key" in low or "令牌" in text:
        return ("Key 不对、过期或没有这个模型的权限：去服务商后台重新复制一份。\n"
                "国内直连可用的：%s" % _cloud_fallbacks())
    if "404" in text or "地址" in text:
        return ("地址要填服务商文档里 chat/completions 的完整地址。\n"
                "向导里的「服务商」下拉框选一下就会自动填好，别手抄。")
    if ("timeout" in low or "timed out" in low or "超时" in text
            or "连不上" in text or "network" in low or "connection" in low):
        if "本地" in mode or "Ollama" in text:
            return ("先确认 Ollama 在跑（右下角托盘的小羊驼）。没装的话点"
                    "「⬇️ 一键下载 Ollama 安装包」—— 自动走国内加速源，比官网快很多。")
        return ("网络到不了这家服务商。两条备选：\n"
                "① 换一个国内直连的：%s\n"
                "② 装本地 Ollama（安装包走国内加速源，向导里一键下载，不联网也能用）"
                % _cloud_fallbacks())
    if "模型" in text or "model" in low:
        return ("模型名一个字符都不能错：云端用「服务商」下拉框自动填；"
                "本地模型点「⬇️ 下载模型」拉一个。")
    return ""


def probe_model_config(trunk, timeout=6):
    """首次/重新配置时的**真探测**：本地预热 Ollama、云端真发一次请求。

    为什么需要
    ----------
    `model_setup.check()` 只看配置齐不齐：云端 Key 少一位也显示"配好了"，
    用户要到第一次聊天才看到 401；本地模型名打错也只会"发了没反应"。
    这里在**保存的那一刻**真连一次，配错一次到位，并把下一步写清楚。

    返回 {ok, mode, problems, advice, detail}；不抛异常。
    """
    from core import self_check as sc

    cfg = getattr(trunk, "config", None) or {}
    mode = str(cfg.get("model_mode", "本地模型") or "本地模型")
    out = {"ok": False, "mode": mode, "problems": [], "advice": "", "detail": ""}
    try:
        if "云端" in mode:
            r = sc.check_cloud(trunk, timeout=timeout) or {}
            if r.get("ok"):
                out.update({
                    "ok": True,
                    "advice": "云端连通（真发过一次最小请求），可以直接聊天了。",
                    "detail": "模型：%s" % (r.get("model")
                                         or cfg.get("cloud_model", "")),
                })
                return out
            why = str(r.get("error") or "云端不可用")
            out["problems"] = ["云端连不上：" + why]
            out["advice"] = _fix_hint(why, "云端") or (
                "检查地址 / 模型名 / Key；也可以改用本地 Ollama（免费，不联网也能用）。")
            out["detail"] = why
            return out

        # 本地：先预热（让模型进程醒过来），再确认真的连得上、模型真的在
        sc.warmup_ollama(trunk)
        r = sc.check_ollama(trunk) or {}
        if not r.get("ok"):
            why = str(r.get("error") or "未响应（服务没启动？）")
            out["problems"] = ["本地 Ollama 连不上：" + why]
            out["advice"] = _fix_hint(why, "本地") or (
                "点「⬇️ 一键下载 Ollama 安装包」装上（走国内加速源），"
                "装完点「🔄 重新检测」。")
            out["detail"] = why
            return out
        models = [m for m in (r.get("models") or []) if m]
        want = str(cfg.get("local_model", "") or "").strip()
        if not models:
            out["problems"] = ["Ollama 在跑，但里面还没有任何模型"]
            out["advice"] = ("点「⬇️ 下载模型」拉一个（推荐 qwen2.5:3b，约 2GB，"
                             "带进度条、可取消）；也可以命令行 ollama pull qwen2.5:3b。")
            return out
        if want and want not in models:
            out["problems"] = ["Ollama 里没有「%s」这个模型" % want]
            out["advice"] = ("点「⬇️ 下载模型」拉「%s」，或从下拉框里选一个已装的：%s"
                             % (want, "、".join(models[:5])))
            return out
        out.update({
            "ok": True,
            "advice": "本地模型已就绪（Ollama 里 %d 个模型），可以直接聊天了。" % len(models),
            "detail": "已选：%s" % (want or models[0]),
        })
        return out
    except Exception as e:
        _x6_swallowed(__name__, e, "probe model config")
        out["problems"] = ["探测时出错：" + str(e)[:80]]
        out["advice"] = "重启程序再试；还不行到「设置 → 系统 → 深度自检」看详细报告。"
        return out
