# -*- coding: utf-8 -*-
"""文件上传 v2.1 - 上传 + 读取 + 列表 + 搜索 + 删除 + 统计 + 清空 + 导出"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, time
from core.safe import safe
from core.path_safety import safe_join, safe_name
from core.plugin_errors import error_result as _error_result
from modules.base import BaseModule


def _err(message, code="PLUGIN_BAD_INPUT"):
    """历史 ``{"错误": ...}`` 的统一出口（标准 6.1 结构化错误）"""
    return _error_result(code, str(message)[:300], module="file_upload")


class FileUpload(BaseModule):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "file_upload"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.upload_dir = os.path.join(trunk.base if trunk else ".", "data", "uploads")
        os.makedirs(self.upload_dir, exist_ok=True)
        self.upload_count = 0
        self.history = []

    @safe
    def upload(self, file_path):
        """上传文件"""
        if not os.path.exists(file_path):
            return _err("文件不存在", "PLUGIN_BAD_PATH")

        import shutil
        fname = os.path.basename(file_path)
        dst = os.path.join(self.upload_dir, fname)
        shutil.copy2(file_path, dst)

        # 读取文本内容
        content = ""
        if fname.endswith((".txt", ".py", ".md", ".json", ".csv")):
            try:
                content = open(dst, encoding="utf-8", errors="ignore").read()[:1000]
            except Exception as e:
                _x6_swallowed(__name__, e)

        self.upload_count += 1
        self.history.append({"文件": fname, "时间": time.strftime("%m-%d %H:%M")})
        return {"ok": True, "文件名": fname, "路径": dst, "内容预览": content[:500]}

    @safe
    def list_files(self):
        """列出所有上传的文件"""
        files = os.listdir(self.upload_dir)
        return {"文件数": len(files), "文件": files}

    @safe
    def search(self, keyword):
        """搜索文件"""
        files = os.listdir(self.upload_dir)
        found = [f for f in files if keyword in f]
        return {"找到": len(found), "文件": found}

    @safe
    def delete_file(self, fname):
        """删除文件（只允许 upload_dir 内的一级文件名）"""
        path = safe_join(self.upload_dir, safe_name(fname, default=""))
        if not path or not os.path.isfile(path):
            return _err("文件不存在或路径非法", "PLUGIN_BAD_PATH")
        os.remove(path)
        return {"ok": True}

    @safe
    def read_file(self, fname):
        """读取文件内容（只允许 upload_dir 内的一级文件名）"""
        path = safe_join(self.upload_dir, safe_name(fname, default=""))
        if not path or not os.path.isfile(path):
            return _err("文件不存在或路径非法", "PLUGIN_BAD_PATH")
        try:
            content = open(path, encoding="utf-8", errors="ignore").read()
            return {"文件名": os.path.basename(path), "内容": content[:1000]}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    def get_history(self, count=10):
        """获取上传历史"""
        return {"历史": self.history[-count:]}

    @safe
    def stats(self):
        """统计"""
        files = os.listdir(self.upload_dir)
        total_size = sum(os.path.getsize(os.path.join(self.upload_dir, f)) for f in files)
        return {
            "总上传次数": self.upload_count,
            "当前文件数": len(files),
            "总大小": f"{total_size//1024}KB"
        }

    @safe
    def clear_all(self):
        """清空所有文件"""
        for f in os.listdir(self.upload_dir):
            os.remove(os.path.join(self.upload_dir, f))
        self.history = []
        return {"ok": True}

    def run(self, *args):
        if args:
            return self.upload(args[0])
        return self.stats()

    @safe
    def get_file_info(self, fname):
        """获取文件信息"""
        path = os.path.join(self.upload_dir, fname)
        if not os.path.exists(path):
            return _err("文件不存在", "PLUGIN_BAD_PATH")
        size = os.path.getsize(path)
        return {"文件名": fname, "大小KB": size // 1024}

    @safe
    def get_file_types(self):
        """统计文件类型"""
        files = os.listdir(self.upload_dir)
        types = {}
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            types[ext] = types.get(ext, 0) + 1
        return {"文件类型统计": types}

    @safe
    def rename_file(self, old_name, new_name):
        """重命名文件（两端都只允许 upload_dir 内的一级文件名）"""
        old_path = safe_join(self.upload_dir, safe_name(old_name, default=""))
        new_path = safe_join(self.upload_dir, safe_name(new_name, default=""))
        if not old_path or not new_path:
            return _err("路径非法", "PLUGIN_BAD_PATH")
        if not os.path.exists(old_path):
            return _err("文件不存在", "PLUGIN_BAD_PATH")
        os.rename(old_path, new_path)
        return {"成功": True}

