# -*- coding: utf-8 -*-
"""P1-3: .x6skill 技能包加载器

技能包格式：一个 zip 文件，扩展名 .x6skill
  prompt.md   - 技能提示词
  tools.json  - 工具声明（可选）
  icon.png    - 图标（可选）

用法：
  loader = SkillLoader(trunk)
  loader.install("path/to/my_skill.x6skill")
  skill = loader.load("my_skill")
  prompt = skill["prompt"]
  tools = skill["tools"]
"""
import json, os, zipfile, shutil


class SkillLoader:
    def __init__(self, trunk):
        self.trunk = trunk
        self.base = getattr(trunk, "base", ".")
        self.skill_dir = os.path.join(self.base, "data", "skills")
        os.makedirs(self.skill_dir, exist_ok=True)
        self._cache = {}

    def install(self, x6skill_path):
        """安装一个 .x6skill 包"""
        if not os.path.exists(x6skill_path):
            return {"ok": False, "error": f"文件不存在: {x6skill_path}"}
        name = os.path.splitext(os.path.basename(x6skill_path))[0]
        target = os.path.join(self.skill_dir, name)
        if os.path.exists(target):
            shutil.rmtree(target)
        os.makedirs(target)
        try:
            with zipfile.ZipFile(x6skill_path) as z:
                z.extractall(target)
            return {"ok": True, "name": name, "path": target}
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}

    def list_skills(self):
        """列出所有已安装技能"""
        out = []
        if not os.path.isdir(self.skill_dir):
            return out
        for d in os.listdir(self.skill_dir):
            p = os.path.join(self.skill_dir, d)
            if os.path.isdir(p):
                out.append(d)
        return out

    def load(self, name):
        """加载技能：返回 {"prompt": ..., "tools": ...}"""
        if name in self._cache:
            return self._cache[name]
        skill_path = os.path.join(self.skill_dir, name)
        if not os.path.isdir(skill_path):
            return None
        # 读 prompt.md
        prompt = ""
        prompt_file = os.path.join(skill_path, "prompt.md")
        if os.path.exists(prompt_file):
            prompt = open(prompt_file, encoding="utf-8").read()
        # 读 tools.json
        tools = []
        tools_file = os.path.join(skill_path, "tools.json")
        if os.path.exists(tools_file):
            try:
                tools = json.load(open(tools_file, encoding="utf-8"))
            except Exception:
                tools = []
        result = {"prompt": prompt, "tools": tools, "path": skill_path}
        self._cache[name] = result
        return result

    def uninstall(self, name):
        """卸载技能"""
        path = os.path.join(self.skill_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
            self._cache.pop(name, None)
            return {"ok": True}
        return {"ok": False, "error": "技能不存在"}