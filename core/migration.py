# -*- coding: utf-8 -*-
"""一键迁移新电脑 - 导出/导入完整迁移包"""
import os, zipfile, json, datetime


class Migration:
    """一键迁移新电脑"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def export(self, out_path=None):
        """导出完整迁移包"""
        if not out_path:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            now = datetime.datetime.now().strftime("%Y%m%d")
            out_path = os.path.join(desk, "小6迁移包_%s.zip" % now)

        dirs_to_pack = ["data", "core", "modules", "gui"]
        skip_ext = (".pyc", ".pyo", "__pycache__", ".git")

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
                        except Exception:
                            pass

        return {"ok": True, "文件": out_path}

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
