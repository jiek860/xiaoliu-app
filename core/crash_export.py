# -*- coding: utf-8 -*-
"""崩溃日志一键导出 - 打包日志+配置+系统信息，敏感信息脱敏

脱敏为什么要按"模式"而不是按"名单"
----------------------------------
原来是一张硬编码名单：("cloud_key", "feedback_email_pass", "wecom_webhook")。
问题不是这三个漏了（实测三个都脱了），而是**将来加了新密钥就会静默漏出去** ——
而崩溃包的用途恰恰是"发给别人帮你排查"，漏一次就是真泄露。

改成模式匹配 + 名单兜底：
    ① 键名匹配 key/secret/token/password/passwd/webhook/credential → 一律脱敏
    ② 值长得像密钥的（长串字母数字、sk-/Bearer 开头）→ 也脱敏
    ③ 原名单保留作兜底（万一某个键名不含上述词）
返回 (脱敏后的配置, 脱敏了几个字段)。
"""
import os, json, re, zipfile, platform, datetime

# 键名里出现这些词就认为是敏感字段
_SECRET_KEY = re.compile(
    r"(key|secret|token|passwd|password|pass$|_pass|webhook|credential"
    r"|auth|sign|session|cookie)", re.I)
# 原硬编码名单，保留作兜底
_SECRET_KEYS = ("cloud_key", "feedback_email_pass", "wecom_webhook")
# 值长得像密钥：sk-xxx / Bearer xxx / 30+ 位无明显分隔的长串
_SECRET_VAL = re.compile(r"^(sk-|Bearer\s)|^[A-Za-z0-9_\-]{30,}$")


def _redact(cfg):
    """递归脱敏（配置可能是嵌套的），返回 (新配置, 脱敏字段数)"""
    n = 0

    def walk(o, key_hint=""):
        nonlocal n
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                # 密钥不可能是纯数字/布尔 —— 这类一律当设置放过。
                # 踩过的坑：`max_tokens_reply = 500` 因为键名含 "token" 被误脱敏，
                # 结果崩溃包少了一个真实设置，反而更难排查。
                numeric = isinstance(v, (int, float, bool)) or v is None
                if not numeric and (_SECRET_KEY.search(str(k))
                                    or str(k) in _SECRET_KEYS):
                    if v not in ("", None, 0, False):
                        n += 1
                    out[k] = "***已脱敏***"
                else:
                    out[k] = walk(v, str(k))
            return out
        if isinstance(o, list):
            return [walk(x, key_hint) for x in o]
        # 值本身像密钥才脱（避免把普通数字/路径误伤）
        if isinstance(o, str) and o and _SECRET_VAL.match(o) \
                and not o.startswith(("http://", "https://", "/", "C:", "D:")):
            n += 1
            return "***已脱敏***"
        return o

    return walk(cfg), n


class CrashExport:
    """崩溃日志导出"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def export(self, out_path=None):
        """导出崩溃日志包"""
        if not out_path:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(desk, "小6崩溃_%s.zip" % now)

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            logs_dir = os.path.join(self.base, "data", "logs")
            if os.path.exists(logs_dir):
                for f in os.listdir(logs_dir):
                    fp = os.path.join(logs_dir, f)
                    if os.path.isfile(fp):
                        z.write(fp, "logs/" + f)

            cfg_path = os.path.join(self.base, "data", "config.json")
            cfg_note = ""
            if os.path.exists(cfg_path):
                try:
                    cfg = json.load(open(cfg_path, encoding="utf-8"))
                    cfg, n_red = _redact(cfg)
                    z.writestr("config.json",
                               json.dumps(cfg, ensure_ascii=False, indent=2))
                    cfg_note = "config.json 已包含（脱敏 %d 个字段）" % n_red
                except Exception as e:
                    # 原来这里是 except: pass —— 崩溃包里就**没有 config.json 了**，
                    # 而拿到包的人（帮你排查的人）不会知道少了东西。
                    # 现在写一份说明进包里，并让它出现在返回值里。
                    cfg_note = ("config.json 没能打包（%s: %s），"
                                "排查时少了配置信息"
                                % (type(e).__name__, str(e)[:60]))
                    try:
                        z.writestr("config_读取失败.txt", cfg_note)
                    except Exception:
                        pass

            info = "OS: %s\nPython: %s" % (platform.platform(), platform.python_version())
            z.writestr("system_info.txt", info)
            if cfg_note:
                z.writestr("打包说明.txt", cfg_note)

        r = {"ok": True, "文件": out_path}
        if cfg_note:
            r["打包说明"] = cfg_note
        return r

    def run(self, *a):
        return self.export()
