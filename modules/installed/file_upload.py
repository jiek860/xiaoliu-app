# -*- coding: utf-8 -*-
"""文件上传 v2.1 - 上传 + 读取 + 列表 + 搜索 + 删除 + 统计 + 清空 + 导出"""
import os, time
from core.safe import safe
from modules.base import BaseModule


class FileUpload(BaseModule):
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
            return {"错误": "文件不存在"}

        import shutil
        fname = os.path.basename(file_path)
        dst = os.path.join(self.upload_dir, fname)
        shutil.copy2(file_path, dst)

        # 读取文本内容
        content = ""
        if fname.endswith((".txt", ".py", ".md", ".json", ".csv")):
            try:
                content = open(dst, encoding="utf-8", errors="ignore").read()[:1000]
            except: pass

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
        """删除文件"""
        path = os.path.join(self.upload_dir, fname)
        if os.path.exists(path):
            os.remove(path)
            return {"ok": True}
        return {"错误": "文件不存在"}

    @safe
    def read_file(self, fname):
        """读取文件内容"""
        path = os.path.join(self.upload_dir, fname)
        if not os.path.exists(path):
            return {"错误": "文件不存在"}
        try:
            content = open(path, encoding="utf-8", errors="ignore").read()
            return {"文件名": fname, "内容": content[:1000]}
        except Exception as e:
            return {"错误": str(e)[:80]}

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
            return {"错误": "文件不存在"}
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
        """重命名文件"""
        old_path = os.path.join(self.upload_dir, old_name)
        new_path = os.path.join(self.upload_dir, new_name)
        if not os.path.exists(old_path):
            return {"错误": "文件不存在"}
        os.rename(old_path, new_path)
        return {"成功": True}

