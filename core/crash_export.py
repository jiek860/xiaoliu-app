# -*- coding: utf-8 -*-
"""崩溃日志一键导出 - 打包日志+配置+系统信息，敏感信息脱敏"""
import os, json, zipfile, platform, datetime


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
            if os.path.exists(cfg_path):
                try:
                    cfg = json.load(open(cfg_path, encoding="utf-8"))
                    for k in ("cloud_key", "feedback_email_pass", "wecom_webhook"):
                        if k in cfg:
                            cfg[k] = "***已脱敏***"
                    z.writestr("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
                except Exception:
                    pass

            info = "OS: %s\nPython: %s" % (platform.platform(), platform.python_version())
            z.writestr("system_info.txt", info)

        return {"ok": True, "文件": out_path}

    def run(self, *a):
        return self.export()
