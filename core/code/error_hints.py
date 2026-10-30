# -*- coding: utf-8 -*-
"""报错提示：把常见异常翻译成「下一步做什么」。

为什么不做成 AI 调用
--------------------
运行失败时用户最需要的是**立刻**看到可执行动作（装包、改编码、给权限），
而不是再等一次模型回复。规则覆盖率有限，但高频问题（缺包/缩进/
NoneType/权限/端口占用）足够用了。
"""
from __future__ import annotations

from core.code import run_parse

_HINTS = {
    "ModuleNotFoundError": "缺依赖：到「设置 → 扩展 → 功能扩展组件」安装对应"
                           "组件；命令行安装走 core.error_text.install_cmd()"
                           "（已带国内源）",
    "ImportError": "导入失败：确认模块已安装，且没有被同名文件/目录遮蔽",
    "IndentationError": "缩进错误：同一代码块用 4 个空格，别混用 Tab",
    "TabError": "Tab 和空格混用：编辑器里执行「Tab 转 4 空格」后重跑",
    "SyntaxError": "语法错误：看提示行的前一行，常见是括号/引号没闭合",
    "NameError": "名字未定义：检查拼写，或在使用前先赋值/导入",
    "UnboundLocalError": "局部变量先用后赋值：把赋值挪到使用之前",
    "TypeError": "类型不匹配：打印一下参数的实际类型，常见是 None 参与运算",
    "AttributeError": "对象没有这个属性：确认对象不是 None，或方法名拼错",
    "ValueError": "值不合法：检查空字符串/格式转换（int/float）的输入",
    "KeyError": "字典没有这个键：用 dict.get(key, 默认值) 或先判断",
    "IndexError": "下标越界：先判断列表长度，或改用切片",
    "ZeroDivisionError": "除数为 0：运算前先判断分母",
    "FileNotFoundError": "文件不存在：确认路径是相对项目根，或先把文件放到位",
    "PermissionError": "权限不足：换有写权限的目录，或右键以管理员运行",
    "UnicodeDecodeError": "编码不对：用 encoding='utf-8'（或 gbk）显式指定",
    "JSONDecodeError": "JSON 格式不合法：检查引号/逗号，或先打印原始文本",
    "ConnectionError": "网络连不上：检查网络/代理，或换一个 API 地址",
    "TimeoutError": "超时：调大超时时间，或先确认服务端是否可用",
    "OSError": "系统调用失败：看后面的具体原因（路径/权限/磁盘）",
    "RecursionError": "递归太深：检查递归出口，或改成循环",
    "MemoryError": "内存不足：分批处理数据，别一次性读入大文件",
}

_PATTERN_HINTS = (
    ("No module named '", "缺依赖：设置 → 扩展 → 功能扩展组件里安装后重启"),
    ("address already in use", "端口被占用：关掉占用的程序，或换端口"),
    ("SSL", "证书问题：更新系统证书，或临时设置 HTTPS_PROXY"),
    ("Permission denied", "权限不足：换目录或提升权限"),
    ("can't open file", "脚本路径不对：确认文件在当前项目里"),
)

MAX_HINT_LEN = 160


def hint_for(text):
    """根据输出给出最多一条可执行提示；没有匹配返回空串。"""
    exc = run_parse.last_exception(text)
    typ = str(exc.get("type") or "")
    # 具体模式优先于泛化类型（OSError 的"端口占用/权限"比"系统调用失败"有用）
    lowered = str(text or "").lower()
    for needle, text_hint in _PATTERN_HINTS:
        if needle.lower() in lowered:
            return text_hint[:MAX_HINT_LEN]
    hint = _HINTS.get(typ, "")
    return hint[:MAX_HINT_LEN]


def lines_for(text):
    """输出 -> 可直接贴进结果框的提示行（无提示时为空列表）。"""
    hint = hint_for(text)
    return ["💡 " + hint] if hint else []
