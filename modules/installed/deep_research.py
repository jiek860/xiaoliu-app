# -*- coding: utf-8 -*-
"""深度研究 Agent v1.0 - 多跳联网研究，带引用报告

对标 DeerFlow / OpenHands Researcher：
  1. LLM 拆 3~5 子问题
  2. 并行搜索（API provider 或降级到 deep_search）
  3. 判断是否需要补搜（最多 3 跳）
  4. 60 秒硬超时
  5. 输出带 [1][2] 引用的报告 + 末尾 URL 列表
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json, time, urllib.request, urllib.parse, concurrent.futures
from modules.base import BaseModule


class _BaseProvider:
    """搜索 API provider 抽象基类"""
    NAME = "base"
    def __init__(self, trunk, api_key):
        self.trunk = trunk
        self.api_key = api_key
    def search(self, query, n=5):
        raise NotImplementedError
    @property
    def available(self):
        return bool(self.api_key)


class _BraveProvider(_BaseProvider):
    NAME = "brave"
    def search(self, query, n=5):
        url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={n}"
        req = urllib.request.Request(url, headers={
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=8) as r:  # nosec B310 - fixed provider HTTPS endpoint
            data = json.loads(r.read())
        out = []
        for item in data.get("web", {}).get("results", [])[:n]:
            out.append({
                "标题": item.get("title", ""),
                "摘要": item.get("description", "")[:200],
                "链接": item.get("url", ""),
                "内容": item.get("description", "")[:300],
            })
        return out


class _TavilyProvider(_BaseProvider):
    NAME = "tavily"
    def search(self, query, n=5):
        body = json.dumps({"api_key": self.api_key, "query": query, "max_results": n}).encode()
        req = urllib.request.Request("https://api.tavily.com/search", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:  # nosec B310 - fixed provider HTTPS endpoint
            data = json.loads(r.read())
        out = []
        for item in data.get("results", [])[:n]:
            out.append({
                "标题": item.get("title", ""),
                "摘要": item.get("content", "")[:200],
                "链接": item.get("url", ""),
                "内容": item.get("content", "")[:300],
            })
        return out


class _BochaProvider(_BaseProvider):
    NAME = "bocha"
    def search(self, query, n=5):
        url = f"https://api.bochaai.com/v1/web-search?query={urllib.parse.quote(query)}&count={n}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.api_key}",
        })
        with urllib.request.urlopen(req, timeout=8) as r:  # nosec B310 - fixed provider HTTPS endpoint
            data = json.loads(r.read())
        out = []
        for item in data.get("webPages", {}).get("value", [])[:n]:
            out.append({
                "标题": item.get("name", ""),
                "摘要": item.get("snippet", "")[:200],
                "链接": item.get("url", ""),
                "内容": item.get("snippet", "")[:300],
            })
        return out


class _SerperProvider(_BaseProvider):
    NAME = "serper"
    def search(self, query, n=5):
        body = json.dumps({"q": query, "num": n}).encode()
        req = urllib.request.Request("https://google.serper.dev/search", data=body,
                                     headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:  # nosec B310 - fixed provider HTTPS endpoint
            data = json.loads(r.read())
        out = []
        for item in data.get("organic", [])[:n]:
            out.append({
                "标题": item.get("title", ""),
                "摘要": item.get("snippet", "")[:200],
                "链接": item.get("link", ""),
                "内容": item.get("snippet", "")[:300],
            })
        return out


class DeepResearch(BaseModule):
    _PROVIDERS = {
        "brave": _BraveProvider,
        "tavily": _TavilyProvider,
        "bocha": _BochaProvider,
        "serper": _SerperProvider,
    }
    """多跳深度研究 Agent"""
    NAME = "deep_research"
    VERSION = "1.0"

    TOOLS = [
        {"name": "research", "method": "research",
         "desc": "多跳联网研究一个问题，输出带引用编号的详细报告（60秒内）",
         "args": {"topic": "要研究的问题或主题，如：PyQt5 最佳实践、RAG 框架对比"},
         "readonly": True,
         "hints": ["研究", "调研", "深度搜索", "对比", "分析", "report", "research"],
         "contract": {
             "params": {"topic": {"type": "string"}},
             "returns": {"type": "string"},
             "errors": ["PLUGIN_TIMEOUT", "PLUGIN_UPSTREAM_ERROR"],
             "side_effects": [],
             "description": "多跳联网研究，输出带引用的报告",
             "not_responsible": ["不负责事实核查", "不负责写论文"]
         }},
    ]

    MAX_HOPS = 3
    TIMEOUT = 60.0
    MAX_SUBQ = 5

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self._providers = []
        self._init_providers()

    def _init_providers(self):
        """从配置/环境变量加载 API key，初始化可用的 provider"""
        keys = {}
        try:
            if self.trunk and hasattr(self.trunk, "config"):
                cfg = self.trunk.config
                for name in self._PROVIDERS:
                    v = cfg.get(f"search.{name}_api_key", "")
                    if v:
                        keys[name] = v
        except Exception as e:
            _x6_swallowed(__name__, e)

        # 环境变量兜底（走基类 env()，不再直接读进程级环境变量）
        for name in self._PROVIDERS:
            v = self.env(f"{name.upper()}_API_KEY")
            if v and name not in keys:
                keys[name] = v

        for name, key in keys.items():
            self._providers.append(self._PROVIDERS[name](self.trunk, key))

    @property
    def _has_api_provider(self):
        return len(self._providers) > 0

    def _search(self, query, n=5):
        """统一搜索入口：有 API 用 API，没有降级到 deep_search"""
        if self._has_api_provider:
            for p in self._providers:
                try:
                    return p.search(query, n)
                except Exception as e:
                    _x6_swallowed(__name__, e, f"provider={p.NAME}")
                    continue
        # 降级到现有 deep_search
        try:
            ds = self.trunk.modules.get("deep_search") if self.trunk else None
            if ds:
                r = ds.search(query)
                return r.get("结果", [])[:n]
        except Exception as e:
            _x6_swallowed(__name__, e)
        return []

    def _split_subquestions(self, topic):
        """LLM 拆 3~5 个子问题"""
        if not self.trunk:
            return [topic]
        llm = self.trunk.modules.get("llm")
        if not llm:
            return [topic]
        try:
            prompt = (f"把这个研究主题拆成 {self.MAX_SUBQ} 个具体的搜索子问题，"
                      f"每行一个，不要编号，不要解释：\n{topic}")
            ans = llm.chat(prompt)
            subs = [l.strip() for l in ans.strip().split("\n") if l.strip() and len(l.strip()) > 3]
            return subs[:self.MAX_SUBQ] if subs else [topic]
        except Exception as e:
            _x6_swallowed(__name__, e)
            return [topic]

    def _need_more_search(self, topic, results):
        """LLM 判断是否需要补搜"""
        if not self.trunk or not results:
            return None
        llm = self.trunk.modules.get("llm")
        if not llm:
            return None
        try:
            txt = "\n".join(f"- {r.get('标题','')}: {r.get('摘要','')[:100]}" for r in results[:5])
            prompt = (f"研究主题：{topic}\n已搜索到的资料：\n{txt}\n\n"
                      f"资料是否足够回答主题？如果不够，给出一个新的搜索关键词（一行）；"
                      f"如果足够，回答'足够'。")
            ans = llm.chat(prompt).strip()
            if "足够" in ans or len(ans) < 3:
                return None
            return ans.split("\n")[0].strip()
        except Exception as e:
            _x6_swallowed(__name__, e)
            return None

    def research(self, topic):
        """主入口：多跳研究，返回带引用的报告"""
        t0 = time.time()
        all_results = []
        seen_titles = set()

        # 第 1 跳：拆子问题并行搜
        subs = self._split_subquestions(topic)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(subs)) as ex:
            futs = {ex.submit(self._search, s, 5): s for s in subs}
            for f in concurrent.futures.as_completed(futs, timeout=self.TIMEOUT):
                if time.time() - t0 > self.TIMEOUT:
                    break
                try:
                    for r in f.result():
                        t = r.get("标题", "")
                        if t and t not in seen_titles:
                            seen_titles.add(t)
                            all_results.append(r)
                except Exception as e:
                    _x6_swallowed(__name__, e)

        # 第 2~N 跳：补搜
        hop = 1
        while hop < self.MAX_HOPS and time.time() - t0 < self.TIMEOUT:
            extra = self._need_more_search(topic, all_results)
            if not extra:
                break
            try:
                for r in self._search(extra, 3):
                    t = r.get("标题", "")
                    if t and t not in seen_titles:
                        seen_titles.add(t)
                        all_results.append(r)
            except Exception as e:
                _x6_swallowed(__name__, e)
            hop += 1

        # 生成报告
        elapsed = time.time() - t0
        report = self._build_report(topic, all_results, elapsed)
        return report

    def _build_report(self, topic, results, elapsed):
        """生成带 [n] 引用的报告"""
        # 给结果编号
        for i, r in enumerate(results, 1):
            r["_ref"] = i

        # LLM 写报告
        report_text = ""
        if self.trunk:
            llm = self.trunk.modules.get("llm")
            if llm:
                try:
                    txt = "\n".join(
                        f"[{r['_ref']}] {r.get('标题','')}: {r.get('内容','')[:200]}"
                        for r in results[:10]
                    )
                    from core.untrusted_content import wrap_untrusted
                    txt = wrap_untrusted(txt, source="deep_research", kind="search")
                    prompt = (f"研究主题：{topic}\n\n参考资料：\n{txt}\n\n"
                              f"请写一份 800 字左右的研究报告，要求：\n"
                              f"1. 每个事实后面标注引用编号 [n]\n"
                              f"2. 结构清晰：概述 / 要点 / 结论\n"
                              f"3. 不要编造资料里没有的内容")
                    report_text = llm.chat(prompt)
                except Exception as e:
                    _x6_swallowed(__name__, e)

        if not report_text:
            report_text = f"研究主题：{topic}\n\n（LLM 不可用，以下是原始搜索结果）\n"
            for r in results[:10]:
                report_text += f"\n[{r['_ref']}] {r.get('标题','')}\n    {r.get('摘要','')[:150]}\n"

        # 末尾 URL 列表
        sources = []
        for r in results[:15]:
            sources.append({
                "ref": r["_ref"],
                "标题": r.get("标题", ""),
                "链接": r.get("链接", ""),
            })

        return {
            "主题": topic,
            "报告": report_text,
            "引用": sources,
            "耗时秒": round(elapsed, 1),
            "结果数": len(results),
            "API模式": self._has_api_provider,
        }

    def run(self, *a):
        topic = a[0] if a else "人工智能发展趋势"
        return self.research(topic)
