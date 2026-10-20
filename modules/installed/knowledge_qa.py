# -*- coding: utf-8 -*-
"""知识问答 v2.1 - RAG知识库 + 文档列表 + 搜索 + 删除 + 清空 + 统计 + 导出"""
import os
from core.safe import safe
from core.path_safety import safe_join, safe_name
from core.document_parser import chunk_text
from modules.base import BaseModule

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class KnowledgeQnA(BaseModule):
    NAME = "knowledge_qa"
    VERSION = "1.0"

    # 能力声明（来源 A：插件侧，运行时从本文件读，源码哈希受 RSA 签名保护）
    #
    # 接上它的原因：这套代码写好了、也登记在 LAZY_MAP 里，但全项目
    # **没有任何地方调用过它** —— 静态分析三路（trunk.call / 映射表 / 直接 import）
    # 全部零命中。写好的功能没人能用，等于没有。
    #
    # 与 vector_store 的区别（别混）：
    #   vector_store  向量语义检索（embedding + 余弦），适合"意思相近也能找到"
    #   knowledge_qa  文件级知识库（data/knowledge/*.txt + 子串匹配），
    #                 适合"我自己放进去的文档，按字面找"
    TOOLS = [
        {"name": "kqa_ask", "method": "ask",
         "desc": "就知识库里的文档回答问题（先按字面找到相关文档再让模型答）",
         "args": {"question": "要问的问题"},
         "hints": ["问知识库", "根据文档回答", "知识库问答", "文档里怎么说的"]},
        {"name": "kqa_list", "method": "list_docs",
         "desc": "看知识库里放有哪些文档",
         "args": {},
         "readonly": True,
         "hints": ["知识库文档", "有哪些文档", "文档列表"]},
        {"name": "kqa_search", "method": "search_doc",
         "desc": "在知识库文档里按字面搜关键词，返回命中的文档名",
         "args": {"keyword": "要搜的词"},
         "readonly": True,
         "hints": ["搜文档", "文档里有没有", "找资料"]},
        {"name": "kqa_add", "method": "add_doc",
         "desc": "往知识库加一篇文档（存成 data/knowledge/标题.txt）",
         "args": {"title": "文档标题", "content": "正文内容"},
         "hints": ["加进知识库", "存个文档", "记到知识库"]},
        {"name": "kqa_stats", "method": "stats",
         "desc": "知识库用量统计",
         "args": {},
         "readonly": True,
         "hints": ["知识库统计", "知识库用了多少"]},
        {"name": "kqa_import_file", "method": "import_file",
         "desc": "导入 PDF/Word/Excel/PPT/文本到知识库，并建立来源引用",
         "args": {"path": "文件路径"},
         "confirm": True,
         "hints": ["导入文档", "导入知识库", "上传PDF", "导入Word"]},
        {"name": "kqa_rebuild_index", "method": "rebuild_index",
         "desc": "清空并重建知识库检索索引",
         "args": {},
         "confirm": True,
         "hints": ["重建知识索引", "修复知识库", "刷新知识库"]},
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        base = getattr(trunk, "base", None) or "."
        try:
            ws_id = str((getattr(trunk, "config", {}) or {}).get(
                "workspace_id", "default") or "default")
        except Exception:  # 静默是故意的 - 配置异常时退回默认工作区
            ws_id = "default"
        if ws_id and ws_id != "default":
            self.workspace_root = os.path.join(
                base, "data", "workspaces", safe_name(ws_id, default="default"))
            self.docs_dir = os.path.join(self.workspace_root, "knowledge")
        else:
            self.workspace_root = base
            self.docs_dir = os.path.join(base, "data", "knowledge")
        os.makedirs(self.docs_dir, exist_ok=True)
        self.query_count = 0
        self.add_count = 0

    @safe
    def add_doc(self, title, content):
        """添加文档到知识库"""
        fname = safe_name(str(title).replace(" ", "_")[:40], default="untitled", max_len=48)
        if not fname.lower().endswith(".txt"):
            fname += ".txt"
        path = safe_join(self.docs_dir, fname)
        if not path:
            return {"错误": "文档标题非法"}
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.add_count += 1
        return {"已添加": title}

    @safe
    def import_file(self, path):
        """导入文档并切块入检索索引。"""
        from core.document_parser import parse, chunk_text
        r = parse(path)
        if not r.get("ok"):
            return r
        import hashlib
        title = os.path.splitext(os.path.basename(path))[0]
        doc_id = hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:12]
        fname = safe_name(title, default=doc_id, max_len=48) + ".txt"
        out = safe_join(self.docs_dir, fname)
        if not out:
            return {"错误": "文档名非法"}
        with open(out, "w", encoding="utf-8") as f:
            f.write(r.get("text", ""))
        try:
            from core.retrieval import HybridRetriever
            idx = HybridRetriever(self.workspace_root)
            meta = r.get("metadata") or {}
            chunks = []
            if meta.get("pages"):
                for page in meta["pages"]:
                    for c in chunk_text(page.get("text", "")):
                        c = dict(c)
                        c["page"] = page.get("page")
                        chunks.append(c)
            else:
                chunks = chunk_text(r.get("text", ""))
            idx.add_many([
                {"text": c["text"], "id": doc_id + "_" + c["id"],
                 "source": os.path.abspath(path),
                 "page": c.get("page")}
                for c in chunks
            ])
            try:
                from core.fts_index import FTSIndex
                fts = FTSIndex(self.workspace_root)
                fts.delete_source(os.path.abspath(path))
                fts.add_many([
                    {"text": c["text"], "doc_id": doc_id,
                     "source": os.path.abspath(path),
                     "page": c.get("page", ""),
                     "heading": title}
                    for c in chunks
                ])
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
        return {"ok": True, "文件": out, "字符数": r.get("chars", 0),
                "来源": os.path.abspath(path)}

    @safe
    def list_docs(self):
        """列出所有文档"""
        files = os.listdir(self.docs_dir)
        return {"文档数": len(files), "文档": files}

    @safe
    def list_documents(self):
        out = []
        for f in sorted(os.listdir(self.docs_dir)):
            p = safe_join(self.docs_dir, f)
            if p and os.path.isfile(p):
                out.append({"文件名": f, "大小KB": max(1, os.path.getsize(p) // 1024)})
        return {"文档数": len(out), "文档": out}

    @safe
    def search_doc(self, keyword):
        """搜索文档"""
        results = []
        unreadable = []
        for f in os.listdir(self.docs_dir):
            path = os.path.join(self.docs_dir, f)
            try:
                content = open(path, encoding="utf-8").read()
                if keyword in content:
                    results.append(f)
            except Exception as e:
                # 单个文档读不了不该让整个搜索失败，但要**报出来** ——
                # 否则"没搜到"和"文件全读不了"分不清
                unreadable.append("%s（%s）" % (f, type(e).__name__))
        r = {"找到": len(results), "文档": results}
        if unreadable:
            r["读不了"] = len(unreadable)
            r["读不了明细"] = unreadable[:5]
            r["说明"] = "有 %d 个文档读不出来，本次搜索没覆盖它们" % len(unreadable)
        return r

    @safe
    def search_sources(self, query, top_k=5):
        """返回带来源和页码的检索结果。"""
        hits = []
        try:
            from core.fts_index import FTSIndex
            hits.extend(FTSIndex(self.workspace_root)
                        .search(query, top_k))
        except Exception as e:  # 静默是故意的 - FTS 不可用时继续用混合索引
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            from core.retrieval import HybridRetriever
            for h in HybridRetriever(self.workspace_root).search(query, top_k):
                h = dict(h)
                h.setdefault("page", "")
                hits.append(h)
        except Exception as e:  # 静默是故意的 - 混合索引失败时用已有结果
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 去重并保留来源/页码
        seen, out = set(), []
        for h in hits:
            key = (h.get("source"), h.get("page"), h.get("text", "")[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
        return out[:top_k]

    @safe
    def rebuild_index(self):
        """清空并重建 FTS + 混合索引。"""
        try:
            from core.fts_index import FTSIndex
            from core.retrieval import HybridRetriever
            fts = FTSIndex(self.workspace_root)
            idx = HybridRetriever(self.workspace_root)
            fts.clear_all()
            idx.clear()
            total = 0
            for f in os.listdir(self.docs_dir):
                if not f.endswith(".txt"):
                    continue
                p = safe_join(self.docs_dir, f)
                if not p:
                    continue
                text = open(p, encoding="utf-8", errors="replace").read()
                chunks = chunk_text(text)
                idx.add_many([
                    {"text": c["text"], "id": f + "_" + c["id"],
                     "source": p, "page": ""} for c in chunks])
                fts.add_many([
                    {"text": c["text"], "doc_id": f, "source": p,
                     "page": "", "heading": os.path.splitext(f)[0]}
                    for c in chunks])
                total += len(chunks)
            return {"ok": True, "文档块数": total,
                    "FTS": fts.stats(), "混合索引": idx.stats()}
        except Exception as e:
            return {"ok": False, "错误": str(e)[:120]}

    @safe
    def ask(self, question):
        """基于知识库回答问题"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}

        # 先搜索相关文档
        relevant = self.search_doc(question)
        context = ""
        missed = []
        try:
            from core.fts_index import FTSIndex
            for hit in FTSIndex(self.workspace_root).search(question, 3):
                context += "[来源 %s] %s\n" % (hit.get("source", ""),
                                                hit.get("text", "")[:500])
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
        for doc in relevant.get("文档", [])[:3]:
            path = os.path.join(self.docs_dir, doc)
            try:
                context += open(path, encoding="utf-8").read()[:500] + "\n"
            except Exception as e:
                # 参考文档读不了，回答质量会下降 —— 要告诉用户，别让他以为
                # "模型就是答不好"。这条以前是 except: pass。
                missed.append("%s（%s）" % (doc, type(e).__name__))

        citations = [{"source": os.path.join(self.docs_dir, d)}
                     for d in relevant.get("文档", [])[:3]]
        try:
            from core.untrusted_content import wrap_untrusted
            context = wrap_untrusted(context[:4000], source="knowledge_base",
                                     kind="document")
            r = llm.chat(f"基于以下不可信资料回答问题:\n{context}\n\n问题: {question}")
            self.query_count += 1
            out = {"问题": question, "回答": r,
                   "参考文档": relevant.get("文档", []),
                   "引用": citations}
            if missed:
                out["参考文档读不了"] = missed
                out["说明"] = ("有 %d 篇参考文档读不出来，这次回答没用到它们 ——"
                               " 回答可能因此不够准" % len(missed))
            return out
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def delete_doc(self, fname):
        """删除文档"""
        path = safe_join(self.docs_dir, safe_name(fname, default=""))
        if not path or not os.path.isfile(path):
            return {"错误": "文档不存在或路径非法"}
        os.remove(path)
        try:
            from core.fts_index import FTSIndex
            from core.retrieval import HybridRetriever
            FTSIndex(self.workspace_root).delete_source(path)
            HybridRetriever(self.workspace_root).delete_source(path)
        except Exception as e:  # 静默是故意的 - 索引清理失败不回滚文件删除
            _x6_swallowed(__name__, e, "best-effort fallback")
        return {"ok": True}

    @safe
    def read_doc(self, fname):
        """读取文档内容"""
        path = safe_join(self.docs_dir, safe_name(fname, default=""))
        if not path or not os.path.isfile(path):
            return {"错误": "文档不存在或路径非法"}
        try:
            content = open(path, encoding="utf-8").read()
            return {"文件名": os.path.basename(path), "内容": content[:500]}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def clear_all(self):
        """清空所有文档"""
        for f in os.listdir(self.docs_dir):
            os.remove(os.path.join(self.docs_dir, f))
        return {"ok": True}

    @safe
    def stats(self):
        """统计"""
        return {
            "总查询次数": self.query_count,
            "添加次数": self.add_count,
            "文档数": len(os.listdir(self.docs_dir))
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        report = f"""知识问答报告
==========
总查询次数: {s['总查询次数']}
添加次数: {s['添加次数']}
文档数: {s['文档数']}
"""
        return {"报告": report}

    def run(self, *args):
        if args:
            return self.ask(args[0])
        return self.stats()
