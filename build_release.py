# -*- coding: utf-8 -*-
"""发版打包脚本 v1.0
用法: python build_release.py [版本号]
功能:
1. 算所有py文件的SHA256
2. 生成manifest.json
3. 列出需要上传的文件
"""
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.release_sign import file_sha256 as sha256_file


def scan_py_files(base):
    """扫描所有需要打包的py文件"""
    files = []
    skip_dirs = {"__pycache__", "backups", "updates", ".git", "data", "dist", "build"}
    for root, dirs, filenames in os.walk(base):
        # 跳过不需要的目录
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in filenames:
            if fn.endswith(".py"):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, base)
                # 跳过test文件
                if "test" in fn.lower():
                    continue
                files.append(rel)
    return sorted(files)


def build_manifest(base, version, changelog=""):
    """生成manifest.json"""
    files = scan_py_files(base)
    manifest_files = []
    for rel in files:
        full = os.path.join(base, rel)
        sha = sha256_file(full)
        size = os.path.getsize(full)
        # 下载地址（Gitee raw格式）
        url = f"https://gitee.com/cloud-drift/liuyun/raw/main/{rel.replace(os.sep, '/')}"
        manifest_files.append({
            "path": rel.replace(os.sep, "/"),
            "sha256": sha,
            "size": size,
            "url": url,
        })

    manifest = {
        "version": version,
        "release_date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        "min_version": "24.0.0",
        "changelog": changelog,
        "gray_ratio": 1.0,
        "files": manifest_files,
        "signature": "",  # 占位，由 sign_release.py 用密钥库私钥填入
    }
    return manifest


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) < 2:
        print("用法: python build_release.py [版本号] [更新说明]")
        print("示例: python build_release.py 24.2.0 '修复若干BUG'")
        sys.exit(1)

    version = sys.argv[1]
    changelog = sys.argv[2] if len(sys.argv) > 2 else ""

    print(f"开始打包 v{version}...")
    manifest = build_manifest(base, version, changelog)

    # 保存manifest.json
    out_path = os.path.join(base, "manifest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"✅ manifest.json 已生成: {out_path}")
    print(f"📦 共 {len(manifest['files'])} 个文件")
    print(f"🔢 版本: v{version}")
    print()
    print("下一步:")
    print("1. 检查manifest.json内容")
    print("2. 运行 python sign_release.py 给 manifest 签名（用户端会验签，未签名不予更新）")
    print("3. 把签名后的 manifest.json + 所有py文件上传到Gitee仓库")
    print("4. 用户端会自动检测更新")


if __name__ == "__main__":
    main()
