# -*- coding: utf-8 -*-
"""状态栏"本地/云端"指示灯的**唯一真理源**。

修复的真实 bug（2026-10-22）：
    1) gui/mixins/dialog_mixin.py 的 switch_model()：
       切到"本地路由"时把 local 和 cloud **都**设成绿色 (#0f0)，
       于是用户看到"本地绿 + 云端也绿"。
    2) gui/settings_dialog.py 的 _safe_set_model_ui()：
       无条件执行 cloud_light.setStyleSheet("color:#0f0;")，
       无论选本地还是云端，云端灯永远是绿的。

新增（c 项）：启动时按 config 回填，不再依赖"用户手动切过一次"。
"""
from __future__ import annotations

COLOR_ON = "#0f0"       # 绿 = 当前生效
COLOR_OFF = "#999"      # 灰 = 未启用
_FONT = "font-size:11px;padding:0 8px;"

MODE_CLOUD = "云端模型"
MODE_LOCAL = "本地路由"


def is_cloud_mode(mode) -> bool:
    """判断是否云端模式。

    只认明确的"云端"，其余（含空值/异常值）一律按本地处理，
    与 llm 模块"本地优先、云端兜底"的默认行为一致。
    """
    return "云端" in str(mode or "")


def _style(on: bool) -> str:
    return "color:%s;%s" % (COLOR_ON if on else COLOR_OFF, _FONT)


def paint(mode, local_light, cloud_light, model_btn=None,
          model_label=None) -> dict:
    """按 mode 统一刷新指示灯 / 按钮 / 顶栏标签。返回刷新后的状态。"""
    cloud = is_cloud_mode(mode)
    text = MODE_CLOUD if cloud else MODE_LOCAL
    for widget, on in ((local_light, not cloud), (cloud_light, cloud)):
        if widget is None:
            continue
        try:
            widget.setStyleSheet(_style(on))
        except Exception:  # 静默是故意的 - 控件已销毁不影响主流程
            pass
    if model_btn is not None:
        try:
            model_btn.setText("🔄 模型:%s" % ("云端" if cloud else "本地路由"))
        except Exception:  # 静默是故意的
            pass
    if model_label is not None:
        try:
            model_label.setText("模型：%s" % text)
        except Exception:  # 静默是故意的
            pass
    return {"mode": text, "cloud": cloud}


def paint_from_config(win):
    """启动时调用：从 trunk.config 读出 model_mode 并回填界面。"""
    mode = MODE_LOCAL
    try:
        mode = win.trunk.config.get("model_mode", MODE_LOCAL)
    except Exception:  # 静默是故意的 - 配置不可用时用默认值
        mode = MODE_LOCAL
    return paint(
        mode,
        getattr(win, "_status_local", None),
        getattr(win, "_status_cloud", None),
        getattr(win, "model_btn", None),
        getattr(win, "model_status_label", None),
    )
