# -*- coding: utf-8 -*-
"""电脑控制：自然语言指令解析。"""
from __future__ import annotations

import os
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerCommandParserMixin:
    _SITE_ALIAS = {
        "百度": "baidu.com", "谷歌": "google.com", "必应": "bing.com",
        "淘宝": "taobao.com", "京东": "jd.com", "知乎": "zhihu.com",
        "微博": "weibo.com", "哔哩哔哩": "bilibili.com", "b站": "bilibili.com",
        "贴吧": "tieba.baidu.com", "豆瓣": "douban.com", "网易": "163.com",
        "腾讯": "qq.com", "github": "github.com", "csdn": "csdn.net",
    }

    @staticmethod
    def _looks_path(s):
        """判断一段文字是不是"路径/文件名"而不是"要复制的文本"

        用在"复制 X 到 Y"的歧义上：
            「复制 D:\\a.txt 到 D:\\b.txt」 -> 路径 -> copy_file
            「复制 你好 到 剪贴板」        -> 不是路径 -> clipboard_set
        判据：含路径分隔符，或看起来有扩展名（.txt / .py / .png …）。
        """
        s = str(s or "").strip().strip("\"'")
        if not s:
            return False
        if re.search(r"[\\/]", s):
            return True
        return bool(re.search(r"\.[A-Za-z0-9]{1,6}$", s))

    def parse(self, text):
        """把用户的话解析成 (action, kwargs)；不匹配返回 None"""
        if not text:
            return None
        t = text.strip()
        tl = t.lower()
        # ============ UI 元素树指令（先于坐标类，因为"按名字点"比"点坐标"精确）============
        # 「点击名为确定的按钮」/「点击确定按钮」——按控件名点，不依赖坐标
        m = re.search(r"(?:点击|点一下|单击|按下)\s*(?:名为|名叫|叫做)?\s*[「\"']?"
                      r"([^」\"'，。]{1,24}?)[」\"']?\s*的?\s*"
                      r"(按钮|链接|菜单|选项|标签|输入框|控件)", t)
        if m:
            nm = m.group(1).strip()
            ct = {"按钮": "ButtonControl", "链接": "HyperlinkControl",
                  "菜单": "MenuItemControl", "选项": "ListItemControl",
                  "标签": "TabItemControl", "输入框": "EditControl",
                  "控件": ""}.get(m.group(2), "")
            return ("ui_click", {"name": nm, "control_type": ct or None})
        # 「看看记事本的控件」/「列出窗口结构」
        m = re.search(r"(?:看看|查看|列出|dump|显示)\s*[「\"']?([^」\"'，。]{1,24})[」\"']?\s*的?\s*"
                      r"(?:控件|界面结构|元素树|结构)", t)
        if m:
            return ("ui_dump", {"window": m.group(1).strip(), "depth": 3})
        if re.search(r"(界面结构|元素树|控件树|窗口结构)", t):
            return ("ui_dump", {"depth": 2})
        # 找控件 / 列出窗口（元素树版）
        m = re.search(r"(?:列出?|看看|查看)\s*(?:当前)?\s*(?:所有)?\s*窗口", t)
        if m:
            return ("ui_windows", {})
        # 「在搜索框里输入 你好」——按控件名输入
        m = re.search(r"(?:在|往)\s*[「\"']?([^」\"'，。]{1,24}?)[」\"']?\s*(?:框|控件)?\s*"
                      r"(?:里|中)?\s*(?:输入|填|打)\s*(.+)$", t)
        if m:
            return ("ui_type", {"name": m.group(1).strip(), "text": m.group(2).strip()})
        # 执行命令：「执行 git status」/「运行命令 dir」
        m = re.search(r"(?:执行命令|运行命令|跑命令|cmd|shell)\s*[：:]?\s*(.+)$", t, re.I)
        if m:
            return ("shell", {"cmd": m.group(1).strip()})
        # 打开网址/网站
        m = re.search(r"(?:打开|访问|去|上)\s*(?:网址|网站|网页)\s*[：: ]?\s*([\w\.\-:/]{4,80})", t)
        if m:
            return ("open_url", {"url": m.group(1).strip()})
        m = re.search(r"https?://[^\s，。]+", t)
        if m:
            return ("open_url", {"url": m.group(0).strip()})
        # 「打开 某网站」——原来只认带 http:// 的、"打开网站 X"这两种说法，
        # 于是「打开百度」「打开 github.com」都掉进下面的 open_app 分支，
        # 去找一个叫"百度"的程序（必然找不到）。这里补两条：
        #   域名形态（x.y.zz）直接按网址开；常见站点中文名走别名表。
        m = re.search(r"(?:打开|访问|去|上)\s*((?:[\w\-]+\.)+[A-Za-z]{2,6}(?:/[^\s，。]*)?)", t)
        if m:
            return ("open_url", {"url": m.group(1).strip()})
        m = re.search(r"(?:打开|访问|去|上)\s*(百度|谷歌|必应|淘宝|京东|知乎|微博|"
                      r"哔哩哔哩|b站|贴吧|豆瓣|网易|腾讯|github|csdn)", t, re.I)
        if m:
            k = m.group(1)
            return ("open_url", {"url": self._SITE_ALIAS.get(k)
                                 or self._SITE_ALIAS.get(k.lower()) or k})
        # 打开/查看 文件路径（先于应用，避免 "打开 E:\x" 被当成应用名）
        m = re.search(r"(?:打开|看看|浏览|查看|列出).{0,8}([A-Za-z]:\\[^\s，。]*)", t)
        if m:
            p = m.group(1).strip()
            if re.search(r"里有什么|有什么|有哪些|里面|列出|浏览|查看", t):
                return ("list_dir", {"path": p})
            return ("open_path", {"path": p}) if os.path.exists(self._safe_path(p) or p) else ("list_dir", {"path": p})
        m = re.search(r"(?:列出|看看|浏览|查看).{0,4}(?:目录|文件夹)", t)
        if m:
            return ("list_dir", {"path": None})
        # 打开应用
        m = re.search(r"(?:打开|启动|运行|开一下|帮我开)\s*([\w\u4e00-\u9fff\-\. ]{1,30})", t)
        if m and not re.search(r"网址|网站|文件|文件夹|目录|url", m.group(1)) \
                and ":" not in m.group(1) and "\\" not in m.group(1):
            return ("open_app", {"app": m.group(1).strip()})
        # 窗口
        m = re.search(r"(?:关闭|最小化|激活|切到|切换)\s*(?:窗口)?\s*[:：]?\s*([\w\u4e00-\u9fff\-\. ]{1,30})", t)
        if m and re.search(r"关闭|最小化|激活|切换|切到", t):
            wname = m.group(1).strip()
            if "关闭" in t:
                return ("close_window", {"title": wname})
            if "最小化" in t:
                return ("minimize_window", {"title": wname})
            return ("activate_window", {"title": wname})
        if re.search(r"列出?.*(窗口|运行中)|正在运行", t):
            return ("list_windows", {})
        # 截屏
        if re.search(r"截屏|截图|屏幕快照", t):
            return ("screenshot", {})
        # 鼠标（右键/双击先于普通点击判断）
        if re.search(r"右键\s*(?:点击|单击)?", t):
            m = re.search(r"[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
            return ("mouse_click", {"x": int(m.group(1)), "y": int(m.group(2)), "button": "right"}) if m else ("mouse_click", {"button": "right"})
        if re.search(r"双击", t):
            m = re.search(r"[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
            return ("mouse_click", {"x": int(m.group(1)), "y": int(m.group(2)), "clicks": 2}) if m else ("mouse_click", {"clicks": 2})
        m = re.search(r"鼠标\s*(?:移动)?\s*到?\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_move", {"x": int(m.group(1)), "y": int(m.group(2))})
        m = re.search(r"移动到?\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_move", {"x": int(m.group(1)), "y": int(m.group(2))})
        m = re.search(r"(?:拖动|拖拽)\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?\s*(?:到|->|至)\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_drag", {"x1": int(m.group(1)), "y1": int(m.group(2)), "x2": int(m.group(3)), "y2": int(m.group(4))})
        m = re.search(r"(?:单击|点击|点一下)\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_click", {"x": int(m.group(1)), "y": int(m.group(2))})
        if re.search(r"滚动", t):
            m = re.search(r"滚动\s*([\-\d]+)?", t)
            n = int(m.group(1)) if m and m.group(1) else 3
            return ("mouse_scroll", {"clicks": n})
        if re.search(r"鼠标.*(?:位置|坐标)|鼠标在哪", t):
            return ("mouse_pos", {})
        # 键盘
        m = re.search(r"(?:输入|打字|打出)\s*[：:]?\s*(.+)$", t)
        if m:
            return ("type_text", {"text": m.group(1).strip()})
        m = re.search(r"(?:按下|按)\s*([a-zA-Z]+(?:\+[a-zA-Z0-9]+)+)", t)
        if m:
            return ("hotkey", {"keys": m.group(1).strip()})
        m = re.search(r"快捷键?\s*[：:]?\s*([\w\-\+ ]{2,20})", t)
        if m:
            return ("hotkey", {"keys": m.group(1).strip()})
        m = re.search(r"按(?:一下)?\s*(enter|回车|esc|delete|空格|tab|方向键上|方向键下|方向键左|方向键右|up|down|left|right)\b", t)
        if m:
            key = {"enter": "enter", "回车": "enter", "esc": "esc", "delete": "delete",
                   "空格": "space", "tab": "tab", "方向键上": "up", "方向键下": "down",
                   "方向键左": "left", "方向键右": "right"}[m.group(1)]
            return ("press_key", {"key": key})
        # ============ 文件操作（必须排在剪贴板之前）============
        #
        # 原来顺序是反的：clipboard_set 的规则 `(?:复制|拷贝)\s*(.+?)\s*(?:到剪贴板)?$`
        # 贪婪匹配任何含"复制"的话，而且排在 copy_file 前面，于是
        #     「复制 a.txt 到 b.txt」-> clipboard_set({'text': 'a.txt 到 b.txt'})
        # 即：想复制文件，结果只改了剪贴板，还回一句"已复制到剪贴板: a.txt 到 b.txt"，
        # 看起来像成功了。copy_file 因此永远不可达（死规则）。
        # 另外这几条原本都要求 [A-Za-z]:\\ 盘符，相对路径/裸文件名一律不认。
        #
        # 现在：文件和剪贴板用 _looks_path 区分 —— 两端都像路径才是文件操作，
        # 目标是"剪贴板"或不像路径就还是剪贴板。
        m = re.search(r"(?:复制|拷贝)\s*[：:]?\s*(.+?)\s*(?:到|至)\s*(.+?)\s*$", t)
        if m:
            src, dst = m.group(1).strip(), m.group(2).strip()
            if dst in ("剪贴板", "粘贴板", "clipboard"):
                return ("clipboard_set", {"text": src})
            if self._looks_path(src) and self._looks_path(dst):
                return ("copy_file", {"src": src, "dst": dst})
        m = re.search(r"(?:移动|剪切)\s*[：:]?\s*(.+?)\s*(?:到|至)\s*(.+?)\s*$", t)
        if m:
            src, dst = m.group(1).strip(), m.group(2).strip()
            if self._looks_path(src) and self._looks_path(dst):
                return ("move_file", {"src": src, "dst": dst})
        m = re.search(r"(?:创建|新建)\s*(?:一个)?\s*文件\s*[：:]?\s*([^\s，。]+)"
                      r"\s*(?:内容[：:]?\s*(.+))?$", t)
        if m:
            return ("create_file", {"path": m.group(1).strip(),
                                    "content": (m.group(2) or "").strip()})
        m = re.search(r"(?:删除|删掉)\s*(?:文件|文档)?\s*[：:]?\s*([^\s，。]+)", t)
        if m and self._looks_path(m.group(1)):
            return ("delete_file", {"path": m.group(1).strip()})
        # 剪贴板（放在文件操作之后，只兜"把这段文字复制起来"这类）
        if re.search(r"剪贴板.*(?:有什么|内容|是什么)", t):
            return ("clipboard_get", {})
        m = re.search(r"(?:复制|拷贝|复制一下)\s*[：:]?\s*(.+?)\s*(?:到剪贴板)?\s*$", t)
        if m:
            return ("clipboard_set", {"text": m.group(1).strip()})
        # 系统信息
        if re.search(r"系统信息|电脑状态|系统状态|cpu|内存|磁盘|电池|硬件", t):
            return ("system_info", {})
        # 取消关机/重启（必须在“关机/重启”之前判断，否则“取消关机”会被误判成关机）
        if re.search(r"取消.*(关机|重启)", t):
            return ("cancel_shutdown", {})
        # 关机重启
        if re.search(r"关机", t):
            m = re.search(r"关机\s*(?:delay|延迟)?\s*(\d+)?", t)
            return ("shutdown", {"delay": int(m.group(1)) if m and m.group(1) else 30})
        if re.search(r"重启", t):
            m = re.search(r"重启\s*(\d+)?", t)
            return ("restart", {"delay": int(m.group(1)) if m and m.group(1) else 30})
        # 文件操作已上移到剪贴板之前（原来放这儿会被"复制…"的剪贴板规则截胡，
        # 且只认 [A-Za-z]:\ 绝对路径）。见本方法开头的 _looks_path 那段。
        return None
