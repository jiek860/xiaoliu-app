# -*- coding: utf-8 -*-
"""P2-09: 人格市场 —— 人格包导出 / 导入（完整版）

人格包是**要分给别人、也要从别人手里收**的文件，所以按"不可信压缩包"处理。

2026-11-02 补的四件事
--------------------
1. **清单 + 校验和**：包里多一份 ``manifest.json``（版本、创建时间、每个
   文件的 sha256）。导入时逐项校验，对不上就**拒绝** —— 原来直接
   ``extractall``，改一位都能悄悄换掉你的人格。
2. **防目录穿越（zip slip）**：``extractall`` 会照着包里的 ``../../x``
   往外面写。现在每个成员都过 ``safe_join``，越界的记进「拒绝」。
3. **不覆盖模式真的能用**：原来 ``overwrite=False`` 直接返回
   "暂未实现"。现在解压到 ``data/personality_import_<时间戳>/`` 先放着，
   用户确认后再自己覆盖 —— 既不假装成功，也不丢包。
4. **只认人格文件**：包里的 ``core/xxx.py``、``startup/xxx.bat`` 一律不落盘
   （人格包没理由带代码），列在「忽略」里。

导出内容：``personality.json`` + ``memory_cards.jsonl``（有哪个pack哪个）。
"""
import hashlib
import json
import os
import time
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

PACK_VERSION = "1.1"
MANIFEST = "manifest.json"
PACK_FILES = ("personality.json", "memory_cards.jsonl")
READ_ME = "说明.txt"


class PersonalityMarket:
    """人格包导出 / 校验 / 导入"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.data_dir = data_path(trunk)

    # ------------------------------------------------------------------
    @staticmethod
    def _sha256(data):
        return hashlib.sha256(data).hexdigest()

    def export_personality(self, out_path=None):
        """导出人格包（带清单与校验和）"""
        if not out_path:
            out_path = data_path(
                self.trunk, "personality_pack_%s.zip"
                % time.strftime("%Y%m%d_%H%M%S"))
        missing, files = [], []
        for name in PACK_FILES:
            src = os.path.join(self.data_dir, name)
            if not os.path.isfile(src):
                missing.append(name)
                continue
            try:
                with open(src, "rb") as f:
                    raw = f.read()
            except Exception as e:
                _x6_swallowed(__name__, e, "read pack file")
                missing.append("%s（读不出来）" % name)
                continue
            files.append({"名称": name, "sha256": self._sha256(raw),
                          "字节": len(raw)})

        if not files:
            return {"ok": False, "error": "没有人格文件可导出",
                    "缺少": missing}

        manifest = {"版本": PACK_VERSION,
                    "创建": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "文件": files}
        try:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
                for name in PACK_FILES:
                    src = os.path.join(self.data_dir, name)
                    if os.path.isfile(src):
                        z.write(src, name)
                z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False,
                                                indent=2))
                z.writestr(READ_ME, "小6人格包 v%s，导入后会覆盖当前人格"
                                    % PACK_VERSION)
        except Exception as e:
            _x6_swallowed(__name__, e, "write personality pack")
            return {"ok": False, "error": "写不出人格包：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}

        r = {"ok": True, "path": out_path, "文件": out_path,
             "打包": [f["名称"] for f in files], "版本": PACK_VERSION}
        if missing:
            r["缺少"] = missing
            r["提示"] = "这些内容本来就没有，没进包：%s" % "、".join(missing)
        return r

    # ------------------------------------------------------------------
    def verify(self, zip_path):
        """校验包内文件的 sha256（对照 manifest）"""
        if not os.path.isfile(zip_path):
            return {"ok": False, "校验": "打不开", "错误": "文件不存在"}
        try:
            with zipfile.ZipFile(zip_path) as z:
                names = z.namelist()
                if MANIFEST not in names:
                    return {"ok": True, "校验": "未提供清单",
                            "说明": "这个包没有 manifest，只能当作纯文件导入"}
                manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
                bad, ok_files = [], []
                for item in (manifest.get("文件") or []):
                    name = str(item.get("名称") or "")
                    if name not in names:
                        bad.append("%s（包里没有这个文件）" % name)
                        continue
                    got = self._sha256(z.read(name))
                    if got != item.get("sha256"):
                        bad.append("%s（内容与清单不一致）" % name)
                    else:
                        ok_files.append(name)
        except Exception as e:
            _x6_swallowed(__name__, e, "verify pack")
            return {"ok": False, "校验": "读不出来",
                    "错误": "%s: %s" % (type(e).__name__, str(e)[:60])}
        r = {"ok": not bad, "校验": "通过" if not bad else "不匹配",
             "通过项": ok_files, "版本": str(manifest.get("版本") or "")}
        if bad:
            r["不匹配"] = bad
            r["说明"] = "校验没过：%s" % "、".join(bad[:5])
        return r

    # ------------------------------------------------------------------
    def import_personality(self, zip_path, overwrite=True, force=False):
        """导入人格包。

        ``overwrite=False`` → 先解到 ``data/personality_import_<时间>/``；
        ``force=True`` 可以跳过校验（只给"我自己的包、给谁改了都认"用）。
        """
        if not os.path.isfile(zip_path):
            return {"ok": False, "error": "文件不存在"}
        ver = self.verify(zip_path)
        if not ver.get("ok") and not force:
            return {"ok": False, "校验": ver.get("校验"),
                    "error": "校验没过，已拒绝导入（%s）"
                             % str(ver.get("说明") or ver.get("错误") or ""),
                    "不匹配": ver.get("不匹配")}

        dest = self.data_dir if overwrite else data_path(
            self.trunk, "personality_import_%s" % time.strftime("%Y%m%d_%H%M%S"))
        try:
            os.makedirs(dest, exist_ok=True)
        except Exception as e:
            _x6_swallowed(__name__, e, "import dest")
            return {"ok": False, "error": "目标目录不可写：%s" % str(e)[:60]}

        imported, rejected, ignored = [], [], []
        try:
            with zipfile.ZipFile(zip_path) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    if os.path.basename(name) not in PACK_FILES:
                        ignored.append(name)
                        continue
                    target = safe_join(dest, name)
                    if target is None:
                        rejected.append(name)       # 目录穿越/绝对路径
                        continue
                    try:
                        with z.open(info) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                    except Exception as e:
                        _x6_swallowed(__name__, e, "extract pack file")
                        rejected.append("%s（写不进去）" % name)
                        continue
                    imported.append(name)
        except Exception as e:
            _x6_swallowed(__name__, e, "open pack")
            return {"ok": False, "error": "读不了人格包：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}

        if not imported:
            return {"ok": False, "error": "包里没有可用的人格文件",
                    "拒绝": rejected, "忽略": ignored}

        r = {"ok": True, "导入": imported, "校验": ver.get("校验"),
             "目录": dest}
        if overwrite:
            r["msg"] = "人格导入完成，重启生效"
        else:
            r["msg"] = ("没有覆盖当前人格：先解到了这个目录，"
                        "确认没问题再自己覆盖（%s）" % dest)
        if rejected:
            r["拒绝"] = rejected
            r["说明"] = "有 %d 个成员被拒绝（越界或写不进去）" % len(rejected)
        if ignored:
            r["忽略"] = ignored[:10]
        return r

    def run(self, *a):
        have = [n for n in PACK_FILES
                if os.path.isfile(os.path.join(self.data_dir, n))]
        return {"功能": "人格导出/导入", "版本": PACK_VERSION,
                "可导出": have,
                "说明": "包内带 manifest 校验和；导入时校验不过会拒绝"}
