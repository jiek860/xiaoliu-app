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
from core.safe_http import open_url as safe_open_url
import hashlib
import json
import time
import urllib.error
import urllib.request

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_OLLAMA = "http://localhost:11434"
RECOMMENDED_LOCAL_MODEL = "qwen2.5:3b"
OLLAMA_DOWNLOAD = "https://ollama.com/download"

# 常见云端服务商预设 —— 点一下就自动填好"地址 + 模型名"，
# 不用用户自己去文档里抄 URL（抄错一个字符就是 404，很难查）。
#
# ⚠️ 每个地址都是**实测过的**（2026-10-13）：向它发一个不带 Key 的请求，
#    返回 401 = 地址有效且需要鉴权。返回 404 的一律没收进来。
#
# "国内直连"这一列如实标注：OpenAI 实测**连接超时**（国内网络到不了），
#    所以没放进列表 —— 收了它只会让用户白填一次再失败。
CLOUD_PROVIDERS = [
    {"名字": "智谱 GLM", "地址": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
     "模型": "glm-4-flash", "申请": "https://open.bigmodel.cn",
     "备注": "有免费额度，国内直连"},
    {"名字": "DeepSeek",
     "地址": "https://api.deepseek.com/chat/completions",
     "模型": "deepseek-chat", "申请": "https://platform.deepseek.com",
     "备注": "便宜，国内直连"},
    {"名字": "通义千问",
     "地址": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
     "模型": "qwen-plus", "申请": "https://dashscope.console.aliyun.com",
     "备注": "阿里，国内直连"},
    {"名字": "月之暗面 Kimi",
     "地址": "https://api.moonshot.cn/v1/chat/completions",
     "模型": "moonshot-v1-8k", "申请": "https://platform.moonshot.cn",
     "备注": "长文本，国内直连"},
    {"名字": "硅基流动",
     "地址": "https://api.siliconflow.cn/v1/chat/completions",
     "模型": "Qwen/Qwen2.5-7B-Instruct", "申请": "https://cloud.siliconflow.cn",
     "备注": "开源模型聚合，国内直连"},
]


def provider_names():
    """给下拉框用的名字列表（"自定义"排在最后，表示不预设）"""
    return [p["名字"] for p in CLOUD_PROVIDERS] + ["自定义（自己填）"]


def find_provider(name):
    """按名字找预设；找不到返回 None"""
    for p in CLOUD_PROVIDERS:
        if p["名字"] == name:
            return p
    return None


def probe_ollama(url=None, timeout=3):
    """探测 Ollama 是否在跑、装了哪些模型。不抛异常，失败也返回结构化结果。"""
    url = (url or DEFAULT_OLLAMA).rstrip("/")
    out = {"url": url, "reachable": False, "models": [], "error": ""}
    try:
        from core.net_guard import get_net_guard
        d = get_net_guard(None).check(
            url + "/api/tags", module="model_setup", purpose="local_model")
        if not d.get("allow"):
            out["error"] = "网络策略拒绝: " + str(d.get("reason"))
            return out
        req = urllib.request.Request(url + "/api/tags")
        with safe_open_url(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        out["reachable"] = True
        out["models"] = [str(m.get("name", "")) for m in (data.get("models") or [])]
    except Exception as e:
        out["error"] = str(e)[:100]
    return out


def _plain_key(key):
    """把“配置里的密文”还原成明文；不是密文就原样返回。

    为什么需要它
    ------------
    data/config.json 里的 cloud_key 是 DPAPI 密文（`dpapi:v1:...`），
    `core.config.load_config()` 读的时候会自动解密。但只要有一条路径
    没走 load_config（旧备份、外部脚本、手抄配置），拿到的就是密文；
    把它当 Bearer 发出去，服务端一律回 **401「令牌已过期或验证不正确」**，
    看起来像"Key 失效了"，实际只是把密文当明文用。
    这里统一兜一层：能解就解，解不开就返回空串（调用方据此报可读错误）。
    """
    text = str(key or "").strip()
    if not text:
        return ""
    try:
        from core.secret_store import PREFIX, decrypt_value
        if text.startswith(PREFIX):
            plain = decrypt_value(text)
            # 解不开时 decrypt_value 原样返回，仍然带前缀
            return "" if str(plain).startswith(PREFIX) else str(plain).strip()
    except Exception as e:  # 静默是故意的：解密失败等价于"Key 不可用"
        _x6_swallowed(__name__, e, "best-effort fallback")
        return ""
    return text


def test_cloud(url=None, model=None, key=None, timeout=8):
    """真的打一次最小请求，确认「地址 + 模型名 + Key」三者能用。

    为什么需要它
    ------------
    check() 只看配置齐不齐：Key 填错一个字符，它照样返回 ready。
    用户要到第一次聊天才发现 401，而那时看到的只是一句"出了点问题"。
    首次配置里点一下「测试云端 Key」就能当场知道错在哪（401 / 404 / 超时）。

    不抛异常、不打印 Key；返回 {ok, code, status, message}。
    """
    url = str(url or "").strip()
    model = str(model or "").strip()
    key_raw = str(key or "").strip()
    key = _plain_key(key_raw)
    if key_raw and not key:
        return {"ok": False, "code": "key_encrypted", "status": 0,
                "message": "这里存的是加密后的 Key，当前用户解不开；"
                           "请在服务商后台重新复制一份明文 Key 填进来。"}
    if not url:
        return {"ok": False, "code": "no_url", "status": 0,
                "message": "先填云端 API 地址（选上面的服务商会自动填）。"}
    if not model:
        return {"ok": False, "code": "no_model", "status": 0,
                "message": "先填模型名，例如 glm-4-flash。"}
    if not key:
        return {"ok": False, "code": "no_key", "status": 0,
                "message": "先填 API Key（在服务商后台申请）。"}

    try:
        from core.net_guard import get_net_guard
        gate = get_net_guard(None).check(
            url, module="model_setup", purpose="cloud_model", method="POST")
        if not gate.get("allow"):
            return {"ok": False, "code": "net_denied", "status": 0,
                    "message": "网络策略拒绝了这次请求：%s（设置 → 安全中心 可加白名单）"
                               % str(gate.get("reason") or "")}
    except Exception as e:  # 静默是故意的：策略自身异常不该让测试入口失效
        _x6_swallowed(__name__, e, "best-effort fallback")

    payload = json.dumps({
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "ping"}],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    })
    try:
        with safe_open_url(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            status = int(getattr(r, "status", 200) or 200)
    except urllib.error.HTTPError as e:
        code = int(getattr(e, "code", 0) or 0)
        hint = {
            401: "Key 不对或已过期，去服务商后台重新复制一份。",
            403: "这个 Key 没有该模型的权限，或账号被限制。",
            404: "地址不对：要用服务商文档里 chat/completions 的完整地址。",
            429: "请求太频繁或额度用完了，稍后再试或换个模型。",
        }.get(code, "服务端返回 %d，检查地址和模型名。" % code)
        return {"ok": False, "code": "http_%d" % code, "status": code,
                "message": hint}
    except Exception as e:  # 静默是故意的：超时/断网都归一成可读提示
        return {"ok": False, "code": "network", "status": 0,
                "message": "连不上：%s（检查网络/代理）" % str(e)[:80]}

    try:
        data = json.loads(body)
    except Exception as e:  # 静默是故意的：部分网关会返回非 JSON
        _x6_swallowed(__name__, e, "best-effort fallback")
        data = {}
    if isinstance(data, dict) and (data.get("choices") or data.get("output")):
        return {"ok": True, "code": "ok", "status": status,
                "message": "云端连通，模型「%s」可以正常回复。" % model}
    err = ""
    if isinstance(data, dict):
        e = data.get("error")
        if isinstance(e, dict):
            err = str(e.get("message") or "")[:120]
        elif e:
            err = str(e)[:120]
    return {"ok": False, "code": "bad_response", "status": status,
            "message": "接口有响应，但不像正常回复：%s" % (err or body[:80])}


# ── 带缓存的连通探测（自检用）─────────────────────────────────
# 为什么需要缓存：系统自检每点一次就要打一次真实请求。用户排查问题时会
# 连着点好几次 —— 每次都花额度、每次都要等 1~3 秒。同一组（地址+模型+Key）
# 在 TTL 内复用上次结果。
# ⚠️ 缓存键只存 Key 的 sha256 指纹，**不存明文/密文**：这个 dict 活在整个
#    进程生命周期里，存明文等于把密钥摊在内存中，崩溃转储会把它们带出去。
CLOUD_PROBE_TTL = 300
cloud_probe_cache = {}           # 指纹 -> (探测时间戳, 结果 dict)


def cloud_fingerprint(url, model, key):
    """缓存键：地址+模型+Key 的摘要。Key 不落库，只留不可逆指纹。"""
    raw = "%s\n%s\n%s" % (url, model, key)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


def probe_cloud_cached(url=None, model=None, key=None, timeout=5):
    """在 test_cloud 外面套一层 TTL 缓存，供自检调用。

    返回 `{ok, url, model, latency, code, status, cached[, error]}`。
    不抛异常 —— 它跑在自检里，崩了会让整份报告消失。
    """
    url = str(url or "").strip()
    model = str(model or "").strip()
    key = str(key or "").strip()
    try:
        if not url or not key:
            return {"ok": False, "error": "未配置"}
        fp = cloud_fingerprint(url, model, key)
        hit = cloud_probe_cache.get(fp)
        if hit and (time.time() - hit[0]) < CLOUD_PROBE_TTL:
            out = dict(hit[1])
            out["cached"] = True
            return out
        t0 = time.time()
        r = test_cloud(url, model, key, timeout=timeout) or {}
        out = {"ok": bool(r.get("ok")),
               "code": str(r.get("code") or "")[:32],
               "status": int(r.get("status") or 0),
               "latency": round(time.time() - t0, 2),
               "url": url, "model": model, "cached": False}
        if not out["ok"]:
            out["error"] = str(r.get("message") or "云端不可用")[:80]
        cloud_probe_cache[fp] = (time.time(), dict(out))
        return out
    except Exception as e:  # 静默是故意的：探测失败只降健康分，不该炸自检
        _x6_swallowed(__name__, e, "cloud probe")
        return {"ok": False, "error": str(e)[:80]}


def check(trunk, probe=True):
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
    #
    # probe=False：调用方明确不需要网络结果（启动判定 / 向导关闭后），
    # 这时 reachable=None 表示"没检测"，不是"连不上"  否则会误报问题。
    need_local = ("本地" in mode) or ("双" in mode)
    if need_local and probe:
        ollama = probe_ollama(cfg.get("ollama_url") or DEFAULT_OLLAMA)
    elif need_local:
        ollama = {"url": str(cfg.get("ollama_url") or DEFAULT_OLLAMA),
                  "reachable": None, "models": [],
                  "error": "已跳过网络探测"}
    else:
        ollama = {"url": str(cfg.get("ollama_url") or DEFAULT_OLLAMA),
                  "reachable": False, "models": [],
                  "error": "当前不是本地模式，未检测"}

    problems = []
    cloud_ok = bool(cloud["key_set"] and cloud["url"])
    local_ok = False
    unknown = ollama.get("reachable") is None

    if unknown:
        # 没探测：只能按"配置里有没有写模型名"判断
        local_ok = bool(local_model)
    elif ollama["reachable"]:
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
            if unknown:
                problems.append("本地模型没指定（已跳过网络检测）")
            elif not ollama["reachable"]:
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
        if unknown:
            if not local_model:
                problems.append("没指定本地模型名")
        elif not ollama["reachable"]:
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
    elif unknown:
        advice = "配置已保存。想确认 Ollama 是否在线，在向导里点「保存并检测」。"
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
