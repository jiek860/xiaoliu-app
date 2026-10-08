# 自动备份模块
import os, shutil, json
from datetime import datetime
from core.logger import get_logger

class Backup:
    # 备份时跳过的目录，三类：
    #   1. 能从别处重新拿到 —— datasets(训练资料，实测 35MB)、cache、__pycache__
    #   2. 本身就是备份 —— backup_*(自动备份)、plugin_backups、config_backup…
    #      不跳的话会"备份套备份"，越滚越大
    #   3. 体积大又不影响恢复 —— recordings、uploads、browser_sessions、logs
    # 实测：data 目录 37.9MB，其中只有 2.2MB 是真正需要备份的状态。
    EXCLUDE_DIRS = {
        "datasets", "cache", "__pycache__", ".pytest_cache", ".ruff_cache",
        "recordings", "uploads", "browser_sessions",
        "backups", "plugin_backups", "pathfix_backup", "config_backup",
        "archive", "staging", "_deprecated", "logs",
    }

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.backup_dir = os.path.join(self.base, r"backups")
        os.makedirs(self.backup_dir, exist_ok=True)

    def _skip_dir(self, name):
        return name in self.EXCLUDE_DIRS or name.startswith("backup_")

    def _ignore(self, dirpath, names):
        """给 shutil.copytree 用：只过滤目录，文件全保留"""
        return [n for n in names
                if os.path.isdir(os.path.join(dirpath, n)) and self._skip_dir(n)]

    def _last_backup_path(self):
        """找最近一次备份"""
        try:
            dirs = [d for d in os.listdir(self.backup_dir) if d.startswith("backup_")]
            if not dirs:
                return None
            dirs.sort(reverse=True)
            return os.path.join(self.backup_dir, dirs[0])
        except Exception:
            return None

    def backup_now(self):
        """P1-6: 增量备份，只备份比上次新的文件"""
        name = "backup_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.backup_dir, name)
        data_src = os.path.join(self.base, r"data")
        if not os.path.exists(data_src):
            return {"成功": False, "错误": "data目录不存在"}
        last_backup = self._last_backup_path()
        if last_backup:
            # 增量：只复制比上次新的文件
            self._copy_incremental(last_backup, data_src, path)
        else:
            # 第一次：全量（排除 datasets / 旧备份 / 缓存等，见 EXCLUDE_DIRS）
            shutil.copytree(data_src, path, dirs_exist_ok=True, ignore=self._ignore)
        self._cleanup(keep=2)
        return {"成功": True, "备份到": name, "增量": last_backup is not None}

    def _copy_incremental(self, last_path, src, dst):
        """增量复制：只复制比上次备份新的文件（同样跳过 EXCLUDE_DIRS）"""
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if not self._skip_dir(d)]
            rel = os.path.relpath(root, src)
            dst_dir = os.path.join(dst, rel) if rel != "." else dst
            os.makedirs(dst_dir, exist_ok=True)
            for f in files:
                src_file = os.path.join(root, f)
                dst_file = os.path.join(dst_dir, f)
                last_file = os.path.join(last_path, rel, f) if rel != "." else os.path.join(last_path, f)
                # 上次没有这个文件，或者文件比上次新 → 复制
                if not os.path.exists(last_file) or os.path.getmtime(src_file) > os.path.getmtime(last_file):
                    shutil.copy2(src_file, dst_file)

    def backup_async(self, callback=None):
        """P1-6: 异步备份，不阻塞UI"""
        import threading
        def _run():
            r = self.backup_now()
            if callback:
                try:
                    callback(r)
                except Exception:
                    pass
        threading.Thread(target=_run, daemon=True).start()
        return {"已启动": True}

    def _cleanup(self, keep=2):
        """只保留最近keep个备份，删旧的"""
        try:
            dirs = sorted(os.listdir(self.backup_dir))
            dirs = [d for d in dirs if d.startswith("backup_")]
            if len(dirs) <= keep:
                return
            old = dirs[:-keep]
            for d in old:
                shutil.rmtree(os.path.join(self.backup_dir, d), ignore_errors=True)
            get_logger().info("自动清理旧备份%d个，保留最近%d个" % (len(old), keep))
        except Exception as e:
            get_logger().error("清理备份失败: %s" % str(e))

    def auto_backup(self):
        """自动备份（定时调用）"""
        return self.backup_now()

    def list_backups(self):
        """列出所有备份"""
        files = os.listdir(self.backup_dir) if os.path.exists(self.backup_dir) else []
        return {"备份数": len(files), "列表": sorted(files)[-10:]}

    def export(self, dest_dir=None, password=None):
        """P2-10: 备份导出异地（zip + AES256 密码加密，优先 7-Zip）"""
        import zipfile
        dest_dir = dest_dir or self.base
        if not os.path.isdir(dest_dir):
            try:
                os.makedirs(dest_dir)
            except Exception as e:
                return {"成功": False, "错误": "目标目录不可用: " + str(e)[:60]}
        password = password or getattr(self.trunk, "config", {}).get("backup_password", "")
        if not password:
            return {"成功": False, "错误": "未配置备份密码，请在设置里先设置backup_password"}
        name = "导出_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"
        dest = os.path.join(dest_dir, name)
        data_src = os.path.join(self.base, "data")
        if not os.path.exists(data_src):
            return {"成功": False, "错误": "data 目录不存在"}

        def _walk_filtered():
            """遍历 data，跳过 EXCLUDE_DIRS（与内部备份保持一致的取舍）"""
            for root, dirs, files in os.walk(data_src):
                dirs[:] = [d for d in dirs if not self._skip_dir(d)]
                for f in files:
                    yield os.path.join(root, f)

        # ① 优先 7-Zip AES256（正规加密）
        try:
            import subprocess
            _7z = None
            for cand in (r"E:\7-Zip\7z.exe",
                         r"C:\Program Files\7-Zip\7z.exe",
                         r"C:\Program Files (x86)\7-Zip\7z.exe",
                         "7z"):
                if os.path.exists(cand):
                    _7z = cand
                    break
            if _7z:
                # 用 -xr! 排除同样的目录，否则 35MB 训练资料会被一起打进去
                ex_args = []
                for d in sorted(self.EXCLUDE_DIRS):
                    ex_args.append("-xr!" + d)
                ex_args.append("-xr!backup_*")
                r = subprocess.run(
                    [_7z, "a", "-tzip", "-p%s" % password, "-mem=AES256", "-y",
                     dest, os.path.join(data_src, "*")] + ex_args,
                    capture_output=True, timeout=180)
                if os.path.exists(dest):
                    return {"成功": True, "导出到": dest, "加密": "AES256(7-Zip)",
                            "大小KB": os.path.getsize(dest) // 1024, "密码": password,
                            "说明": "已排除 datasets/日志/旧备份等，只导出状态数据"}
                return {"成功": False, "错误": (r.stderr or b"").decode("gbk", "ignore")[:100]}
        except Exception:
            pass
        # ② 退化：zipfile 普通压缩（无密码，但至少异地可拷贝）
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for fp in _walk_filtered():
                    z.write(fp, os.path.relpath(fp, self.base))
            return {"成功": True, "导出到": dest, "加密": "无(未找到7-Zip)",
                    "大小KB": os.path.getsize(dest) // 1024, "密码": "",
                    "说明": "已排除 datasets/日志/旧备份等，只导出状态数据"}
        except Exception as e:
            return {"成功": False, "错误": str(e)[:80]}

    def run(self, *args):
        return self.backup_now()

    def restore(self, backup_name):
        """恢复备份（按备份内容覆盖，不清空 data）

        ⚠️ 这里**不能**先 rmtree 整个 data 再拷回来：
        备份本身就不含 datasets / uploads / recordings / logs 等目录（见 EXCLUDE_DIRS），
        整目录清空会把那些没进备份的东西一并删掉 —— 那是不可逆的数据丢失。
        所以改成"备份里有什么就覆盖什么"，未备份的目录原样保留。
        """
        path = os.path.join(self.backup_dir, backup_name)
        if not os.path.exists(path):
            return {"成功": False, "错误": "备份不存在"}
        data_dst = os.path.join(self.base, "data")
        os.makedirs(data_dst, exist_ok=True)
        try:
            shutil.copytree(path, data_dst, dirs_exist_ok=True)
        except Exception as e:
            return {"成功": False, "错误": "恢复失败: " + str(e)[:80]}
        return {"成功": True, "已恢复": backup_name,
                "说明": "按备份内容覆盖；datasets 等未纳入备份的目录保持原样"}

    def get_backup_size(self):
        """获取备份总大小"""
        total = 0
        if os.path.exists(self.backup_dir):
            for root, _, files in os.walk(self.backup_dir):
                for f in files:
                    total += os.path.getsize(os.path.join(root, f))
        return {"大小MB": round(total / 1024 / 1024, 1)}

    def delete_backup(self, backup_name):
        """删除指定备份"""
        path = os.path.join(self.backup_dir, backup_name)
        if os.path.exists(path):
            shutil.rmtree(path)
            return {"成功": True}
        return {"成功": False, "错误": "备份不存在"}




