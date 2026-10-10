# -*- coding: utf-8 -*-
"""P2-04: 任务模板市场 - 预置常用任务模板，一键执行"""
import os, json


# 预置任务模板
PRESET_TEMPLATES = [
    {
        "name": "整理下载文件夹",
        "desc": "按文件类型分类下载文件夹",
        "steps": ["读取下载文件夹", "按扩展名分类", "移动到对应子目录"],
        "tags": ["文件管理"],
    },
    {
        "name": "总结今天做了什么",
        "desc": "汇总今天的聊天记录生成日报",
        "steps": ["读取今天所有聊天记录", "提取关键事项", "生成日报"],
        "tags": ["效率"],
    },
    {
        "name": "备份重要数据",
        "desc": "一键备份data目录到backups",
        "steps": ["调用backup模块", "压缩备份", "报告备份位置"],
        "tags": ["备份"],
    },
    {
        "name": "清理内存",
        "desc": "释放内存，重启未使用的模块",
        "steps": ["查看当前内存占用", "卸载不用的模块", "报告释放了多少"],
        "tags": ["性能"],
    },
    {
        "name": "生成使用统计",
        "desc": "统计程序用了多久、聊了多少轮",
        "steps": ["读取统计数据", "计算使用时长", "生成报告"],
        "tags": ["统计"],
    },
]


class TaskTemplate:
    """任务模板管理"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "task_templates.json")
        self.templates = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        # 默认用预置模板
        return {"templates": PRESET_TEMPLATES}

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.templates, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def list_templates(self, tag=None):
        """列出所有模板，可按标签过滤"""
        ts = self.templates["templates"]
        if tag:
            ts = [t for t in ts if tag in t.get("tags", [])]
        return ts

    def add_template(self, name, desc, steps, tags=None):
        """新增自定义模板"""
        self.templates["templates"].append({
            "name": name,
            "desc": desc,
            "steps": steps,
            "tags": tags or [],
        })
        self._save()

    def delete_template(self, name):
        """删除模板"""
        self.templates["templates"] = [
            t for t in self.templates["templates"] if t["name"] != name
        ]
        self._save()

    def run(self, *a):
        return {"模板数": len(self.templates["templates"])}
