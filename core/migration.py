# -*- coding: utf-8 -*-
"""一键迁移新电脑 —— 导出/导入完整迁移包（完整版）

导出端（2026-10-13 修，保留）
------------------------------
写不进 zip 的文件原来是 ``except: pass`` 静默跳过的，最后照样返回
``{"ok": True}``。**这比导出失败更危险** —— 用户以为备份完整，换电脑才
发现少了数据。现在把跳过的文件和原因一并报出来。

导入端（2026-11-02 补）
----------------------
1. **不再照着包里的路径乱写**：原来 ``extractall(self.base)`` 会照着
   ``../../`` 往程序外面写（zip slip）。现在每个成员过 ``safe_join``。
2. **覆盖前先确认**：``overwrite=False``（默认）时，如果包里会盖掉现有
   数据文件，就返回 ``需要确认=True`` + 将被覆盖的清单，**一个字节都不写**。
   确认后再传 ``overwrite=True``。原来没有这一步，双击一下就把当前数据
   覆盖成别人的了。
3. 解压结果报 ``解压`` / ``拒绝`` / ``覆盖`` 三个数，出问题看得见。
"""
import datetime
import os
import zipfile

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

from core.path_safety import safe_join

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

PACK_DIRS = ("data", "core", "modules", "gui")
SKIP_EXT = (".pyc", ".pyo")
SKIP_DIR_PARTS = ("__pycache__", ".git")


class Migration:
    """一键迁移新电脑"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    # ------------------------------------------------------------------
    def export(self, out_path=None):
        """导出完整迁移包（报告打包数与跳过明细）"""
        if not out_path:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            now = datetime.datetime.now().strftime("%Y%m%d")
            out_path = os.path.join(desk, "小6迁移包_%s.zip" % now)

        packed = 0
        skipped = []          # [(相对路径, 原因)]
        try:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
                readme = ("小6智能体迁移包\n导出时间: %s\n\n使用方法:\n"
                          "1. 在新电脑上运行程序的「导入迁移包」\n"
                          "2. 确认覆盖提示后再覆盖\n3. 启动即可"
                          % datetime.datetime.now())
                z.writestr("迁移说明.txt", readme)

                for d in PACK_DIRS:
                    src = os.path.join(self.base, d)
                    if not os.path.isdir(src):
                        continue
                    for root, _, files in os.walk(src):
                        if any(p in root for p in SKIP_DIR_PARTS):
                            continue
                        for f in files:
                            if f.endswith(SKIP_EXT):
                                continue
                            fp = os.path.join(root, f)
                            rel = os.path.relpath(fp, self.base)
                            try:
                                z.write(fp, rel)
                                packed += 1
                            except Exception as e:
                                # 不再静默：记下谁没进去、为什么
                                skipped.append(
                                    (rel, "%s: %s"
                                     % (type(e).__name__, str(e)[:60])))
        except Exception as e:
            _x6_swallowed(__name__, e, "migration export")
            return {"ok": False, "error": "写不出迁移包：%s: %s"
                                        % (type(e).__name__, str(e)[:60]),
                    "文件": out_path}

        r = {"ok": True, "文件": out_path, "已打包": packed}
        if skipped:
            r["跳过"] = len(skipped)
            r["跳过明细"] = ["%s（%s）" % (p, why) for p, why in skipped[:10]]
            if len(skipped) > 10:
                r["跳过明细"].append("… 还有 %d 个" % (len(skipped) - 10))
            r["提示"] = ("有 %d 个文件没能打进包里（上面列了前 10 个），"
                         "换电脑后这些内容会缺" % len(skipped))
        return r

    # ------------------------------------------------------------------
    def _plan(self, zip_path):
        """预读包：返回 (可写入成员列表, 越界成员, 会覆盖的文件, 总字节)"""
        members, rejected, overwrite, size = [], [], [], 0
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                size += int(info.file_size or 0)
                target = safe_join(self.base, info.filename)
                if target is None:
                    rejected.append(info.filename)
                    continue
                members.append(info.filename)
                if os.path.exists(target):
                    overwrite.append(info.filename)
        return members, rejected, overwrite, size

    def import_zip(self, zip_path, overwrite=False):
        """导入迁移包（默认只做检查，确认后才真写）"""
        if not os.path.isfile(zip_path):
            return {"ok": False, "error": "文件不存在"}
        try:
            members, rejected, will_overwrite, size = self._plan(zip_path)
        except Exception as e:
            _x6_swallowed(__name__, e, "migration plan")
            return {"ok": False, "error": "读不了迁移包：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}

        if not members:
            return {"ok": False, "error": "包里没有可导入的文件",
                    "拒绝": rejected}

        r = {"文件数": len(members), "总字节": size}
        if will_overwrite and not overwrite:
            # 关键：一个字节都不写，先让人确认
            r.update({"ok": False, "需要确认": True,
                      "将覆盖": will_overwrite[:10],
                      "说明": ("有 %d 个文件会被覆盖（上面列了前 10 个）。"
                               "确认后用 import_zip(path, overwrite=True) 再导一次"
                               % len(will_overwrite))})
            if rejected:
                r["拒绝"] = rejected
            return r

        written, failed = [], []
        rejected = list(rejected)      # 路径不安全的成员：拒绝是保护生效，不算写失败
        try:
            with zipfile.ZipFile(zip_path) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    target = safe_join(self.base, info.filename)
                    if target is None:
                        if info.filename not in rejected:
                            rejected.append(info.filename)
                        continue
                    try:
                        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
                        with z.open(info) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        written.append(info.filename)
                    except Exception as e:
                        _x6_swallowed(__name__, e, "migration extract")
                        failed.append("%s（%s）" % (info.filename,
                                                   type(e).__name__))
        except Exception as e:
            _x6_swallowed(__name__, e, "migration import")
            return {"ok": False, "error": "解压中断：%s: %s"
                                        % (type(e).__name__, str(e)[:60]),
                    "已写入": len(written)}

        # ok 的口径：「该写的写进去了」。被安全规则挡下的成员单独报 拒绝，
        # 不能因为包里夹带一个 ../evil.txt 就把整次导入判成失败 ——
        # 那会让用户以为数据没恢复，从而反复重导。
        r.update({"ok": bool(written), "解压": len(written),
                  "覆盖": len(will_overwrite)})
        if written:
            r["msg"] = "迁移完成，请重启程序"
        if rejected:
            r["拒绝"] = rejected[:10]
            r["说明"] = "有 %d 个成员路径不安全，已拒绝写入" % len(rejected)
        if failed:
            r["写入失败"] = failed[:10]
            r["说明"] = "有 %d 个成员没写进去（上面列了前 10 个）" % len(failed)
            if not written:
                r["ok"] = False
        return r

    def run(self, *a):
        return {"功能": "一键迁移", "导出": "export(out_path)",
                "导入": "import_zip(path, overwrite=False)",
                "说明": "导入默认只检查覆盖范围，确认后再 overwrite=True"}
