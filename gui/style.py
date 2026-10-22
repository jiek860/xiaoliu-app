# -*- coding: utf-8 -*-
"""全局样式表"""

STYLE = """
QMainWindow { background: #ffffff; }
QWidget { color: #1f1f1f; font-family: 'Microsoft YaHei UI'; font-size: 13px; }
QPushButton {
    background: #ffffff; border: 1px solid #e5e6eb;
    border-radius: 6px; padding: 4px 12px; color: #1f1f1f;
    font-size: 13px; text-align: left;
    /* 为什么不是 padding:10px
       --------------------------
       全局 QPushButton 原来是 padding:10px（上下各 10px）。
       紧凑工具条上的按钮高度只有 24~27px（如工作台的
       ▶开始 / ⏸暂停 / 🛑取消 / ⛶弹出），
       24 - 20 = 4px 分给文字 —— 中文被压成一条横线，
       就是"文字显示不全"的现象。
       改成 6px 12px：留 12px 给文字（13px 字体够用），
       同时最小高度仍能满足 10px 内边距的视觉留白。
       需要更大留白的按钮自己 setMinimumHeight(34) 即可。 */
    min-height: 24px;
}
QPushButton:hover { background: #f2f3f5; border: 1px solid #4a9eff; color: #4a9eff; }
QTextBrowser, QListWidget, QComboBox {
    background: #ffffff; border: 1px solid #e5e6eb;
    border-radius: 8px; color: #1f1f1f;
}
QLineEdit {
    background: #ffffff; border: 1px solid #e5e6eb;
    border-radius: 6px; color: #1f1f1f; padding: 8px;
}
QDialog, QScrollArea { background: #ffffff; }
QLabel { color: #1f1f1f; font-size: 13px; }
QCheckBox {
    color: #1f1f1f;
    /* 与按钮保持一致的点击高度，否则中文标签只有 19px，
       在紧凑布局里同样会被压扁（工作台"把当前打开的文件交给 AI"复选框）。 */
    min-height: 22px;
    padding: 2px 4px;
}
"""