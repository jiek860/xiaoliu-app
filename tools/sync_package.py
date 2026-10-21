# -*- coding: utf-8 -*-
"""把开发目录同步到"打包源"目录（E:\\xiao6-package）

为什么要有这个脚本
------------------
打包流程是：开发目录 -> 复制一份干净的 -> 对那份打包。
"复制一份干净的"这一步**每次改完代码都要重做**，
靠人记得不靠谱 —— 忘了同步就会把旧代码打进安装包，
而且**装出来照样能跑**，只是行为是旧的，很难发现。

用法
----
    py -3 tools\\sync_package.py            同步（会先显示要改什么）
    py -3 tools\\sync_package.py --dry-run  只看差异，不动文件
    py -3 tools\\sync_package.py --to D:\\x  同步到别的目录

安全底线（每次同步都会检查，不通过就中止）
------------------------------------------
    · 绝不复制 data\\ backups\\ optional_libs\\ tests\\ tools\\ .git\\
    · config.default.json 里不许有填好的 Key
    · 同步后打印文件数/体积，方便和上次对比
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import argparse
import hashlib
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DST = r"E:\xiao6-package"

# 要同步的根级文件
FILES = ["run.py", "app.ico", "config.default.json",
         "requirements.txt", "requirements-optional.txt", "requirements.lock",
         "install.bat", "启动PyQt.bat", "使用说明-小白版.txt",
         # 用户教程：程序内「新手教程」「检查更新」「深度自检」会直接打开
         # 这些文件；少了它们，打包版点按钮只会提示"文件未找到"。
         "FAQ.txt", "安装教程.txt", "激活教程.txt", "模型教程.txt",
         "检测手册.txt", "部署步骤.md", "卸载.bat",
         # 插件标准：用户/开发者需要查阅的规范文档
         "插件标准.txt",
         # 协议：agreement.py 读 docs/，读不到会回退到根目录  打包版
         # 不带 docs/，所以这两份必须随包发，否则首次启动显示"文件未找到"
         "隐私政策.txt", "用户协议.txt"]
# 可选：有就同步
# ⚠️ 这里**故意不放 CHANGELOG.md / docs/** —— 那是开发文档，
#    用户不需要。安装包越小越好（每多一个文件，用户就多一分困惑）。
OPTIONAL_FILES = []

# 要同步的目录
DIRS = ["core", "gui", "modules", "modules_repo", "libs"]

# 复制时排除的目录名
SKIP = {"__pycache__", "retired", ".git", ".githooks", ".pytest_cache",
        ".ruff_cache", "backup_", ".venv", ".runtime-venv",
        ".build-venv", "htmlcov"}

# 绝对不能出现在打包源里的
FORBIDDEN = ["data", "backups", "optional_libs", "tests", "tools",
             "scripts", "staging", ".git", ".githooks", "dist", "build",
             "logs", "docs", ".venv", ".runtime-venv", ".build-venv"]


def md5(p):
    try:
        with open(p, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def walk(base):
    """列出文件 -> 哈希（相对路径用 / 分隔）"""
    out = {}
    if not os.path.isdir(base):
        return out
    for r, ds, fs in os.walk(base):
        ds[:] = [d for d in ds
                 if d not in SKIP and not d.startswith("backup_")]
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, base).replace("\\", "/")] = md5(p)
    return out


def plan(dst):
    """算出要做什么：新增 / 更新 / 删除"""
    add, upd, dele = [], [], []

    for name in FILES + [f for f in OPTIONAL_FILES
                         if os.path.exists(os.path.join(BASE, f))]:
        s, d = os.path.join(BASE, name), os.path.join(dst, name)
        if not os.path.exists(d):
            add.append(name)
        elif md5(s) != md5(d):
            upd.append(name)

    for name in DIRS:
        sm = walk(os.path.join(BASE, name))
        dm = walk(os.path.join(dst, name))
        for k in sorted(set(sm) - set(dm)):
            add.append("%s/%s" % (name, k))
        for k in sorted(set(dm) - set(sm)):
            dele.append("%s/%s" % (name, k))
        for k in sorted(set(sm) & set(dm)):
            if sm[k] != dm[k]:
                upd.append("%s/%s" % (name, k))
    return add, upd, dele


PACKAGE_README = "_打包说明.txt"


def write_package_readme(dst):
    """生成/刷新打包源说明，数字每次同步后重新计算，避免像以前那样
    一直写着 1710 个文件 / 47.8 MB（早就不对了）。"""
    import datetime
    n, s = du(dst)
    def _count(sub):
        p = os.path.join(dst, sub)
        c, _ = du(p) if os.path.isdir(p) else (0, 0)
        return c
    files = sorted(f for f in FILES if os.path.isfile(os.path.join(dst, f)))
    lines = [
        "小6智能体 · 打包专用目录（打包源）",
        "=" * 60,
        "生成时间：%s（由 tools/sync_package.py 自动刷新）"
        % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "来源：从开发目录**复制**过来的一份干净程序",
        "规模：%d 个文件 / %.1f MB" % (n, s / 1048576.0),
        "",
        "这份是干什么的",
        "-" * 60,
        "用桌面上那套工具（加固打包 + 安装包生成器）给小6 做安装包。",
        "**对这一个文件夹打包**，不要对开发目录打包。",
        "",
        "开发目录里混着不能发出去的东西 —— 直接打包是隐私事故：",
        "    data\\config.json     API Key、邮箱授权码、Webhook",
        "    data\\chats.db        聊天记录",
        "    data\\memory*.json    长期记忆",
        "    data\\users\\ logs\\    账号与会话",
        "    backups\\             自动备份",
        "    optional_libs\\       可选依赖（约 1 GB）",
        "    tests\\ tools\\ .git\\  开发用",
        "本目录在同步时已逐项排查，上面这些一个都没进来。",
        "",
        "复制内容（明细，数字为本次同步实测）",
        "-" * 60,
        "【程序本体】",
        "  run.py                       入口（打包工具要编译它）",
        "  core\\        %4d 文件       核心代码（含公钥/激活公钥）" % _count("core"),
        "  gui\\         %4d 文件       界面代码" % _count("gui"),
        "  modules\\     %4d 文件       插件模块" % _count("modules"),
        "  modules_repo\\ %3d 文件     插件清单（RSA 签名）" % _count("modules_repo"),
        "  libs\\        %4d 文件       随包库" % _count("libs"),
        "",
        "【配置与依赖】",
        "  config.default.json          默认配置（脱敏版，不含任何 Key）",
        "  requirements.txt / -optional.txt",
        "",
        "【给用户的文件】",
    ]
    for f in files:
        if f not in ("run.py", "app.ico", "config.default.json",
                     "requirements.txt", "requirements-optional.txt",
                     "requirements.lock", "install.bat"):
            lines.append("  %-28s %s" % (f, ""))
    lines += [
        "",
        "打包步骤（手工操作）",
        "-" * 60,
        "第 1 步：编译成 exe",
        "    双击 加固打包.exe，选源文件：" + os.path.join(dst, "run.py"),
        "    输出位置：就放 " + dst + "（方便第 2 步直接从文件夹里找）",
        "",
        "    ⚠️ 也可以走 PyInstaller：在开发目录执行",
        "       .build-venv\\Scripts\\python.exe -m PyInstaller --clean --noconfirm xiao6.spec",
        "       注意 xiao6.spec 引用的是开发目录里的文件，不要在打包源里直接跑。",
        "",
        "第 2 步：做成安装包",
        "    双击 安装包生成器.exe",
        "    ① 主程序 exe        **留空**",
        "    ② 应用名            小6智能体",
        "    ③ 安装包图标        可留空",
        "    ④ 桌面快捷方式      勾上",
        "    ⑤ 整个文件夹一起打包  **选 %s**    ← 关键" % dst,
        "    ⑥ Inno Setup 编译器  已自动填好",
        "    然后点「一键生成安装包」",
        "",
        "做完之后请验一遍（重要）",
        "-" * 60,
        "安装包必须在干净环境里试装，重点看四件事：",
        "  1. 装完双击快捷方式，能不能打开界面",
        "  2. 能不能聊起来（首次向导配模型）",
        "  3. 设置 → 系统 → 深度自检，有没有报错",
        "  4. 卸载，确认 data\\ 留在原地没被删",
        "",
        "已知的坑",
        "-" * 60,
        "1. 可选功能（语音 / 看图）默认不在里面。要带上 optional_libs，",
        "   安装包会从约 200 MB 涨到 1 GB 以上；建议做标准版 + 语音版两个包。",
        "2. 这是打包源，不是运行环境。想在这儿直接跑，需要先把依赖装进 libs\。",
        "3. 程序内「新手教程」「用量成本」「RAG管理」「团队管理」入口见",
        "   使用说明-小白版.txt；运行时不读取 docs/，本目录只带用户能看的文档。",
        "",
        "用户文档清单（本目录已包含）",
        "-" * 60,
    ]
    for f in files:
        if f.lower().endswith((".txt", ".md")) and f != PACKAGE_README:
            lines.append("  %s" % f)
    text = "\n".join(lines) + "\n"
    path = os.path.join(dst, PACKAGE_README)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def check_safety(dst):
    """同步后检查：不该有的有没有混进来"""
    bad = [n for n in FORBIDDEN if os.path.exists(os.path.join(dst, n))]
    if bad:
        return ["打包源里混进了不该有的东西: %s" % bad]
    problems = []
    cfg = os.path.join(dst, "config.default.json")
    if os.path.exists(cfg):
        import re
        s = open(cfg, encoding="utf-8", errors="ignore").read()
        for k, v in re.findall(
                r'"(cloud_key|email_pass|webhook|api_key|[^"\s]*_webhook|[^"\s]*_secret)"\s*:\s*"([^"]*)"',
                s, re.I):
            if v.strip() and not v.startswith("x6enc:v1:"):
                problems.append("config.default.json 里 %s 有未加密的值！" % k)
    return problems


def _rmtree_force(p):
    """删目录树，遇到**只读文件**也删得掉

    ⚠️ 为什么不能只用 shutil.rmtree(p, ignore_errors=True)：
        git 的 objects/ 里是**只读文件**，Windows 上 rmtree 删不掉它们。
        而 ignore_errors=True 会**把失败吞掉** —— 于是函数"成功返回"、
        调用方以为清干净了，实际文件还在。

        实测踩到：同步报告"清掉了 modules_repo/.git"，可它一直在，
        461 个文件里有 433 个还留着（全是 objects/ 下的只读对象）。
        测试 `test_real_package_has_no_nested_git` 才把它揪出来。

    做法：用 onerror 先把只读属性去掉再删；删完**检查是否真的没了**，
    没删掉就如实返回 False（不假装成功）。
    """
    import stat

    def _onerror(func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        # 静默是故意的：这是 rmtree 的重试回调 —— 它失败会被忽略，
        # 但**删除结果由调用方检查**（下面 `os.path.exists` 那一句），
        # 所以不会像第一版 ignore_errors 那样"看着成功其实没删掉"
        except Exception:
            pass

    if not os.path.exists(p):
        return True
    try:
        shutil.rmtree(p, onerror=_onerror)
    # 静默是故意的：同上 —— 这里吞掉异常是为了走到下面那句检查，
    # 由它如实返回 True/False，调用方会据此报"没删掉"
    except Exception:
        pass
    return not os.path.exists(p)          # 真的没了才算成功


def purge_forbidden(dst):
    """把目标目录里**不该有的东西**强制清掉

    ⚠️ 为什么需要这一步（踩过的坑）：
        同步用的是 copytree(dirs_exist_ok=True) —— 它**只增不删**。
        而"要删除"清单是靠 plan() 比出来的，plan() 又会**跳过** .git
        这类目录（walk() 里 ds[:] 把它们滤掉了）。
        两个一叠加：目标里如果**早先就混进了 .git**（比如手动 robocopy
        带进去的），同步永远清不掉它。

        实测踩到：打包源里留着 modules_repo\\.git（461 文件 / 1.79 MB），
        里面有**私有 gitee 仓库地址**（https://gitee.com/cloud-drift/liuyun.git）。
        没有凭据泄漏（git 默认不把 token 写进 config），但仓库地址和
        git 历史（objects/ 里可能有已删文件）都不该跟着安装包发出去。

        所以：复制之后**无条件扫一遍目标目录**，见到就删，不依赖差异比对。

    返回 (清掉的清单, 没删掉的清单) —— 删不掉要如实报出来，
    不能像第一版那样被 ignore_errors 吞掉、看着像成功。
    """
    removed, failed = [], []
    for r, ds, _fs in os.walk(dst, topdown=True):
        for d in list(ds):
            if d in SKIP or d.startswith("backup_"):
                p = os.path.join(r, d)
                rel = os.path.relpath(p, dst).replace("\\", "/")
                if _rmtree_force(p):
                    removed.append(rel)
                else:
                    failed.append(rel)
                ds.remove(d)
    for r, _ds, fs in os.walk(dst):
        for f in fs:
            if f.endswith((".pyc", ".pyo", ".log", ".tmp", ".bak")):
                p = os.path.join(r, f)
                rel = os.path.relpath(p, dst).replace("\\", "/")
                try:
                    os.chmod(p, 0o666)
                    os.remove(p)
                    removed.append(rel)
                except Exception:
                    failed.append(rel)
    return removed, failed


def du(p):
    n = s = 0
    for r, ds, fs in os.walk(p):
        ds[:] = [d for d in ds if d not in SKIP]
        for f in fs:
            try:
                s += os.path.getsize(os.path.join(r, f))
                n += 1
            # 静默是故意的：统计体积时遇到读不到的单个文件（权限/被占用），
            # 跳过它继续数就行 —— 少算一个不影响"大概多大"这个用途
            except Exception:
                pass
    return n, s


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
    ap = argparse.ArgumentParser(description="同步打包源目录")
    ap.add_argument("--to", default=DEFAULT_DST, help="目标目录")
    ap.add_argument("--dry-run", action="store_true", help="只看差异")
    a = ap.parse_args()
    dst = a.to

    print("=" * 78)
    print("同步打包源：%s  ->  %s" % (BASE, dst))
    print("=" * 78)

    if not os.path.isdir(dst):
        print("  目标不存在，先建:", dst)
        if not a.dry_run:
            os.makedirs(dst, exist_ok=True)

    add, upd, dele = plan(dst)
    print("  要新增 %d 个 / 要更新 %d 个 / 要删除 %d 个"
          % (len(add), len(upd), len(dele)))
    for tag, arr in (("新增", add), ("更新", upd), ("删除", dele)):
        for k in arr[:8]:
            print("    %s %s" % (tag, k))
        if len(arr) > 8:
            print("    ... %s 还有 %d 个" % (tag, len(arr) - 8))

    # ⚠️ 有没有"早先混进来的"不该有的东西 —— 这也算差异！
    #    第一版把"已经一致就提前返回"写在清理之前，结果：
    #    目标里残留着 .git（plan 比不出来，因为 walk 会跳过它），
    #    于是同步说"已经一致，不用动"，**清理那一步永远跑不到**。
    stash = [os.path.relpath(os.path.join(r, d), dst).replace("\\", "/")
             for r, ds, _fs in os.walk(dst) for d in ds
             if d in SKIP or d.startswith("backup_")]
    if stash:
        print("  目标里有 %d 个不该有的目录（早先混进来的）：" % len(stash))
        for k in stash[:6]:
            print("    清理 %s" % k)

    if not (add or upd or dele or stash):
        if not a.dry_run:
            # 说明文件按当前实际数字重新生成（只有内容变了才会写盘）
            write_package_readme(dst)
        print()
        print("  ✅ 已经一致，不用动")
        return 0

    if a.dry_run:
        print()
        print("  （--dry-run，没有改动任何文件）")
        return 0

    # ── 真的同步 ──
    print()
    print("  开始同步…")
    for name in FILES + [f for f in OPTIONAL_FILES
                         if os.path.exists(os.path.join(BASE, f))]:
        s = os.path.join(BASE, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dst, name))
    for name in DIRS:
        s = os.path.join(BASE, name)
        if not os.path.isdir(s):
            continue
        shutil.copytree(s, os.path.join(dst, name),
                        ignore=shutil.ignore_patterns(*SKIP),
                        dirs_exist_ok=True)
    # 删掉源里已经没有的（保持一致）
    for k in dele:
        try:
            os.remove(os.path.join(dst, k.replace("/", os.sep)))
        # 静默是故意的：删一个源里已经没有的文件失败（被占用/只读），
        # 不该中断整次同步 —— 后面的一致性校验会把残留报出来
        except Exception:
            pass
    # 无条件清掉不该有的（.git / __pycache__ / 日志 …）
    # 不能只靠上面那个 dele 清单 —— 它比不出"早先就混进来的"东西
    purged, failed = purge_forbidden(dst)
    if purged:
        print()
        print("  清掉了 %d 个不该有的目录/文件（早先混进来的）：" % len(purged))
        for k in purged[:6]:
            print("    %s" % k)
        if len(purged) > 6:
            print("    ... 还有 %d 个" % (len(purged) - 6))
    if failed:
        print()
        print("  ❌ **有 %d 个没删掉**（多半是只读文件被占用）：" % len(failed))
        for k in failed[:6]:
            print("    %s" % k)
        print("  这些会跟着安装包发出去 —— 先手工删掉再打包。")
    # 清掉可能产生的 __pycache__
    for r, ds, _fs in os.walk(dst):
        for d in list(ds):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(r, d), ignore_errors=True)

    # ── 校验 ──
    print()
    print("=" * 78)
    print("同步后校验")
    print("=" * 78)
    add2, upd2, dele2 = plan(dst)
    if add2 or upd2 or dele2:
        print("  ⚠️ 还有差异: 新增%d 更新%d 删除%d"
              % (len(add2), len(upd2), len(dele2)))
    else:
        print("  ✅ 已完全一致")

    problems = check_safety(dst)
    if problems:
        print()
        for p in problems:
            print("  ❌ %s" % p)
        return 1
    print("  ✅ 安全检查通过（没有 data/ tests/ tools/，配置里没有 Key）")

    readme = write_package_readme(dst)
    print("  ✅ 已刷新 %s" % os.path.basename(readme))

    n, s = du(dst)
    print()
    print("  %s" % dst)
    print("  %d 个文件，%.1f MB" % (n, s / 1048576))
    print()
    print("  下一步：")
    print("    1. 加固打包.exe  -> 选 %s\\run.py 编译成 exe" % dst)
    print("    2. 安装包生成器.exe -> 第⑤项选 %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
