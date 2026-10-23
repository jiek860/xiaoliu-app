# -*- coding: utf-8 -*-
"""远程/本地 Skills 目录与下载。

安全边界：
- 远程目录只从固定 GitHub raw 地址读取；
- 每个技能包必须有 sha256，下载后先校验再交给 SkillRegistry；
- 本地开发/打包环境优先使用 core/skills_catalog.json 和 skills_repo/。
"""
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request

REMOTE_CATALOG_URL = (
    "https://raw.githubusercontent.com/jiek860/xiaoliu-app/main/"
    "core/skills_catalog.json")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED_CATALOG = os.path.join(BASE, "core", "skills_catalog.json")


def _valid_catalog(items):
    if not isinstance(items, list) or len(items) > 100:
        return False
    for s in items:
        if not isinstance(s, dict):
            return False
        if not all(str(s.get(k) or "").strip() for k in ("name", "title", "desc")):
            return False
        if not str(s.get("sha256") or "").strip():
            return False
        if not (s.get("download_url") or s.get("local_path")):
            return False
    return True


def _load_bundled():
    try:
        with open(BUNDLED_CATALOG, encoding="utf-8") as f:
            data = json.load(f)
        return data if _valid_catalog(data) else []
    except Exception:
        return []


def fetch_remote_catalog():
    """优先远程；网络不可用时回退到随程序分发的本地目录。"""
    try:
        req = urllib.request.Request(
            REMOTE_CATALOG_URL, headers={"User-Agent": "xiaoliu-app"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if _valid_catalog(data):
            return {"ok": True, "skills": data, "source": "remote"}
    except Exception:  # 静默是故意的：远程不可用时回退随包目录
        pass
    local = _load_bundled()
    if local:
        return {"ok": True, "skills": local, "source": "bundled"}
    return {"ok": False, "error": "技能目录不可用"}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_skill(skill_name, target_dir=None):
    """准备一个技能包，返回本地 zip 路径；调用方再交给 SkillRegistry 安装。"""
    catalog_r = fetch_remote_catalog()
    if not catalog_r.get("ok"):
        return catalog_r
    item = next((s for s in catalog_r["skills"]
                 if s.get("name") == skill_name), None)
    if not item:
        return {"ok": False, "error": "技能不在目录里"}

    tmp_dir = target_dir or tempfile.mkdtemp(prefix="x6skill_")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_zip = os.path.join(tmp_dir, str(skill_name) + ".x6skill")
    local_path = str(item.get("local_path") or "")
    if local_path:
        # local_path 是相对项目根的路径；打包后同样保持这个布局
        src = local_path if os.path.isabs(local_path) else os.path.join(BASE, local_path)
        if not os.path.isfile(src):
            return {"ok": False, "error": "本地技能包不存在: " + src}
        shutil.copy2(src, tmp_zip)
    else:
        url = str(item.get("download_url") or "")
        if not url.startswith("https://"):
            return {"ok": False, "error": "只允许 HTTPS 技能下载地址"}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "xiaoliu-app"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with open(tmp_zip, "wb") as f:
                f.write(data)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    expected = str(item.get("sha256") or "").lower()
    actual = _sha256(tmp_zip)
    if not expected or actual != expected:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass
        return {"ok": False, "error": "sha256 校验失败"}
    return {"ok": True, "zip_path": tmp_zip, "skill_name": skill_name,
            "source": catalog_r.get("source", "")}
