# -*- coding: utf-8 -*-
"""知识问答 v2.1 - RAG知识库 + 文档列表 + 搜索 + 删除 + 清空 + 统计 + 导出"""
import os
from core.safe import safe
from modules.base import BaseModule


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
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.docs_dir = os.path.join(trunk.base if trunk else ".", "data", "knowledge")
        os.makedirs(self.docs_dir, exist_ok=True)
        self.query_count = 0
        self.add_count = 0

    @safe
    def add_doc(self, title, content):
        """添加文档到知识库"""
        fname = title.replace(" ", "_")[:30] + ".txt"
        path = os.path.join(self.docs_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.add_count += 1
        return {"已添加": title}

    @safe
    def list_docs(self):
        """列出所有文档"""
        files = os.listdir(self.docs_dir)
        return {"文档数": len(files), "文档": files}

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
    def ask(self, question):
        """基于知识库回答问题"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}

        # 先搜索相关文档
        relevant = self.search_doc(question)
        context = ""
        missed = []
        for doc in relevant.get("文档", [])[:3]:
            path = os.path.join(self.docs_dir, doc)
            try:
                context += open(path, encoding="utf-8").read()[:500] + "\n"
            except Exception as e:
                # 参考文档读不了，回答质量会下降 —— 要告诉用户，别让他以为
                # "模型就是答不好"。这条以前是 except: pass。
                missed.append("%s（%s）" % (doc, type(e).__name__))

        try:
            r = llm.chat(f"基于以下资料回答问题:\n{context[:1000]}\n\n问题: {question}")
            self.query_count += 1
            out = {"问题": question, "回答": r,
                   "参考文档": relevant.get("文档", [])}
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
        path = os.path.join(self.docs_dir, fname)
        if os.path.exists(path):
            os.remove(path)
            return {"ok": True}
        return {"错误": "文档不存在"}

    @safe
    def read_doc(self, fname):
        """读取文档内容"""
        path = os.path.join(self.docs_dir, fname)
        if not os.path.exists(path):
            return {"错误": "文档不存在"}
        try:
            content = open(path, encoding="utf-8").read()
            return {"文件名": fname, "内容": content[:500]}
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
