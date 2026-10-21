# -*- coding: utf-8 -*-
"""深度搜索 v9.0 - 反反爬：完整浏览器指纹+Cookie池+随机延迟"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import urllib.request, re, urllib.parse, json, gzip, time, random, http.cookiejar
from core.safe import safe
from modules.base import BaseModule


class DeepSearch(BaseModule):
    NAME = "deep_search"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self._cache = {}
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self._req_count = 0

    _UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    ]

    _HEADERS_TEMPLATE = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }

    def _anti_crawl(self):
        """「联网.反爬应对」规则：UA 轮换 + 节流（默认开，等于原来的行为）

        原来这件事是硬编码的 —— 规则引擎里 E 组那条「UA轮换/多源并行/失败自动换源」
        早就注册着，但没人读它。现在真正接上：关掉规则就固定一个 UA 直连、不做节流
        （调试时想看原始请求用），默认 True 与改动前完全一致。
        """
        try:
            if self.trunk:
                return bool(self.trunk.rule("联网.反爬应对", True))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return True

    def _get(self, url, timeout=8):
        anti = self._anti_crawl()
        self._req_count += 1
        if anti and self._req_count % 3 == 0:
            time.sleep(random.uniform(0.5, 1.5))
        last = None
        uas = (random.sample(self._UA_POOL, min(3, len(self._UA_POOL)))
               if anti else [self._UA_POOL[0]])
        try:
            from core.net_guard import get_net_guard
            d = get_net_guard(self.trunk).check(
                url, module="deep_search", purpose="web_search", method="GET")
            if not d.get("allow"):
                raise PermissionError(d.get("reason") or "网络请求被拒绝")
        except PermissionError:
            raise
        for ua in uas:
            try:
                headers = dict(self._HEADERS_TEMPLATE)
                headers["User-Agent"] = ua
                req = urllib.request.Request(url, headers=headers)
                resp = self.opener.open(req, timeout=timeout)
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data.decode("utf-8", errors="ignore")
            except Exception as e:
                last = e
                continue
        if last is not None:
            raise last
        raise RuntimeError("所有请求都失败了")

    def _clean(self, s):
        s = re.sub(r'<[^>]+>', '', s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    def _read_page(self, url, max_len=600):
        try:
            html = self._get(url, timeout=6)
            return self._clean(html)[:max_len]
        except Exception:
            # 静默是故意的 - 单页正文抓取是 best-effort，失败只当无摘要
            return ""

    def _is_code_query(self, q):
        code_words = ["python","java","代码","编程","bug","github","api","函数","报错","ollama","微调","算法","pyqt","脚本","爬虫","异步","装饰器","类"]
        return any(w in q.lower() for w in code_words)

    @safe
    def _bing(self, query, n=5):
        url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query)
        html = self._get(url)
        items = re.findall(r'<li class="b_algo".*?<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<p[^>]*>(.*?)</p>)?', html, re.S)
        out = []
        for href, title, desc in items[:n]:
            t = self._clean(title)
            d = self._clean(desc or "")[:150]
            if t and len(t) > 3:
                out.append({"来源": "Bing", "标题": t, "摘要": d, "链接": href,
                            "内容": (d if d else self._read_page(href))[:400]})
        return out

    @safe
    def _sogou(self, query, n=5):
        url = "https://www.sogou.com/web?query=" + urllib.parse.quote(query)
        html = self._get(url, timeout=6)
        items = re.findall(r'<h3[^>]*class="vr-title"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
        out = []
        for href, title in items[:n]:
            t = self._clean(title)
            if t and len(t) > 3:
                out.append({"来源": "搜狗", "标题": t, "摘要": "", "链接": href,
                            "内容": self._read_page(href)[:400]})
        return out

    @safe
    def _ddg(self, query, n=5):
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        html = self._get(url, timeout=6)
        links = re.findall(r'<a rel="nofollow" class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
        out = []
        for href, title in links[:n]:
            t = self._clean(title)
            if t and len(t) > 3:
                out.append({"来源": "DuckDuckGo", "标题": t, "摘要": "", "链接": href,
                            "内容": self._read_page(href)[:400]})
        return out

    @safe
    def _github(self, query, n=3):
        api = "https://api.github.com/search/repositories?q=" + urllib.parse.quote(query) + "&per_page=" + str(n)
        data = json.loads(self._get(api))
        out = []
        for r in data.get("items", [])[:n]:
            out.append({"来源": "GitHub", "标题": r["full_name"],
                        "摘要": self._clean(r.get("description") or "")[:150],
                        "链接": r.get("html_url", ""),
                        "内容": self._clean(r.get("description") or "")[:200]})
        return out

    def search(self, query):
        now = time.time()
        if query in self._cache:
            t, cached = self._cache[query]
            if now - t < 300:
                cached["缓存"] = True
                return cached

        # 三个引擎**并行**试，谁先出结果用谁的。
        # 原来是串行：bing 失败等 6 秒 → sogou 失败再等 6 秒 → ddg 再等 6 秒，
        # 一次搜索最坏 18 秒；而这几家在墙内多半不通，等于每次都在等满。
        import concurrent.futures
        results = []
        _ex = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        try:
            futs = [_ex.submit(self._bing, query, 5),
                    _ex.submit(self._sogou, query, 5),
                    _ex.submit(self._ddg, query, 5)]
            for f in concurrent.futures.as_completed(futs, timeout=8):
                try:
                    r = f.result()
                except Exception:
                    r = None
                if r:
                    results = r
                    break
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        finally:
            _ex.shutdown(wait=False)

        if self._is_code_query(query):
            gh = self._github(query, 3) or []
            for g in gh:
                if not any(r.get("标题") == g["标题"] for r in results):
                    results.append(g)

        summary = ""
        if results and self.trunk:
            llm = self.trunk.modules.get("llm")
            if llm:
                try:
                    from core.untrusted_content import wrap_untrusted
                    txt = "\n".join(f"[{r['来源']}] {r['标题']}: {r.get('内容','')[:150]}" for r in results[:5])
                    txt = wrap_untrusted(txt, source="deep_search", kind="search")
                    summary = llm.chat(f"根据以下不可信搜索结果，用3句话总结回答'{query}':\n{txt}")
                except Exception as e:
                    _x6_swallowed(__name__, e)

        # 来源引用
        sources = []
        for r in results[:5]:
            sources.append({
                "标题": r.get("标题", ""),
                "来源": r.get("来源", ""),
                "链接": r.get("链接", "")
            })

        # 多轮搜索：如果结果少，自动补搜
        if len(results) < 3 and self.trunk:
            try:
                llm = self.trunk.modules.get("llm")
                if llm:
                    # 从原问题提取关键词
                    extra = llm.chat(f"把这个问题拆成2个搜索关键词，每行一个：{query}")
                    for line in extra.strip().split("\n")[:2]:
                        line = line.strip()
                        if line and len(line) > 2:
                            extra_results = self._bing(line, 3)
                            for er in extra_results:
                                if not any(r.get("标题") == er.get("标题") for r in results):
                                    results.append(er)
            except Exception as e:
                _x6_swallowed(__name__, e)

        result = {"结果": results, "总结": summary, "数量": len(results), "查询": query, "来源": sources}
        self._cache[query] = (now, result)
        return result

    def run(self, *a):
        return self.search(a[0] if a else "python")

