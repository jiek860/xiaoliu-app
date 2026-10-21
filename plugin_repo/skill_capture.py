# -*- coding: utf-8 -*-
"""技能捕获 v2.0 - 成功任务自动存技能 + 确认 + 搜索 + 历史 + 统计"""
import os, time, re
from core.safe import safe
from modules.base import BaseModule


class SkillCapture(BaseModule):
    NAME = "skill_capture"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        # v2.1: 插件持久化必须落在 data/plugin_data/<插件名>/ 内
        os.makedirs(os.path.join(self.base, "data", "plugin_data", "skill_capture"), exist_ok=True)
        self.skill_dir = os.path.join(self.base, "data", "plugin_data", "skill_capture", "skills")
        self.pending_dir = os.path.join(self.base, "data", "plugin_data", "skill_capture", "skills_pending")
        for _old, _new in ((os.path.join(self.base, "data", "skills"), self.skill_dir),
                           (os.path.join(self.base, "data", "skills_pending"), self.pending_dir)):
            if not os.path.exists(_new) and os.path.isdir(_old):
                try: os.rename(_old, _new)
                except OSError:  # 静默是故意的：旧目录迁移失败不阻断主流程
                    pass
        os.makedirs(self.skill_dir, exist_ok=True)
        os.makedirs(self.pending_dir, exist_ok=True)
        self.history = []
        self.capture_count = 0

    @safe
    def capture(self, task="", result="", success=True, confirm=False):
        """从成功任务提取技能"""
        if not success or not task:
            return {"记录": "失败任务不沉淀"}

        name = re.sub(r'[^\w]', '_', task[:20])[:30]
        target_dir = self.skill_dir if confirm else self.pending_dir
        skill_file = os.path.join(target_dir, f"{name}.md")

        skill_content = f"""---
name: {name}
created: {time.strftime('%Y-%m-%d %H:%M')}
trigger: {task[:50]}
status: {"正式" if confirm else "待确认"}
---
# 技能: {task}

## 怎么做
{result[:200]}
"""
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(skill_content)

        self.capture_count += 1
        self.history.append({"task": task[:40], "时间": time.strftime("%m-%d %H:%M")})
        if len(self.history) > 30:
            self.history = self.history[-30:]

        return {"已存技能" if confirm else "待确认": name}

    @safe
    def confirm_skill(self, name):
        """确认技能"""
        pending = os.path.join(self.pending_dir, f"{name}.md")
        if os.path.exists(pending):
            import shutil
            shutil.move(pending, os.path.join(self.skill_dir, f"{name}.md"))
            return {"已确认": name}
        return {"错误": "技能不存在"}

    @safe
    def reject_skill(self, name):
        """拒绝技能"""
        pending = os.path.join(self.pending_dir, f"{name}.md")
        if os.path.exists(pending):
            os.remove(pending)
            return {"已拒绝": name}
        return {"错误": "技能不存在"}

    @safe
    def list_pending(self):
        """列出待确认技能"""
        files = os.listdir(self.pending_dir)
        return {"待确认技能": files}

    @safe
    def search_skill(self, query):
        """搜索技能"""
        results = []
        for f in os.listdir(self.skill_dir):
            if query in f:
                results.append(f)
        return results

    @safe
    def get_history(self, count=10):
        """获取捕获历史"""
        return {"历史": self.history[-count:]}

    @safe
    def stats(self):
        """统计"""
        return {
            "总捕获次数": self.capture_count,
            "已存技能数": len(os.listdir(self.skill_dir)),
            "待确认数": len(os.listdir(self.pending_dir))
        }

    def run(self, *args):
        return self.stats()

    @safe
    def get_skill_detail(self, name):
        """获取技能详情"""
        path = os.path.join(self.skill_dir, f"{name}.md")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return {"名称": name, "内容": f.read()}
        return {"错误": "技能不存在"}

    @safe
    def delete_skill(self, name):
        """删除技能"""
        path = os.path.join(self.skill_dir, f"{name}.md")
        if os.path.exists(path):
            os.remove(path)
            return {"成功": True}
        return {"错误": "技能不存在"}

    @safe
    def list_all_skills(self):
        """列出所有技能"""
        files = os.listdir(self.skill_dir)
        return {"技能数": len(files), "技能": files}
