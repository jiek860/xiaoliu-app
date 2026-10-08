# -*- coding: utf-8 -*-
"""boot_ok启动检测 - 启动成功写标记，失败自动回滚"""
import os
import json
import time


def check_boot_ok(base):
    """检查boot_ok标记，返回是否需要回滚"""
    boot_path = os.path.join(base, "data", "boot_ok.json")
    if not os.path.exists(boot_path):
        # 上次启动没写boot_ok，说明启动崩溃了
        backup_dir = os.path.join(base, "updates", "backup")
        if os.path.exists(backup_dir) and os.listdir(backup_dir):
            return True  # 需要回滚
    return False


def write_boot_ok(base, version=""):
    """启动成功写标记"""
    boot_path = os.path.join(base, "data", "boot_ok.json")
    os.makedirs(os.path.dirname(boot_path), exist_ok=True)
    tmp = boot_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "time": time.time(),
            "version": version,
        }, f, ensure_ascii=False)
    os.replace(tmp, boot_path)


def clear_boot_ok(base):
    """更新前清除标记"""
    boot_path = os.path.join(base, "data", "boot_ok.json")
    if os.path.exists(boot_path):
        os.remove(boot_path)
