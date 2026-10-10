# -*- coding: utf-8 -*-
r"""打包一个「干净版」给小6智能体给朋友用

为什么需要它
------------
直接把整个项目文件夹压缩发出去，会把下面这些**你自己的东西**一起送出去：
    data\config.json     你的 GLM API Key、QQ 邮箱授权码、企业微信 Webhook
    data\chats.db        你和它的全部聊天记录
    data\memory.json     它的长期记忆（包含关于你的事）
    data\users\          各账号的聊天与记忆目录
    data\logs\           运行日志（含你的使用轨迹）
    data\.secret_key     本地加密密钥
    data\backup_*\       上面这些的副本
这些只占 0.8 MB，但格不起。

同时 data\ 里还有**必须带上**的内容，缺了它就"变傻"：
    data\*_bible.md      20 份人格设定（core 的 personality.py 明确按文件名读取）
    data\persona_full.md 人格全文
    data\knowledge_docs\ 知识库
    data\skills\ rules\  技能与规则
    data\datasets\       训练资料（35MB，朋友用不到，默认不带）

用法
----
    py -3 tools\make_share_zip.py                # 默认：不带语音，约 55 MB
    py -3 tools\make_share_zip.py --with-voice   # 带语音识别，约 1 GB
    py -3 tools\make_share_zip.py --out D:\x.zip # 指定输出

安全兜底
--------
打包完成后会**扫描 zip 内容**，发现疑似密钥/私钥/隐私文件就直接删除产物并报错，
不会留下一个"以为干净其实不安全"的包。
"""
import argparse
import os
import re
import sys
import time
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------- 要带的目录（整个）----------
# 注意不含 tools/：那是发版/签名/打包用的开发者工具，朋友用不上，
# 而且本脚本就在里面，没必要连打包器一起发出去。
INCLUDE_DIRS = [
    "core", "gui", "modules", "modules_repo", "libs",
    "docs", "scripts", "plugins",
]
# ---------- 要带的目录（可选，体积大）----------
OPTIONAL_DIRS = ["optional_libs"]

# ---------- 要带的根文件 ----------
INCLUDE_FILES = [
    "run.py", "run_server.py",
    "install.bat", "check.bat", "启动PyQt.bat", "启动PyQt.vbs", "卸载.bat", "打开控制台.bat",
    "config.default.json", "requirements.txt", "requirements-optional.txt",
    "pyproject.toml", "app.ico",
    "README.md", "ARCHITECTURE.md", "FAQ.txt",
    "使用说明.txt", "安装教程.txt", "模型教程.txt", "激活教程.txt",
    "用户协议.txt", "隐私政策.txt",
]

# ---------- 开发者专属，不进朋友版 ----------
EXCLUDE_RELPATHS = {
    "检测手册.txt",                      # 你自己的检测手册
    "开发者须知-密钥与发版.md",            # 含密钥库位置等内部信息
    "CONTRIBUTING.md", "CHANGELOG.md",
    "docs/开发流程与目录结构梳理.md",       # 内部梳理（含体积/已知问题）
    "docs/全模块规则体系.md", "docs/规则对比与优化清单.md", "docs/升级报告_20260923.md",
}

# ---------- data\ 里只带"内容"，不带"隐私" ----------
DATA_INCLUDE_DIRS = ["knowledge_docs", "skills", "rules"]
DATA_INCLUDE_GLOBS = [".md", ".html"]      # *_bible.md / persona_full.md / 图谱可视化.html

# ---------- 永远排除 ----------
EXCLUDE_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".git", "backups", "updates", "staging", "dist", "build",
}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".log", ".tmp", ".bak", ".bak_ui")

# ---------- 安全扫描：这些一旦出现在包里就报错 ----------
# 注意：这里只放"模式"，绝不写任何真实凭据明文 —— 否则这个脚本本身就成了泄漏源。
SECRET_PATTERNS = [
    ("GLM/智谱 API Key", re.compile(rb"\b[0-9a-f]{32}\.[A-Za-z0-9]{10,}\b")),
    # 只认 sk- 后面紧跟 20 位以上纯字母数字，避免误伤 setuptools 里的
    # SPDX 许可证标识（如 sk-linking-protocols-exception，中间有连字符）
    ("OpenAI 风格 Key", re.compile(rb"sk-[A-Za-z0-9]{20,}")),
    ("企业微信 Webhook", re.compile(rb"qyapi\.weixin\.qq\.com[^\s\"']{0,120}"),
     ),
    ("私钥块", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Gitee 带令牌 URL", re.compile(rb"https://[^/\s:@]+:[0-9a-f]{32}@gitee\.com")),
    # 带密码的连接串：要求密码位至少 10 位真字符。
    # 这样 urllib3 文档里的占位符（://username:password@、://<user>:<pwd>@）不会误报。
    ("带密码的连接串", re.compile(rb"://[A-Za-z0-9._\-]{2,32}:[A-Za-z0-9._\-]{10,64}@")),
]
SECRET_FILENAMES = ("config.json", ".secret_key", "密钥.key", "私钥.pem",
                    "小6智能体-全部密钥汇总.txt", "密钥汇总-归档.txt")


def should_skip(name):
    if name in EXCLUDE_NAMES:
        return True
    if name.endswith(EXCLUDE_SUFFIX):
        return True
    if name.startswith("backup_"):        # data\backup_MMDD_HHMM
        return True
    if name.startswith("截图_") or name.startswith("聊天记录_"):
        return True
    return False


def collect(with_voice):
    """返回 [(绝对路径, zip 内相对路径), ...]"""
    items = []

    def keep(rel):
        return rel.replace("\\", "/") not in EXCLUDE_RELPATHS

    for d in INCLUDE_DIRS + (OPTIONAL_DIRS if with_voice else []):
        root = os.path.join(BASE, d)
        if not os.path.isdir(root):
            print("  [跳过] 目录不存在: %s" % d)
            continue
        for r, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if not should_skip(x)]
            for f in files:
                if should_skip(f):
                    continue
                p = os.path.join(r, f)
                rel = os.path.relpath(p, BASE)
                if keep(rel):
                    items.append((p, rel))
    for f in INCLUDE_FILES:
        p = os.path.join(BASE, f)
        if os.path.isfile(p) and keep(f):
            items.append((p, f))
    # data\ 的内容部分
    ddir = os.path.join(BASE, "data")
    if os.path.isdir(ddir):
        for sd in DATA_INCLUDE_DIRS:
            root = os.path.join(ddir, sd)
            if not os.path.isdir(root):
                continue
            for r, dirs, files in os.walk(root):
                dirs[:] = [x for x in dirs if not should_skip(x)]
                for f in files:
                    if should_skip(f):
                        continue
                    p = os.path.join(root and r, f)
                    rel = os.path.relpath(p, BASE)
                    if keep(rel):
                        items.append((p, rel))
        for f in sorted(os.listdir(ddir)):
            p = os.path.join(ddir, f)
            if os.path.isfile(p) and os.path.splitext(f)[1] in DATA_INCLUDE_GLOBS:
                rel = os.path.join("data", f)
                if keep(rel):
                    items.append((p, rel))
    return items


FRIEND_README = """小6智能体 · 朋友版
================================================================

一、先装 Python（只需一次）
    去 https://www.python.org/downloads/ 下载 3.10 以上版本，
    安装时务必勾选 "Add Python to PATH"。

    如果双击 install.bat 提示"没找到Python"，多半是 Windows 应用商店
    那个占位程序在捣乱，去「设置 → 应用 → 高级应用设置 → 应用执行别名」
    里把 python.exe 关掉即可。

二、装依赖
    双击 install.bat，等它跑完（走的是清华镜像，比较快）。

三、启动
    双击 启动PyQt.bat（有控制台窗口，出问题能看报错）
    或   启动PyQt.vbs（静默无窗口）

四、第一次会要求激活
    跟我要一个激活码，在登录窗口点「激活」输入。
    激活码很长（500 多字符），直接 Ctrl+V 粘进去就行，
    输入框下面会提示"识别为 RSA 长码"，看到这行再点激活。

五、然后会弹出「首次设置向导」，跟着走一遍
    它会自动检查你的模型能不能用，并告诉你该装什么：
      · 想免费：点里面的 Ollama 下载链接，装完在命令行执行
              ollama run qwen2.5:3b
        然后回向导点「重新检测」。
      · 想效果更好：选「用云端 API」，填你自己的 API 地址和 Key。
    配好后向导会显示"可以正常聊天了"。
    以后想再打开：设置 → 系统 → 首次设置向导。

六、出问题了怎么办
    程序里「设置 → 记录 → 日志 → 导出日志包」，把生成的 zip 发我。
    （导出时会自动抹掉密钥字段，可以放心发）

七、这个版本含什么
    {VOICE_NOTE}

日志在 data\\logs\\ 下，配置在 data\\config.json。
你的聊天记录、记忆都只存在你自己电脑上，不会上传到任何地方。
"""


def main():
    ap = argparse.ArgumentParser(description="打包干净版给小6智能体")
    ap.add_argument("--with-voice", action="store_true",
                    help="带上 optional_libs（语音识别/看图），包会大很多")
    ap.add_argument("--out", default=None, help="输出 zip 路径")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d")
    out = args.out or os.path.join(os.path.dirname(BASE),
                                   "小6智能体-朋友版-%s%s.zip"
                                   % (stamp, "-含语音" if args.with_voice else ""))
    out = os.path.abspath(out)
    if os.path.dirname(out) == BASE:
        print("[X] 输出不能放在项目目录里（会被下次打包带进去）")
        return 1

    print("=" * 62)
    print("打包小6智能体 · 朋友版")
    print("=" * 62)
    print("  含语音/看图: %s" % ("是" if args.with_voice else "否（约 55 MB，推荐）"))
    print("  输出到     : %s" % out)
    print()

    if not args.yes:
        try:
            if input("  继续？(Y/n) ").strip().lower() not in ("", "y", "yes"):
                print("  已取消")
                return 0
        except EOFError:
            pass

    items = collect(args.with_voice)
    total = sum(os.path.getsize(p) for p, _ in items if os.path.exists(p))
    print("  待打包: %d 个文件, %.1f MB" % (len(items), total / 1024 / 1024))
    print()

    note = ("含语音识别与看图功能（体积大）" if args.with_voice
            else "不含语音识别/看图（想要可以让程序里「功能扩展组件」按需安装）")
    tmp_readme = os.path.join(os.path.dirname(out), "_friend_readme_tmp.txt")
    with open(tmp_readme, "w", encoding="utf-8") as f:
        f.write(FRIEND_README.replace("{VOICE_NOTE}", note))

    print("  正在写入 zip ...")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p, rel in items:
            if os.path.exists(p):
                z.write(p, rel)
        z.write(tmp_readme, "使用说明-朋友版.txt")
    os.remove(tmp_readme)

    size = os.path.getsize(out)
    print("  完成: %.1f MB" % (size / 1024 / 1024))

    # ---------- 安全扫描 ----------
    print()
    print("=" * 62)
    print("安全检查：扫描包内是否混入密钥/隐私")
    print("=" * 62)
    problems = []
    with zipfile.ZipFile(out) as z:
        for info in z.infolist():
            base = os.path.basename(info.filename)
            if base in SECRET_FILENAMES:
                problems.append("含敏感文件: " + info.filename)
                continue
            if info.file_size > 3 * 1024 * 1024:
                continue
            data = z.read(info)
            for label, rx in SECRET_PATTERNS:
                m = rx.search(data)
                if m:
                    problems.append("含疑似%s: %s -> %s"
                                    % (label, info.filename, m.group(0)[:40].decode("utf-8", "replace")))

    if problems:
        print("  [X] 发现 %d 处问题，已删除产物：" % len(problems))
        for p in problems[:20]:
            print("      " + p)
        try:
            os.remove(out)
        except Exception:
            pass
        return 1

    print("  [OK] 未发现任何密钥、私钥或隐私文件")
    print()
    print("=" * 62)
    print("可以发给朋友了")
    print("=" * 62)
    print("  %s" % out)
    print("  包里附了一份「使用说明-朋友版.txt」，直接让他看那个。")
    print()
    print("  提醒：包里不含你的 data\\config.json，所以朋友首次启动")
    print("        需要自己配模型（本地 Ollama 或他自己的 API Key）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
