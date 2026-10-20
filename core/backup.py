# 自动备份模块
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, shutil, secrets, hashlib, tempfile
from datetime import datetime
from core.logger import get_logger
from core.path_safety import safe_name, safe_join

_ENC_MAGIC = b"X6BAK2"
_ENC_ITER = 200_000

class Backup:
    # 备份时跳过的目录，三类：
    #   1. 能从别处重新拿到 —— datasets(训练资料，实测 35MB)、cache、__pycache__
    #   2. 本身就是备份 —— backup_*(自动备份)、plugin_backups、config_backup…
    #      不跳的话会"备份套备份"，越滚越大
    #   3. 体积大又不影响恢复 —— recordings、uploads、browser_sessions、logs
    #   4. **browsers** —— Chromium 内核，705.6 MB
    #
    # ⚠️ 上面第 4 条是 2026-10-14 补的，之前漏了它，代价很大：
    #    实测每个备份 **708.3 MB**，其中 705.6 MB 全是 Chromium 的
    #    .pak/.hyb/.dll —— 备份本该系统只占约 2.7 MB，**膨胀了 260 倍**。
    #    backups/ 因此堆到 1.4 GB（两份，隔 12 分钟）。
    #
    #    原始注释写的是"实测 data 目录 37.9MB，其中只有 2.2MB 是真正需要
    #    备份的状态" —— 那句话写的时候 data/browsers 还不存在，
    #    是浏览器功能加进来之后才把它"漏"进备份范围的。
    #
    #    判断标准：**能重新下载/重新生成的东西不进备份**。
    #    用户真正怕丢的是记忆、聊天、配置、人格 —— 那些都不大。
    EXCLUDE_DIRS = {
        "datasets", "cache", "__pycache__", ".pytest_cache", ".ruff_cache",
        "recordings", "uploads", "browser_sessions",
        "backups", "plugin_backups", "pathfix_backup", "config_backup",
        "archive", "staging", "_deprecated", "logs",
        "browsers",          # Chromium 内核 705.6 MB，能重新下载
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
        """做一份完整快照：变了的复制，没变的从上一份硬链接过来"""
        name = "backup_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        # 同一秒内连做两次会撞名（原来会直接往同一目录里写，
        # 于是"上一份"就是自己、增量逻辑整个失效）。撞了就加序号。
        if os.path.exists(os.path.join(self.backup_dir, name)):
            for i in range(2, 1000):
                cand = "%s_%d" % (name, i)
                if not os.path.exists(os.path.join(self.backup_dir, cand)):
                    name = cand
                    break
        path = os.path.join(self.backup_dir, name)
        data_src = os.path.join(self.base, r"data")
        if not os.path.exists(data_src):
            return {"成功": False, "错误": "data目录不存在"}
        last_backup = self._last_backup_path()
        if last_backup:
            self._copy_incremental(last_backup, data_src, path)
        else:
            # 第一次：全量（排除 datasets / 旧备份 / 缓存等，见 EXCLUDE_DIRS）
            shutil.copytree(data_src, path, dirs_exist_ok=True, ignore=self._ignore)
        self._cleanup(keep=2)
        return {"成功": True, "备份到": name, "增量": last_backup is not None}

    def _copy_incremental(self, last_path, src, dst):
        """在新备份里做出**完整快照**：变了的复制，没变的从上一份硬链接过来。

        原来只复制"比上次新"的文件，于是新备份里**只有变化的那些** ——
        它根本不是一份完整快照。配上 _cleanup(keep=2)，第一次那份全量的
        很快会被清掉，此后剩下的每一份都是残缺的：拿它恢复到空目录
        会得到不完整的数据（实测新备份里连 config.json 都没有）。

        改成补全：没变的文件从上一份 os.link 过来。
        硬链接不额外占空间，而且旧备份被删掉也不影响新备份（inode 还活着）。
        文件系统不支持硬链接时退回普通复制。
        """
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if not self._skip_dir(d)]
            rel = os.path.relpath(root, src)
            dst_dir = os.path.join(dst, rel) if rel != "." else dst
            os.makedirs(dst_dir, exist_ok=True)
            for f in files:
                src_file = os.path.join(root, f)
                dst_file = os.path.join(dst_dir, f)
                last_file = (os.path.join(last_path, rel, f) if rel != "."
                             else os.path.join(last_path, f))
                # 上次没有这个文件，或者文件比上次新 → 复制一份新的
                if (not os.path.exists(last_file)
                        or os.path.getmtime(src_file) > os.path.getmtime(last_file)):
                    shutil.copy2(src_file, dst_file)
                else:
                    # 没变 → 从上一份链接过来，保证这一份也是完整快照
                    if not self._link_or_copy(last_file, dst_file):
                        shutil.copy2(src_file, dst_file)

    @staticmethod
    def _link_or_copy(src, dst):
        """先试硬链接（省空间），不行就普通复制"""
        try:
            if os.path.exists(dst):
                os.remove(dst)
            os.link(src, dst)
            return True
        except Exception:
            try:
                shutil.copy2(src, dst)
                return True
            except Exception:
                return False

    def backup_async(self, callback=None):
        """P1-6: 异步备份，不阻塞UI"""
        import threading
        def _run():
            r = self.backup_now()
            if callback:
                try:
                    callback(r)
                except Exception as e:
                    _x6_swallowed(__name__, e)
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

    @staticmethod
    def _encrypt_bytes(data, password):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        key = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode("utf-8"), salt, _ENC_ITER, dklen=32)
        ct = AESGCM(key).encrypt(nonce, data, _ENC_MAGIC)
        return _ENC_MAGIC + salt + nonce + ct

    @staticmethod
    def _decrypt_bytes(data, password):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if not data.startswith(_ENC_MAGIC):
            raise ValueError("不是小6加密备份格式")
        off = len(_ENC_MAGIC)
        salt = data[off:off + 16]
        off += 16
        nonce = data[off:off + 12]
        ct = data[off + 12:]
        key = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode("utf-8"), salt, _ENC_ITER, dklen=32)
        return AESGCM(key).decrypt(nonce, ct, _ENC_MAGIC)

    def decrypt_export(self, source, out_zip, password):
        """把 Python AES-GCM 备份解回普通 zip（供恢复/检查用）。"""
        try:
            data = open(source, "rb").read()
            plain = self._decrypt_bytes(data, password)
            with open(out_zip, "wb") as f:
                f.write(plain)
            return {"成功": True, "导出到": out_zip}
        except Exception as e:
            return {"成功": False, "错误": "解密备份失败: " + str(e)[:80]}

    def export(self, dest_dir=None, password=None):
        """备份导出异地：优先 7-Zip AES256，否则用 Python AES-GCM 加密。"""
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
                            "大小KB": os.path.getsize(dest) // 1024,
                            "说明": "已排除 datasets/日志/旧备份等，只导出状态数据"}
                return {"成功": False, "错误": (r.stderr or b"").decode("gbk", "ignore")[:100]}
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        # 没有 7-Zip：先构建临时 zip，再整体 AES-GCM 加密。
        # 绝不退化成明文 zip。
        tmp_zip = dest + ".plain.tmp"
        try:
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
                for fp in _walk_filtered():
                    z.write(fp, os.path.relpath(fp, self.base))
            raw = open(tmp_zip, "rb").read()
            enc = self._encrypt_bytes(raw, password)
            with open(dest, "wb") as f:
                f.write(enc)
            return {"成功": True, "导出到": dest,
                    "加密": "AES-GCM + PBKDF2(Python)",
                    "格式": "小6加密备份（x6bak）",
                    "大小KB": os.path.getsize(dest) // 1024,
                    "说明": "已排除 datasets/日志/旧备份；恢复时用 "
                            "Backup.decrypt_export() 解回 zip"}
        except Exception as e:
            try:
                if os.path.exists(dest):
                    os.remove(dest)
            except OSError:
                pass
            return {"成功": False, "错误": "加密备份失败: " + str(e)[:80]}
        finally:
            try:
                if os.path.exists(tmp_zip):
                    os.remove(tmp_zip)
            except OSError:
                pass

    def run(self, *args):
        return self.backup_now()

    def restore(self, backup_name):
        """恢复备份（按备份内容覆盖，不清空 data）

        ⚠️ 这里**不能**先 rmtree 整个 data 再拷回来：
        备份本身就不含 datasets / uploads / recordings / logs 等目录（见 EXCLUDE_DIRS），
        整目录清空会把那些没进备份的东西一并删掉 —— 那是不可逆的数据丢失。
        所以改成"备份里有什么就覆盖什么"，未备份的目录原样保留。
        """
        name = safe_name(backup_name, default="")
        path = safe_join(self.backup_dir, name)
        if not name or not path or not os.path.isdir(path):
            return {"成功": False, "错误": "备份不存在或名称非法"}
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
        name = safe_name(backup_name, default="")
        path = safe_join(self.backup_dir, name)
        if name and path and os.path.isdir(path):
            shutil.rmtree(path)
            return {"成功": True}
        return {"成功": False, "错误": "备份不存在或名称非法"}




