# -*- coding: utf-8 -*-
"""去 AI 腔：回复出站前的确定性清理（零模型、零 IO）。

为什么单独一个模块
------------------
人格卡里的 ``banned`` 词表只在 ``ResponseCritic`` 里替换，而
``聊天.校验器`` 默认是 ``shadow``（只记录、不改文本）。所以
「作为一个AI，…」「希望对你有所帮助」这些句子，**实际回复里从来没被改掉**：
提示词里写了不许说，模型偶尔还是说；校验器又不开。

这里把同一件事放到**最后一道**，和校验器开关无关：
    · ``ReplyPipeline._critique`` 里无条件调用（on/shadow/off 都调用）
    · ``legacy_reply.run`` 兜底链路也调用
宁可模板腔少一点，也不能只写在文档里。

只做"删/换"，不改写内容、不加新事实：
    · 删句首自我介绍：「作为一个AI，」「作为人工智能，」……
    · 删客服式结尾：「希望对你有所帮助」「如果还有问题随时告诉我」……
    · 删空许诺：「请稍等片刻，我会尽快为您查询并回复」「稍后回复您」……
    · 删自我否定：「我并没有情感，所以不能感受到高兴」「我是一个AI机器人，
      我的任务是为用户提供服务」（2026-11-01 用户截图里的原话）
    · 删书面模板前缀：「首先，」「其次，」「总之，」「需要注意的是，」……
    · ``` 代码块一个字符都不动（代码/注释里的"首先"不是模板腔）

用法::

    from core.chat.deai import deai
    result = deai("作为一个AI，我不能帮你删库。希望对你有所帮助。")
    result["text"]   # "我不能帮你删库。"
    result["hits"]   # ["自称AI", "客服腔"]
"""
import re

_AI_WORD = r"(?:AI|A\.I\.|人工智能|大?语言模型|AI\s*助手|人工智能助手|智能助手|聊天机器人)"

# 「作为一个AI，」「作为人工智能助手，」——只删句首（含换行后）的那一段
_P_SELF_INTRO = re.compile(
    r"(?:^|(?<=[。！？!?；;\n]))[ \t]*"
    r"作为(?:一(?:个|名|位)?)?[ \t]*" + _AI_WORD + r"[ \t]*[，,：:][ \t]*")

# 句中还残留（续写、插话）时直接删掉，「我作为一个AI」不能变成「我我」
_P_SELF_ANY = re.compile(r"作为(?:一(?:个|名|位)?)?[ \t]*" + _AI_WORD + r"[，,]?")

# 客服腔：这类话放哪都是废话，整句删
_P_SERVICE = re.compile(
    r"(?:希望(?:这些|以上)?(?:内容|信息)?(?:能)?对(?:你|您)(?:有(?:所)?帮助|有用)"
    r"|希望(?:能)?帮到(?:你|您)"
    r"|很(?:高兴|荣幸)(?:能)?[ \t]*为(?:你|您)?[ \t]*(?:服务|解答|解答疑问|解答问题|效劳)"
    r"|这(?:是)?(?:一个|个)?(?:非常|很|挺)?(?:好|不错)的问题"
    r"|还有(?:什么|其他)(?:可以|需要)?(?:我)?(?:能)?帮(?:你|您)(?:的)?(?:吗|呢)?"
    r"|还有(?:什么|其他|别的)(?:问题|需要)(?:吗|么|要问)?"
    r"|(?:请问)?还有其他(?:问题|需要)(?:吗|么)?)"
    r"[ \t]*[。！!？?]?")
_P_SERVICE_TAIL = re.compile(
    r"(?:如果|如|要是|若)(?:你|您)?(?:还)?(?:有|需要)(?:任何|什么|其他|别的)?"
    r"(?:问题|疑问|需要|要求|吩咐)[，,、]?[ \t]*"
    r"(?:也)?(?:可以|请|欢迎)?[ \t]*(?:随时)?[ \t]*"
    r"(?:告诉|联系|找|问|喊)(?:我|我们)?"
    r"[ \t]*[。！!？?]?")

# 空许诺：「请稍等片刻，我会尽快为您查询并回复」「稍后回复您」
# 实测（2026-11-01）用户问"最近的烧烤店"，模型没数据就回一句
# 「好的，请稍等片刻，我会尽快为您查询并回复」—— 它其实永远不会查。
# 这类句子比不说话更糟：用户会一直等。只删**承诺动作**的句式，
# 「我查到了…」这种有结果的句子不动。
_P_PROMISE = re.compile(
    r"(?:请(?:稍等|稍候|耐心等待)(?:片刻|一下|一会(?:儿)?)?"
    r"|我(?:会|要|马上|立刻|这就|现在)(?:尽快|为您|为你|马上|立刻|去){0,3}"
    r"(?:查询|查一下|查查|搜索|搜一下|查找|处理)(?:并|然后)?(?:您|你)?"
    r"(?:回复(?:您|你)?|答复|告诉(?:您|你))"
    r"|稍后(?:会|再)?(?:回复|答复|告诉)(?:您|你)?"
    r"|我(?:会|将)尽快(?:回复|答复)(?:您|你)?)"
    r"[ \t]*[。！!？?，,；;]?")

# 自称"没有情感/只是个机器人"：用户截图里那条原话是
#   「抱歉，我刚刚的回复有误，我并没有情感，所以不能感受到高兴，
#     我是一个AI机器人，我的任务是为用户提供服务。」
# 这不是人格，是自我否定 —— 整句删掉，别留着污染对话。
_P_SELF_DENY = re.compile(
    r"(?:^|(?<=[。！？!?；;，,、\n]))[ \t]*"
    r"(?:我(?:并)?(?:没有|不具备|不会有|缺乏)(?:真实)?(?:的)?(?:情感|情绪|感情)"
    r"|我(?:只|就)?是(?:一(?:个|台|名))?(?:AI|人工智能|机器人|语言模型)"
    r"|我(?:无法|不能|不会)(?:真正)?(?:感受|拥有|理解)(?:到)?(?:情感|情绪|感情)"
    r"|(?:所以)?(?:我)?(?:不能|无法|不会)(?:真正)?(?:感受到|感受|体会到)"
    r"(?:高兴|难过|悲伤|伤心|情绪|情感|感情|喜悦|愤怒|痛苦|快乐|心情)"
    r"|我的任务(?:就)?是为(?:用户|你)提供(?:服务|帮助)"
    r"|我(?:只|就)(?:能|会)?(?:按|按照)(?:设定|程序|规则)(?:回答|回复))"
    r"[^。！？!?\n，,；;]*"          # 这个分句剩下的部分一起删
    r"[，,、。！!？?；;]?")

# 书面模板腔：只删句首（含换行后）且后面跟逗号/冒号的那种，
# 「最后我还是选了 A」没有逗号，不会被误伤。
_P_TEMPLATE = re.compile(
    r"(?:^|(?<=[。！？!?；;\n]))[ \t]*"
    r"(?:首先|其次|再次|第三|总之|总的来说|总而言之|综上所述|综上"
    r"|需要注意的是|值得注意的是|需要提醒的是"
    r"|简单来说|换句话说|以下是|下面是)[ \t]*[，,：:][ \t]*")

_RULES = (
    ("自称AI", _P_SELF_INTRO),
    ("自称AI", _P_SELF_ANY),
    ("自我否定", _P_SELF_DENY),
    ("客服腔", _P_SERVICE),
    ("客服腔", _P_SERVICE_TAIL),
    ("空许诺", _P_PROMISE),
    ("模板前缀", _P_TEMPLATE),
)

# 结尾本来就该留着的符号：句号类 + 引号/括号/波浪号（表情）
_SOFT_END = "。！？!?…~～\"'」』”’）)]}"


def _tidy(text, close=False):
    """收敛被删出来的空标点。

    ``close=True`` 才处理"整段结尾"（去掉末尾孤零零的逗号、补个句号），
    因为一段话后面还跟着代码块时，结尾其实是「这样写：」，不该被改成句号。
    """
    if not text:
        return text
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[，,、；;：:]+(?=[。！？!?])", "", text)
    text = re.sub(r"(?<=[。！？!?])[，,、；;：:]+", "", text)
    text = re.sub(r"[，,、；;：:]{2,}", "，", text)
    text = re.sub(r"。。+", "。", text)
    text = re.sub(r"[！!][！!]+", "！", text)
    text = re.sub(r"[？?][？?]+", "？", text)
    lines = [re.sub(r"^[ \t]*[，,、；;：:]+[ \t]*", "", row).rstrip()
             for row in text.split("\n")]
    text = "\n".join(lines)
    if not close:
        return text
    text = text.rstrip()
    text = re.sub(r"[，,、；;：:]+$", "", text)
    if text and text[-1] not in _SOFT_END:
        text += "。"
    return text


def _split_blocks(text):
    """按 ``` 围栏切成 (是否代码, 内容)；围栏行本身也算代码，原样保留。"""
    parts, buf, in_code = [], [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            if buf:
                parts.append((in_code, "".join(buf)))
                buf = []
            parts.append((True, line))   # 围栏行不参与清理
            in_code = not in_code
            continue
        buf.append(line)
    if buf:
        parts.append((in_code, "".join(buf)))
    return parts


def deai(text):
    """清一遍 AI 腔。返回 ``{"text": 新文本, "hits": [命中规则名]}``。

    空输入、清完变空（整条回复都是客套话）都返回原文 ——
    宁可留一句废话，也不能把回复清成空白。
    """
    original = "" if text is None else str(text)
    if not original.strip():
        return {"text": original, "hits": []}
    hits = []
    out, last_prose = [], -1
    for is_code, chunk in _split_blocks(original):
        if is_code:
            out.append(chunk)
            continue
        cleaned = chunk
        for name, pattern in _RULES:
            cleaned, count = pattern.subn("", cleaned)
            if count and name not in hits:
                hits.append(name)
        out.append(_tidy(cleaned))
        last_prose = len(out) - 1
    if not hits:
        return {"text": original, "hits": []}
    # 只有"正文结尾"才补句号：后面还跟着代码块时，那句「这样写：」不能改
    if last_prose >= 0 and last_prose == len(out) - 1:
        out[last_prose] = _tidy(out[last_prose], close=True)
    body = "".join(out).strip()
    if not body:                     # 整条都是客套话：宁可留原样
        return {"text": original, "hits": []}
    return {"text": body, "hits": hits}


def strip_ai_tone(text):
    """只想要文本时的便捷入口（失败也返回原文）。"""
    return deai(text)["text"]
