# -*- coding: utf-8 -*-
"""命令执行安全策略：白名单、元字符拦截、argv 构造和审计摘要。

设计原则：
* 固定系统动作（关机/重启）只允许 argv 数组；
* 任意字符串命令必须显式走权限中心，并限制首个命令名；
* 优先 shell=False；确需 cmd 解释器时显式使用 build_shell_argv()，
  不再用 Python 的 shell=True；
* 审计只保存命令摘要，不保存可能含密钥的完整命令。
"""
from __future__ import annotations

import hashlib
import os
import shlex

# 常见开发/测试/系统只读命令白名单。真实执行前还要经过权限中心。
ALLOWED_SHELL_COMMANDS = frozenset({
    # Python / 测试 / 代码质量
    "python", "python3", "py", "pytest", "ruff", "mypy", "coverage",
    "tox", "nox", "black", "isort", "flake8", "pylint", "bandit",
    # Node / 前端
    "node", "npm", "npx", "pnpm", "yarn", "bun", "deno", "tsc",
    "uv", "uvx",
    "eslint", "prettier", "jest", "vitest", "playwright",
    # Rust / Go / Java / .NET
    "cargo", "rustc", "gofmt", "go", "java", "javac", "mvn", "gradle",
    "dotnet", "msbuild",
    # 其他常见构建工具
    "make", "cmake", "ninja", "git", "gh", "docker",
    # Windows 只读/查询命令（cmd 内建或系统工具）
    "dir", "type", "where", "tasklist", "whoami", "hostname", "ver",
    "ipconfig", "systeminfo", "tree", "findstr", "more", "fc",
    "ffmpeg", "curl", "ping", "nslookup", "netstat", "wmic", "reg",
    "echo", "set",
})

SHELL_META = ("&&", "||", "|", ";", ">", "<", "&", "`", "$(", "%(",
              "\n", "\r")
APP_FILE_EXTS = (".exe", ".lnk", ".bat", ".cmd")
SHELL_BUILTINS = frozenset({
    "dir", "type", "where", "echo", "set", "ver", "tree",
    "findstr", "more", "fc", "ipconfig", "systeminfo",
    "tasklist", "whoami", "hostname", "netstat", "wmic", "reg",
})
URI_PREFIXES = ("ms-settings:", "ms-store:", "http://", "https://")


def has_shell_meta(text):
    """检测引号外的 shell 元字符。

    例如 `python -c "print(1); print(2)"` 里的分号在引号内，不是命令
    分隔符；而 `calc.exe & whoami` 的 & 在引号外，必须拒绝。
    """
    s = str(text or "")
    quote = ""
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in ("'", '"'):
            if not quote:
                quote = ch
            elif quote == ch:
                quote = ""
            i += 1
            continue
        if not quote:
            for meta in SHELL_META:
                if s.startswith(meta, i):
                    return meta
        i += 1
    return ""


def first_command_token(command):
    """从字符串命令里取首命令名，失败返回空串。"""
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text, posix=False)
    except ValueError:
        return ""
    if not parts:
        return ""
    first = str(parts[0]).strip().strip('"').strip("'")
    base = os.path.basename(first).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base


def check_command(command, allowed=None):
    """检查命令字符串是否满足最基本的安全边界。

    返回 (ok, reason, token)。这只是第一道门；调用方还必须经过
    PermissionCenter 和用户确认。
    """
    text = str(command or "").strip()
    if not text:
        return False, "命令为空", ""
    meta = has_shell_meta(text)
    if meta:
        return False, "不允许串联/重定向（检测到 %r）；一次只跑一条命令" % meta, ""
    token = first_command_token(text)
    if not token:
        return False, "无法解析命令", ""
    allow = set(allowed or ALLOWED_SHELL_COMMANDS)
    if token not in allow:
        return False, "命令 %r 不在白名单内" % token, token
    return True, "", token


def command_hash(command):
    return hashlib.sha256(str(command or "").encode("utf-8", "replace")).hexdigest()[:16]


def command_preview(command, limit=200):
    """审计用的短预览；不额外展开环境变量或参数。"""
    return str(command or "").replace("\r", " ").replace("\n", " ")[:limit]


def build_shell_argv(command):
    """构造不经过 shell=True 的 cmd/sh 调用参数。

    Windows 返回**单个命令行字符串**，由 CreateProcess 直接交给 cmd.exe；
    这样 cmd 的内部引号规则与用户写的命令行一致，避免 list2cmdline
    把内部引号转义成 \" 导致 .cmd / npx 识别失败。

    注意：cmd.exe 仍会解释字符串中的元字符，因此调用前必须先经过
    check_command()、PermissionCenter 和用户确认。本函数只负责去掉
    Python 层的 shell=True。
    """
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return '"%s" /d /s /c "%s"' % (comspec, str(command))
    return ["/bin/sh", "-c", str(command)]


def build_exec_argv(command):
    """尽量用 argv 直接执行；只有 shell 内建命令才回退到 cmd/sh 包装。

    返回 (argv, used_shell_wrapper)。
    """
    import shutil

    text = str(command or "").strip()
    try:
        parts = shlex.split(text, posix=True)
    except ValueError:
        return build_shell_argv(text), True
    if not parts:
        return [], False
    first = parts[0]
    base = os.path.basename(first).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    if base in SHELL_BUILTINS:
        return build_shell_argv(text), True
    resolved = first if os.path.isfile(first) else shutil.which(first)
    if not resolved:
        return build_shell_argv(text), True
    ext = os.path.splitext(str(resolved))[1].lower()
    if ext in (".bat", ".cmd"):
        return build_shell_argv(text), True
    return [str(resolved)] + parts[1:], False


def validate_app_target(target):
    """校验应用启动目标并返回 (ok, resolved_or_reason)。

    允许 URI（ms-settings:/http/https）和真实存在的 exe/lnk/bat/cmd；
    裸命令名必须能通过 shutil.which() 解析，禁止把用户输入直接交给 shell。
    """
    import shutil

    raw = str(target or "").strip()
    if not raw:
        return False, "启动目标为空"
    meta = has_shell_meta(raw)
    if meta:
        return False, "启动目标包含非法字符 %r" % meta
    low = raw.lower()
    if low.startswith(URI_PREFIXES):
        return True, raw
    candidate = raw
    if not os.path.isabs(candidate):
        found = shutil.which(candidate)
        if not found:
            return False, "找不到可执行程序: " + candidate
        candidate = found
    candidate = os.path.abspath(os.path.expanduser(candidate))
    if not os.path.isfile(candidate):
        return False, "程序不存在: " + candidate
    if os.path.splitext(candidate)[1].lower() not in APP_FILE_EXTS:
        return False, "不允许启动该类型文件: " + candidate
    return True, candidate