# -*- coding: utf-8 -*-
"""一键迁移新电脑 - 导出/导入完整迁移包"""
import os, zipfile, datetime


class Migration:
    """一键迁移新电脑"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def export(self, out_path=None):
        """导出完整迁移包

        关于"跳过"：写不进 zip 的文件原来是 `except: pass` 静默跳过的，
        最后照样返回 {"ok": True}。**这比导出失败更危险** —— 用户以为备份完整，
        换电脑才发现少了数据。现在把跳过的文件和原因一并报出来。
        """
        if not out_path:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            now = datetime.datetime.now().strftime("%Y%m%d")
            out_path = os.path.join(desk, "小6迁移包_%s.zip" % now)

        dirs_to_pack = ["data", "core", "modules", "gui"]
        skip_ext = (".pyc", ".pyo", "__pycache__", ".git")

        packed = 0
        skipped = []          # [(相对路径, 原因)]
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            readme = "小6智能体迁移包\n导出时间: %s\n\n使用方法:\n1. 解压到新电脑\n2. 覆盖文件\n3. 启动即可" % datetime.datetime.now()
            z.writestr("迁移说明.txt", readme)

            for d in dirs_to_pack:
                src = os.path.join(self.base, d)
                if not os.path.exists(src):
                    continue
                for root, _, files in os.walk(src):
                    if "__pycache__" in root or ".git" in root:
                        continue
                    for f in files:
                        if f.endswith(skip_ext):
                            continue
                        fp = os.path.join(root, f)
                        rel = os.path.relpath(fp, self.base)
                        try:
                            z.write(fp, rel)
                            packed += 1
                        except Exception as e:
                            # 不再静默：记下谁没进去、为什么
                            skipped.append((rel, "%s: %s"
                                            % (type(e).__name__, str(e)[:60])))

        r = {"ok": True, "文件": out_path, "已打包": packed}
        if skipped:
            r["跳过"] = len(skipped)
            r["跳过明细"] = ["%s（%s）" % (p, why) for p, why in skipped[:10]]
            if len(skipped) > 10:
                r["跳过明细"].append("… 还有 %d 个" % (len(skipped) - 10))
            r["提示"] = ("有 %d 个文件没能打进包里（上面列了前 10 个），"
                         "换电脑后这些内容会缺" % len(skipped))
        return r

    def import_zip(self, zip_path):
        """导入迁移包"""
        if not os.path.exists(zip_path):
            return {"ok": False, "error": "文件不存在"}
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(self.base)
            return {"ok": True, "msg": "迁移完成，请重启程序"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}

    def run(self, *a):
        return {"功能": "一键迁移", "导出": "export()", "导入": "import_zip(path)"}
