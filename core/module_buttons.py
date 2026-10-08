# -*- coding: utf-8 -*-
r"""模块按钮：哪些已安装模块要在侧边栏露出一个按钮

数据来源
--------
modules_repo/manifest.json —— 每条可以带：
    "button": {"label": "🖥️ 电脑控制", "action": "gui:computer_dialog"}

action 的两种形式（与 gui/mixins/dialog_mixin.py 的 _module_button_clicked 一致）：
    "gui:<窗口方法名>"  打开本地面板，例如 gui:computer_dialog
    其它              当作模块方法调用，例如 "list" -> trunk.call(name, "list")

为什么不用 modules/installed_meta.json
--------------------------------------
那份文件 29 条记录全部指向已不存在的旧中文文件名，而且全项目没有任何代码读它，
已经移到 core/_deprecated/。现在模块元信息的唯一来源就是 manifest.json。

只返回**文件确实已安装**的模块 —— 没装的模块不该在侧边栏出现。
本模块不依赖 Qt，可单独测试。
"""
import json
import os

MANIFEST_REL = os.path.join("modules_repo", "manifest.json")
INSTALLED_REL = os.path.join("modules", "installed")


def load_buttons(base):
    """返回 [{name, label, action, file, title}]，按 label 排序。

    任何异常都返回 []，绝不能因为按钮数据把界面搞崩。
    """
    if not base:
        return []
    mpath = os.path.join(base, MANIFEST_REL)
    inst = os.path.join(base, INSTALLED_REL)
    try:
        if not os.path.exists(mpath):
            return []
        # utf-8-sig：manifest 可能是被记事本/PS 存过带 BOM 的
        data = json.load(open(mpath, encoding="utf-8-sig"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    out, seen = [], set()
    for m in data:
        if not isinstance(m, dict):
            continue
        btn = m.get("button")
        if not isinstance(btn, dict):
            continue
        label = str(btn.get("label") or "").strip()
        action = str(btn.get("action") or "").strip()
        name = str(m.get("name") or "").strip()
        fname = str(m.get("file") or "").strip()
        if not (label and action and name and fname):
            continue
        if name in seen:
            continue
        if not os.path.exists(os.path.join(inst, fname)):
            continue                      # 没装就不显示
        seen.add(name)
        out.append({"name": name, "label": label, "action": action,
                    "file": fname, "title": str(m.get("title") or name)})
    out.sort(key=lambda x: x["label"])
    return out


def describe(base):
    """给自检用：报告按钮加载情况"""
    bs = load_buttons(base)
    return {"按钮数": len(bs),
            "按钮": ["%s -> %s" % (b["label"], b["action"]) for b in bs]}
