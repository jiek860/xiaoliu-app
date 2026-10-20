# -*- coding: utf-8 -*-
"""类型化电脑动作与验证条件的统一 schema。

设计目标：
* 模型只能产出这里允许的动作；
* 每个动作都能被审计、限权、验证和尽可能回滚；
* 目标元素必须是结构化描述（element_id / name / rect / selector），
  不再只靠模型手写坐标。
"""
from __future__ import annotations

import time
import uuid

ACTION_TYPES = {
    # UI / 输入
    "click", "type", "hotkey", "press_key", "scroll", "drag", "wait",
    "wait_for",
    # 应用 / 窗口
    "open_app", "open_url", "activate_window", "close_window", "list_windows",
    "screenshot",
    # 文件
    "read_file", "write_file", "edit_file", "delete_file", "copy_file",
    "move_file",
    # 系统 / 剪贴板
    "shell", "clipboard_get", "clipboard_set",
    # 浏览器（优先走 DOM，而不是像素点击）
    "browser_open", "browser_click", "browser_type", "browser_text",
    "browser_screenshot", "browser_wait",
}
RISK_LEVELS = {"low", "medium", "high"}
HIGH_RISK_TYPES = {
    "shell", "write_file", "edit_file", "delete_file", "copy_file",
    "move_file",
}
READONLY_TYPES = {
    "read_file", "list_windows", "screenshot", "clipboard_get",
    "browser_text", "browser_screenshot",
}
VERIFY_TYPES = {
    "none", "window_title", "control_visible", "text_changed",
    "element_value", "file_exists", "file_changed", "file_contains",
    "exit_code", "url_contains", "screenshot_diff", "wait_for",
}


class ActionError(ValueError):
    pass


def _rect(value):
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return [int(value[0]), int(value[1]), int(value[2]), int(value[3])]
    except (TypeError, ValueError):
        return None


def make_action(action_type, *, target=None, args=None, verify=None,
                risk=None, reason="", rollback=None):
    rid = "act_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    return {
        "action_id": rid,
        "type": action_type,
        "target": target or {},
        "args": args or {},
        "verify": verify or {"type": "none"},
        "risk": risk or ("high" if action_type in HIGH_RISK_TYPES else "medium"),
        "reason": reason,
        "rollback": rollback or {"type": "none"},
        "created_at": time.time(),
    }


def validate_action(action):
    if not isinstance(action, dict):
        raise ActionError("动作必须是 dict")
    atype = str(action.get("type") or "")
    if atype not in ACTION_TYPES:
        raise ActionError("不支持的电脑动作: %r" % atype)
    target = action.get("target") or {}
    args = action.get("args") or {}
    if not isinstance(target, dict) or not isinstance(args, dict):
        raise ActionError("target/args 必须是 dict")
    risk = str(action.get("risk") or
               ("high" if atype in HIGH_RISK_TYPES else "medium"))
    if risk not in RISK_LEVELS:
        raise ActionError("risk 必须是 low/medium/high")
    # 风险等级不能由模型自行降级：动作类型本身就是安全边界。
    if atype in HIGH_RISK_TYPES:
        risk = "high"
    elif atype in READONLY_TYPES and risk != "high":
        risk = "low"
    verify = action.get("verify") or {"type": "none"}
    if not isinstance(verify, dict):
        raise ActionError("verify 必须是 dict")
    vtype = str(verify.get("type") or "none")
    if vtype not in VERIFY_TYPES:
        raise ActionError("不支持的验证类型: " + vtype)

    # 每种动作的最小参数校验。目标既可以是 UIA 名称，也可以是
    # element_id / rect / selector；后续由 Resolver 统一解析。
    if atype == "click":
        if not (target.get("name") or target.get("uia_id")
                or target.get("element_id") or _rect(target.get("rect"))
                or target.get("selector")
                or ("x" in args and "y" in args)):
            raise ActionError("click 需要 target.name/element_id/rect/selector 或 args.x/args.y")
    elif atype == "type":
        if "text" not in args:
            raise ActionError("type 需要 args.text")
    elif atype == "hotkey":
        if not args.get("keys"):
            raise ActionError("hotkey 需要 args.keys")
    elif atype in ("open_app", "activate_window", "close_window"):
        if not args.get("name") and not target.get("name"):
            raise ActionError("%s 需要 name" % atype)
    elif atype == "open_url":
        if not (args.get("url") or target.get("url")):
            raise ActionError("open_url 需要 url")
    elif atype in ("read_file", "write_file", "edit_file", "delete_file",
                   "copy_file", "move_file"):
        if not (args.get("path") or target.get("path")):
            raise ActionError("%s 需要 path" % atype)
        if atype in ("copy_file", "move_file") and not (
                args.get("dst") or args.get("destination") or target.get("dst")):
            raise ActionError("%s 需要 dst" % atype)
    elif atype == "edit_file":
        if "old" not in args or "new" not in args:
            raise ActionError("edit_file 需要 old/new")
    elif atype == "shell":
        if not args.get("cmd"):
            raise ActionError("shell 需要 args.cmd")
    elif atype == "wait":
        try:
            if float(args.get("seconds", 0)) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ActionError("wait 需要正数 seconds") from None
    elif atype == "wait_for":
        condition = args.get("condition") or verify
        if not isinstance(condition, dict):
            raise ActionError("wait_for 需要 condition 或 verify")
        if not condition.get("type") or condition.get("type") == "none":
            raise ActionError("wait_for 需要有效条件")
    elif atype == "browser_open":
        if not (args.get("url") or target.get("url")):
            raise ActionError("browser_open 需要 url")
    elif atype in ("browser_click", "browser_type", "browser_wait"):
        if not (args.get("selector") or target.get("selector")):
            raise ActionError("%s 需要 selector" % atype)
        if atype == "browser_type" and "text" not in args:
            raise ActionError("browser_type 需要 text")
    elif atype == "browser_text":
        # selector 可选：为空表示整页文本
        pass
    elif atype == "clipboard_set":
        if "text" not in args:
            raise ActionError("clipboard_set 需要 text")

    out = dict(action)
    out["type"] = atype
    out["target"] = target
    out["args"] = args
    out["verify"] = verify
    out["risk"] = risk
    out.setdefault("action_id", "act_" + uuid.uuid4().hex[:10])
    out.setdefault("reason", "")
    out.setdefault("rollback", {"type": "none"})
    return out


def effective_risk(action):
    """返回经过动作类型校正后的风险等级。"""
    return validate_action(action)["risk"]


def requires_confirmation(action):
    action = validate_action(action)
    return action["risk"] == "high" or action["type"] in HIGH_RISK_TYPES


def is_readonly(action):
    action = validate_action(action)
    return action["type"] in READONLY_TYPES and action["risk"] == "low"


def action_summary(action):
    action = validate_action(action)
    t = action["type"]
    target = action.get("target") or {}
    args = action.get("args") or {}
    label = (target.get("name") or target.get("path")
             or target.get("selector") or target.get("element_id") or "")
    if t == "click":
        return "点击 %s" % (label or ("(%s,%s)" % (args.get("x"), args.get("y"))))
    if t == "type":
        return "输入文本到 %s" % (label or "当前焦点")
    if t == "open_app":
        return "打开应用 %s" % (args.get("name") or label)
    if t == "open_url":
        return "打开网址 %s" % (args.get("url") or label)
    if t == "activate_window":
        return "激活窗口 %s" % (args.get("name") or label)
    if t == "close_window":
        return "关闭窗口 %s" % (args.get("name") or label)
    if t == "shell":
        return "执行命令：%s" % args.get("cmd", "")
    if t in ("read_file", "write_file", "edit_file", "delete_file"):
        return "%s：%s" % ({
            "read_file": "读取文件", "write_file": "写入文件",
            "edit_file": "修改文件", "delete_file": "删除文件"}[t],
            args.get("path") or label)
    if t in ("copy_file", "move_file"):
        return "%s：%s -> %s" % (
            "复制" if t == "copy_file" else "移动",
            args.get("path") or label, args.get("dst") or "")
    if t.startswith("browser_"):
        return "%s：%s" % (t, args.get("selector") or args.get("url") or "")
    if t == "wait_for":
        return "等待条件：%s" % (
            (args.get("condition") or action.get("verify") or {}).get("type", ""))
    return t
