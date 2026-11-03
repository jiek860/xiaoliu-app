# -*- coding: utf-8 -*-
"""联网搜索进上下文的"清洗 / 渲染 / 说明"（2026-11-01 修「牛头不对马嘴」）

为什么单独一个文件
------------------
`context_builder` 已经 660 行（策略上限 600，见 tools/check_file_sizes.py），
而这一块是**纯函数**（不碰 trunk、不碰线程），单独放更好测也更好读。

原来三个直接病因都在这块：
    ① `deep_search.search()` 返回的是 **dict**（结果/总结/数量/查询/来源），
       代码却 `str(web)[:4000]` 原样塞进提示词 —— 空结果（`'数量': 0`）
       也算"非空"，模型看到一坨 Python 字典字面量，只能反问
       「您希望我提供什么样的信息？」。
    ② 8 秒超时静默返回 `""` —— 模型**不知道"这次没搜到"**，
       于是许空诺（「请稍等片刻，我会尽快为您查询并回复」）。
    ③ 用户整句口语「可以帮我查看最近的烧烤店吗」直接丢给搜索引擎，
       抓回来全是无关页面。
"""
import re

from core.untrusted_content import wrap_search_result

# 口语前缀：削掉它们才像人话搜出来的词
Q_PREFIX = ("请问", "麻烦", "能不能", "可不可以", "可以", "能否", "帮我", "帮忙",
            "给我", "我想", "我要", "你帮我", "查一下", "查下", "查询", "查",
            "搜一下", "搜下", "搜索", "搜", "查看", "看看", "找一下", "找找", "请")
Q_SUFFIX = ("可以吗", "行吗", "好吗", "谢谢", "谢了", "可以", "吗", "呢", "吧",
            "啊", "呀", "一下")
# 「身边的位置」—— 本机没有定位/地图数据，模型不该假装能查到附近
LOCAL_WORDS = ("附近", "周围", "周边", "身旁", "旁边", "最近的", "离我")

MAX_QUERY = 60
MAX_ROWS = 5
ROW_TITLE = 80
ROW_SNIPPET = 80
ROW_LINK = 120
MAX_SUMMARY = 300


def clean_query(user_input) -> str:
    """把整句口语削成搜索引擎能用的关键词（削空了就返回原文）。"""
    q = re.sub(r"\s+", " ", str(user_input or "")).strip()
    prefixes = sorted(Q_PREFIX, key=len, reverse=True)
    # 「请问搜一下…」要一层层剥：剥完一层得**从头**再看，
    # 否则短前缀"搜"先命中，会把"搜一下"拆成"一下"
    changed = True
    while changed:
        changed = False
        for word in prefixes:
            if q.startswith(word):
                q = q[len(word):].lstrip("，,、 ")
                changed = True
                break
    suffixes = sorted(Q_SUFFIX, key=len, reverse=True)
    changed = True
    while changed:
        changed = False
        for word in suffixes:
            if q.endswith(word):
                q = q[:-len(word)].rstrip("，,、 。")
                changed = True
                break
    q = q.strip("，,。.！!？?、；;《》「」\"'")
    return q[:MAX_QUERY] or str(user_input or "").strip()[:MAX_QUERY]


def pick_rows(web):
    """从 deep_search 的返回里挑出真有用的条目，返回 ``(rows, summary)``。

    没有标题的条目一律丢掉（链接类结果经常只有 URL，模型看了也白看）。
    """
    if not isinstance(web, dict):
        return [], ""
    rows = []
    summary = str(web.get("总结") or "").strip()[:MAX_SUMMARY]
    for item in web.get("结果") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("标题") or "").strip()
        if not title:
            continue
        rows.append({
            "标题": title[:ROW_TITLE],
            "来源": str(item.get("来源") or "")[:12],
            "摘要": str(item.get("摘要") or item.get("内容") or "").strip()[:ROW_SNIPPET],
            "链接": str(item.get("链接") or "").strip()[:ROW_LINK],
        })
    return rows[:MAX_ROWS], summary


def render_rows(query, rows, summary=""):
    """把条目渲成给模型看的线索块（外网内容一律过 wrap_search_result）。"""
    body = ["[联网-网页线索] 查询「%s」，抓到 %d 条（网页标题，未经核实）："
            % (query, len(rows))]
    for i, row in enumerate(rows, 1):
        line = "%d. %s（%s）" % (i, row["标题"], row["来源"] or "网页")
        if row["摘要"]:
            line += " —— " + row["摘要"]
        if row["链接"]:
            line += " " + row["链接"]
        body.append(line)
    if summary:
        body.append("模型总结（同样是外部资料，不可信）：" + summary)
    return "\n" + wrap_search_result("\n".join(body), source="web_search")


def empty_note(query, reason) -> str:
    """给模型的"这次没搜到"上下文 —— 比空字符串好：它就不会许空诺了。"""
    return ("\n[联网-没搜到] 查询「%s」%s，这次没有可用资料。"
            "别编店名/地址/电话/价格，直接说没查到，再给用户一个自己能做的一步"
            "（例：打开美团/饿了么/地图，搜「%s」）。" % (query, reason, query))


def local_hint(user_input) -> str:
    """问"附近xxx"时提醒模型：没有定位，先问一句在哪，别猜。"""
    if any(w in str(user_input or "") for w in LOCAL_WORDS):
        return ("注意：用户问的是**身边的位置**，而我没有定位/地图数据 —— "
                "先说清只能给网页线索，并问他一句在哪个城市或区。")
    return ""
