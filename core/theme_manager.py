# -*- coding: utf-8 -*-
"""主题管理 v1.0 - 深色/浅色/护眼三主题"""
import os

THEMES = {
    "light": {
        "name": "浅色",
        "bg": "#ffffff", "fg": "#1f1f1f",
        "panel": "#f5f5f5", "border": "#e5e6eb",
        "accent": "#4a9eff", "accent_fg": "#ffffff",
        "chat_user_bg": "#4a9eff", "chat_user_fg": "#ffffff",
        "chat_ai_bg": "#f0f2f5", "chat_ai_fg": "#1f1f1f",
    },
    "dark": {
        "name": "深色",
        "bg": "#1e1e1e", "fg": "#e0e0e0",
        "panel": "#2d2d2d", "border": "#3d3d3d",
        "accent": "#4a9eff", "accent_fg": "#ffffff",
        "chat_user_bg": "#4a9eff", "chat_user_fg": "#ffffff",
        "chat_ai_bg": "#2d2d2d", "chat_ai_fg": "#e0e0e0",
    },
    "eye": {
        "name": "护眼",
        "bg": "#f0f4e8", "fg": "#333333",
        "panel": "#e8ecdf", "border": "#d0d8c0",
        "accent": "#6b8e23", "accent_fg": "#ffffff",
        "chat_user_bg": "#6b8e23", "chat_user_fg": "#ffffff",
        "chat_ai_bg": "#e8ecdf", "chat_ai_fg": "#333333",
    },
}


def get_theme_names():
    return list(THEMES.keys())


def get_stylesheet(name="light"):
    """生成QSS样式表"""
    t = THEMES.get(name, THEMES["light"])
    return """
    QMainWindow, QDialog {{
        background: {bg};
    }}
    QWidget {{
        color: {fg};
        font-family: 'Microsoft YaHei UI';
        font-size: 13px;
    }}
    QPushButton {{
        background: {panel};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 8px 16px;
        color: {fg};
    }}
    QPushButton:hover {{
        border: 1px solid {accent};
        color: {accent};
    }}
    QPushButton:pressed {{
        background: {accent};
        color: {accent_fg};
    }}
    QTextBrowser, QListWidget, QComboBox, QLineEdit, QSpinBox {{
        background: {bg};
        border: 1px solid {border};
        border-radius: 8px;
        color: {fg};
        padding: 6px;
    }}
    QLineEdit:focus {{
        border: 1px solid {accent};
    }}
    QTabWidget::pane {{
        border: 1px solid {border};
        border-radius: 8px;
    }}
    QTabBar::tab {{
        background: {panel};
        padding: 8px 16px;
        border: 1px solid {border};
        border-bottom: none;
    }}
    QTabBar::tab:selected {{
        background: {bg};
        border-bottom: 2px solid {accent};
    }}
    QScrollBar:vertical {{
        background: {panel};
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: {border};
        border-radius: 5px;
    }}
    QMenuBar {{
        background: {panel};
        border-bottom: 1px solid {border};
    }}
    QMenuBar::item {{
        padding: 6px 12px;
    }}
    QMenuBar::item:selected {{
        background: {accent};
        color: {accent_fg};
    }}
    QStatusBar {{
        background: {panel};
        border-top: 1px solid {border};
    }}
    """.format(**t)


def load_current_theme(base=None):
    """从配置读当前主题"""
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(base, "data", "config.json")
    try:
        import json
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        return cfg.get("theme", "light")
    except Exception:
        return "light"


def save_theme(theme_name, base=None):
    """保存主题到配置"""
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(base, "data", "config.json")
    try:
        import json
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        cfg["theme"] = theme_name
        tmp = cfg_path + ".tmp"
        json.dump(cfg, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(tmp, cfg_path)
        return True
    except Exception:
        return False
