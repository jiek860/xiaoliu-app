# -*- coding: utf-8 -*-
"""知识问答 v2.1 - RAG知识库 + 文档列表 + 搜索 + 删除 + 清空 + 统计 + 导出"""
import sys, os, time
from core.safe import safe
from modules.base import BaseModule


class KnowledgeQnA(BaseModule):
    NAME = "knowledge_qa"
    VERSION = "1.0"
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
        for f in os.listdir(self.docs_dir):
            path = os.path.join(self.docs_dir, f)
            try:
                content = open(path, encoding="utf-8").read()
                if keyword in content:
                    results.append(f)
            except: pass
        return {"找到": len(results), "文档": results}

    @safe
    def ask(self, question):
        """基于知识库回答问题"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}

        # 先搜索相关文档
        relevant = self.search_doc(question)
        context = ""
        for doc in relevant.get("文档", [])[:3]:
            path = os.path.join(self.docs_dir, doc)
            try:
                context += open(path, encoding="utf-8").read()[:500] + "\n"
            except: pass

        try:
            r = llm.chat(f"基于以下资料回答问题:\n{context[:1000]}\n\n问题: {question}")
            self.query_count += 1
            return {"问题": question, "回答": r, "参考文档": relevant.get("文档", [])}
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
