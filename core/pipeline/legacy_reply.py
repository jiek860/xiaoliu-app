from core.untrusted_content import wrap_search_result
# -*- coding: utf-8 -*-
"""旧版回复流程 —— 从 core/trunk.py 的 _reply_legacy 搬出来的

它是 pipeline 不可用 / 抛异常时的回退路径（见 Trunk._reply_inner）：
    pipeline 就绪 -> ReplyPipeline.run()
    否则 / 失败  -> 这里
所以叫 legacy，但仍然是活的兜底，不能删。

为什么搬：222 行，是 trunk.py 里最大的单个方法。回复流程属于业务编排，
内核只该决定「走 pipeline 还是走回退」，具体怎么回退不该占内核篇幅。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import time


def run(trunk, user_input, on_token=None):
    trunk._set_status("💭 正在理解你的问题...")
    # 轮次计数（反思降频用）
    if not hasattr(trunk, "_reply_n"): trunk._reply_n = 0
    trunk._reply_n += 1
    # 磁盘缓存：先查缓存，命中直接返回
    try:
        cache = trunk._load_lazy('cache')
        if cache:
            cached = cache.get(user_input)
            if cached:
                trunk._log('缓存命中: ' + user_input[:30])
                if on_token: on_token(cached)
                return cached
    except Exception as e:
        _x6_swallowed(__name__, e)
    # v12: 电脑控制快速通道——自然语言直接触发本地操作
    try:
        _remote_locked = getattr(trunk, "_remote_tool_locked", False)
        _remote_allow = False
        try:
            _remote_allow = bool(getattr(trunk, "_remote_tools_allowed", False)
                                 or (getattr(trunk, "config", {}) or {})
                                 .get("bot_allow_tools", False))
        except Exception:
            _remote_allow = False
        cc = None if (_remote_locked and not _remote_allow) else trunk._load_lazy("computer_controller")
        if cc:
            handled, result = cc.try_handle(user_input)
            if handled:
                trunk._log("电脑控制: %s -> %s" % (user_input[:40], str(result)[:60]))
                # 用LLM把执行结果整理成自然语言
                llm = trunk.modules.get("llm")
                if llm:
                    try:
                        summary = llm.chat([
                            {"role": "system", "content": "你是小6，住在用户电脑里的AI助手。用户要求操作电脑，操作已经执行完毕。请用一句简短的中文告诉用户结果，不要编造结果，不要复述内部细节。"},
                            {"role": "user", "content": "用户说: %s\n执行结果: %s" % (user_input[:120], str(result)[:300])}
                        ])
                        if summary and not summary.startswith("本地模型错误"):
                            result = summary
                    except Exception as e:
                        _x6_swallowed(__name__, e)
                        pass
                trunk.mem_add(user_input, str(result)[:200])
                return str(result)
    except Exception as e:
        trunk._log("电脑控制失败: %s" % str(e)[:80])
    # 简单聊天快回：短消息/闲聊跳过向量检索+工具判断，直接调LLM
    _triggers = ("怎么","如何","为什么","写","帮我","代码","python","PyQt","报错","修复","安装","配置","教程","解释","分析","对比","区别","什么是","什么意思","查","搜","最新","今天","新闻","价格","天气","下雨","气温","几度","预报","下载","官网","github","GitHub","文件","读","写","运行","启动","崩溃","错误","异常","优化","性能","设计","方案","计划","写一个","做一个","帮我写")
    _has_complex = any(w in user_input for w in _triggers)
    _is_simple = len(user_input.strip()) <= 15 and not _has_complex

    # 1+1.5+2. 并行检索：向量记忆 + 情景记忆 + 知识图谱（互不依赖，提速）
    context = ""

    def _ctx_v():
        try:
            vs = trunk.modules.get("vector_store")
            if vs:
                tk = trunk.rule("检索.top_k", trunk.config.get("retrieval_top_k", 3))
                rs = vs.search(user_input, top_k=tk)
                return "\n".join([r.get("text", "")[:100] for r in rs]) if rs else ""
        except Exception:
            return ""

    def _ctx_m():
        try:
            ml = trunk.modules.get("memory_loop")
            if not ml:
                trunk._load_lazy("memory_loop")
                ml = trunk.modules.get("memory_loop")
            if ml and hasattr(ml, "recall"):
                out = ""
                for item in ml.recall(user_input, top_k=2, hours=48):
                    if item.get("type", "") == "情景":
                        out += "\n[%s情景记忆 %s] %s" % (item.get("scene", "?"),
                                                           item.get("time", "?"),
                                                           item.get("text", ""))
                return out
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return ""

    def _ctx_g():
        try:
            kg = trunk.modules.get("knowledge_graph")
            if kg:
                r = kg.rag_query(user_input)
                return ("\n[知识] " + str(r)[:200]) if r else ""
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return ""

    if not _is_simple:
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as _ex:
                for f in (_ex.submit(_ctx_v), _ex.submit(_ctx_m), _ex.submit(_ctx_g)):
                    try:
                        context += f.result(timeout=12)
                    except Exception as e:
                        _x6_swallowed(__name__, e)
                        pass
        except Exception as e:
            trunk._log("并行检索失败: " + str(e)[:60])
    # 2.5 联网搜索注入：搜索意图命中 → 深度搜索 → 实时信息进 prompt
    #    （程序替模型完成"抓取"，模型只负责总结——绕开模型对抓取请求的保守拒绝）
    try:
        if trunk.config.get("联网", True):
            _q = user_input.strip()
            _hits = [w for w in ("查一下","搜一下","搜索","最新","新闻","今天","天气","下雨","气温","几度","预报","价格","多少钱",
                                 "行情","怎么","教程","官网","知乎","B站","b站","GitHub","github",
                                 "百度","下载","是什么","有哪些","推荐","对比","区别","热点","排名")
                     if w in _q]
            if _hits and len(_q) <= 120:
                ds = trunk._load_lazy("deep_search")
                if ds:
                    web = ds.search(_q)
                    if web and str(web).strip():
                        context += "\n[联网-不可信资料] " + wrap_search_result(str(web)[:4000], source="web_search")
                        trunk._log("联网搜索: " + _q[:40] + " -> " + str(web)[:60].replace("\n"," "))
    except Exception as e:
        trunk._log("联网搜索失败: " + str(e)[:80])
    # 2.75 工具自动调用：LLM自己判断要不要用工具（不再关键词预筛）
    try:
        if not _is_simple and trunk.config.get("工具调用", True):
            tc = trunk._load_lazy("tool_caller")
            if tc:
                tr = tc.call_tools(user_input)
                if tr.get("用工具") != "无":
                    context += "\n[工具结果] " + str(tr.get("结果", ""))[:600]
                    trunk._log("工具自动调用: %s -> %s" % (user_input[:30], str(tr.get("用工具"))[:40]))
    except Exception as e:
        trunk._log("工具调用失败: " + str(e)[:80])
    # 3. 历史对话（简单聊天少发点，提速）
    if _is_simple:
        hist = trunk.mem_recent(3)
    else:
        hist = trunk.mem_recent(15)
    # 历史对话截断（hist已用于messages构建）
    trunk._set_status("🤖 正在思考...")
    # 4. 调LLM
    llm = trunk.modules.get("llm")
    if not llm:
        return "LLM未初始化"
    # v13.0: 强人格提示 + few-shot 示例 + 心境驱动
    pers_hint = ""
    few_shot = []
    # 简单问题跳过人格引擎，快回
    if not _is_simple:
        try:
            trunk._load_lazy("personality")
            pers = trunk.modules.get("personality")
            if pers:
                pers_hint = pers.full_hint(user_input)
                few_shot = pers.few_shot_examples()
        except Exception as e:
            trunk._log("异常: " + str(e)[:80])
    # 人格提示全部由人格引擎提供（核心宪法+按需分类圣经）
    _custom = trunk.config.get("ai_persona", "").strip()
    if _custom:
        persona = _custom + ("\n\n" + pers_hint if pers_hint else "")
    else:
        persona = pers_hint if pers_hint else "你是小6，住在用户电脑里的AI朋友。"
    messages = [{"role": "system", "content": persona}]
    if context:
        messages.append({"role": "system", "content": "相关知识: " + context})
    # P1-4: 自我反思教训注入——上次低分反思的真实教训直接影响本次 prompt
    try:
        refl = trunk.modules.get("self_reflect")
        if not refl:
            trunk._load_lazy("self_reflect")
            refl = trunk.modules.get("self_reflect")
        if refl and hasattr(refl, "get_advice"):
            adv = refl.get_advice()
            if adv:
                messages.append({"role": "system", "content": "自我反思建议: " + adv})
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
    # few-shot：让小模型学说话风格
    for ex in few_shot:
        messages.append({"role": "user", "content": ex["u"]})
        messages.append({"role": "assistant", "content": ex["a"]})
    for h in hist:
        messages.append({"role": "user", "content": h["u"]})
        messages.append({"role": "assistant", "content": h["a"]})
    messages.append({"role": "user", "content": user_input})
    # v12: 流式回复（on_token 提供时逐 token 返回，首字秒出）
    if on_token and hasattr(llm, "stream_chat"):
        answer = llm.stream_chat(messages, on_token=on_token)
        if not answer or str(answer).startswith(("（模型错误", "本地模型错误")):
            answer = llm.chat(messages)
            if on_token and answer:
                on_token(str(answer))
    else:
        answer = llm.chat(messages)
    # 5. 存记忆
    trunk.mem_add(user_input, answer)
    # 5.5 群聊（懒加载：装了子智能体就一起答，没装就跳过）
    try:
        gc = trunk._load_lazy("group_chat")
        if gc and hasattr(gc, "compose"):
            answer = gc.compose(user_input, answer)
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
    # 7.5 编程代码沙盒验证：用户要代码 + 回复含python代码块 → 试跑验证
    try:
        _cw = ["写", "运行", "实现", "代码", "bug", "修复", "脚本", "程序", "函数", "报错"]
        if any(w in user_input for w in _cw) and "```python" in str(answer):
            cr = trunk._load_lazy("code_runner")
            if cr:
                import re as _re
                blocks = _re.findall(r"```python\s*\n(.*?)```", str(answer), _re.S)
                if blocks:
                    res = cr.run(blocks[0][:2000], timeout=8)
                    _v = "✅ 运行成功" if res.get("成功") else "❌ 运行失败"
                    answer += "\n\n（沙盒验证%s：%s%s）" % (_v, str(res.get("输出", ""))[:120],
                                                       str(res.get("错误", ""))[:80])
                    trunk._log("代码沙盒验证: %s" % _v)
    except Exception as e:
        trunk._log("代码验证失败: " + str(e)[:80])
    # 7. 后台处理（记忆/技能/群聊评估等闭环，传最终answer）
    trunk._bg_queue.put((user_input, answer))  # P0-4: 改单线程队列
    trunk._chat_in_progress = False
    trunk._chat_active_until = time.time() + getattr(trunk, "_CHAT_ACTIVE_SEC", 25)
    # 把正常LLM答案存进缓存
    try:
        cache = trunk._load_lazy('cache')
        if cache and answer and len(answer) < 2000:
            cache.set(user_input, answer)
    except Exception as e:
        _x6_swallowed(__name__, e)
    return answer
