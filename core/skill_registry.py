# -*- coding: utf-8 -*-
"""SkillRegistry：统一技能注册表

整合两种来源的技能：
1. zip 包技能（.x6skill）：从 skill_loader 来
2. markdown 捕获技能：从 skill_capture 来

统一提供：
- list_all()：列出所有技能（带来源、启用状态）
- load(name)：加载技能
- enable(name) / disable(name)：启用/禁用
- delete(name)：删除
"""
import json, os


class SkillRegistry:
    def __init__(self, trunk):
        self.trunk = trunk
        self.base = getattr(trunk, "base", ".")
        # 启用/禁用状态存在这里
        self.state_file = os.path.join(self.base, "data", "skill_registry.json")
        self._state = self._load_state()

        # 两种来源的目录
        self.zip_skill_dir = os.path.join(self.base, "data", "skills")
        self.captured_dir = os.path.join(
            self.base, "data", "plugin_data", "skill_capture", "skills")
        self.pending_dir = os.path.join(
            self.base, "data", "plugin_data", "skill_capture", "skills_pending")

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                return json.load(open(self.state_file, encoding="utf-8"))
        except Exception:  # 静默是故意的：状态文件缺失/损坏时回退默认值
            pass
        return {"enabled": [], "disabled": []}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            json.dump(self._state, open(self.state_file, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception:  # 静默是故意的：状态保存失败不阻断技能读写
            pass

    def _scan_dir(self, dir_path, source):
        """扫描目录，返回技能列表"""
        out = []
        if not os.path.isdir(dir_path):
            return out
        for f in os.listdir(dir_path):
            if f.endswith(".md"):
                name = os.path.splitext(f)[0]
                out.append({
                    "name": name,
                    "source": source,
                    "path": os.path.join(dir_path, f),
                    "enabled": name not in self._state.get("disabled", []),
                })
            elif os.path.isdir(os.path.join(dir_path, f)):
                out.append({
                    "name": f,
                    "source": source,
                    "path": os.path.join(dir_path, f),
                    "enabled": f not in self._state.get("disabled", []),
                })
        return out

    def _verify_signature(self, path):
        """本地完整性校验：SHA256 对比；不是远程 RSA 签名。"""
        import hashlib
        if not os.path.isfile(path):
            return True  # 目录型不做单文件完整性校验
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            saved = self._state.get("signatures", {}).get(path)
            if saved is None or not str(saved).startswith("sha256:"):
                self._state.setdefault("signatures", {})[path] = "sha256:" + digest
                self._save_state()
                return True
            return saved == "sha256:" + digest
        except Exception:
            return True

    def list_all(self):
        """列出所有技能（统一格式）"""
        out = []
        # zip 包技能
        out.extend(self._scan_dir(self.zip_skill_dir, "zip"))
        # 已确认的捕获技能
        out.extend(self._scan_dir(self.captured_dir, "captured"))
        # 待确认的捕获技能
        out.extend(self._scan_dir(self.pending_dir, "pending"))
        # 加签名验证结果
        for s in out:
            s["verified"] = self._verify_signature(s.get("path", ""))
        return sorted(out, key=lambda x: x["name"])

    def load(self, name):
        """加载技能：返回 {"prompt": ..., "tools": ...}，禁用的技能返回 None"""
        # 检查是不是被禁用了
        if name in self._state.get("disabled", []):
            return None

        # 先找 zip 包
        zip_path = os.path.join(self.zip_skill_dir, name)
        if os.path.isdir(zip_path):
            prompt_file = os.path.join(zip_path, "prompt.md")
            prompt = open(prompt_file, encoding="utf-8").read() if os.path.exists(prompt_file) else ""
            tools = []
            tools_file = os.path.join(zip_path, "tools.json")
            if os.path.exists(tools_file):
                try:
                    tools = json.load(open(tools_file, encoding="utf-8"))
                except Exception:
                    tools = []
            return {"prompt": prompt, "tools": tools, "source": "zip"}

        # 再找 markdown 捕获技能
        for d in [self.captured_dir, self.pending_dir]:
            md_file = os.path.join(d, name + ".md")
            if os.path.exists(md_file):
                content = open(md_file, encoding="utf-8").read()
                return {"prompt": content, "tools": [], "source": "captured"}

        return None

    def get_enabled_prompts(self):
        """获取所有启用技能的提示词，拼成一段，用来注入到 Agent 系统提示里"""
        all_skills = self.list_all()
        enabled_skills = [s for s in all_skills if s.get("enabled") and s.get("source") != "pending"]
        if not enabled_skills:
            return ""

        parts = ["\n\n## 用户已教会你的技能（请在合适的时候自动运用）："]
        for s in enabled_skills:
            name = s["name"]
            loaded = self.load(name)
            if loaded and loaded.get("prompt"):
                parts.append("\n### 技能：%s\n%s" % (name, loaded["prompt"][:500]))
        return "\n".join(parts)

    def install_from_file(self, file_path):
        """从 .x6skill 文件导入技能（安全解压：路径、数量、体积都校验）"""
        import zipfile, tempfile, shutil
        if not os.path.exists(file_path):
            return {"ok": False, "error": "文件不存在"}
        target_name = os.path.splitext(os.path.basename(file_path))[0]
        if not target_name or target_name in (".", ".."):
            return {"ok": False, "error": "非法技能名"}
        os.makedirs(self.zip_skill_dir, exist_ok=True)
        target_dir = os.path.join(self.zip_skill_dir, target_name)
        tmp_dir = tempfile.mkdtemp(prefix="x6skill_", dir=self.zip_skill_dir)
        try:
            with zipfile.ZipFile(file_path, "r") as z:
                infos = z.infolist()
                if len(infos) > 200:
                    return {"ok": False, "error": "技能包文件过多"}
                total = sum(max(0, int(i.file_size)) for i in infos)
                if total > 5 * 1024 * 1024:
                    return {"ok": False, "error": "技能包解压后超过 5MB"}
                root = os.path.abspath(tmp_dir)
                for info in infos:
                    name = info.filename.replace("\\", "/")
                    if name.startswith("/") or ".." in name.split("/"):
                        return {"ok": False, "error": "技能包包含越界路径"}
                    dest = os.path.abspath(os.path.join(root, *name.split("/")))
                    if not (dest == root or dest.startswith(root + os.sep)):
                        return {"ok": False, "error": "技能包包含越界路径"}
                z.extractall(tmp_dir)
            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir)
            os.replace(tmp_dir, target_dir)
            return {"ok": True, "name": target_name}
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return {"ok": False, "error": str(e)[:200]}

    def export_to_file(self, name, output_path):
        """把技能导出成 .x6skill 文件（zip 包）"""
        import zipfile
        # 找技能路径
        skill_path = None
        for d in [self.zip_skill_dir, self.captured_dir]:
            p = os.path.join(d, name)
            if os.path.isdir(p):
                skill_path = p
                break
            md = p + ".md"
            if os.path.exists(md):
                skill_path = md
                break
        if skill_path is None:
            return {"ok": False, "error": "技能不存在"}
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
                if os.path.isdir(skill_path):
                    # 目录型：把整个目录打进去
                    for root, _dirs, files in os.walk(skill_path):
                        for f in files:
                            full = os.path.join(root, f)
                            arc = os.path.relpath(full, skill_path)
                            z.write(full, arc)
                else:
                    # 单文件型：写成 prompt.md
                    z.write(skill_path, "prompt.md")
            return {"ok": True, "path": output_path}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def enable(self, name):
        """启用技能"""
        if name in self._state.get("disabled", []):
            self._state["disabled"].remove(name)
            if name not in self._state.get("enabled", []):
                self._state.setdefault("enabled", []).append(name)
            self._save_state()
        return {"ok": True}

    def disable(self, name):
        """禁用技能"""
        if name not in self._state.get("disabled", []):
            self._state.setdefault("disabled", []).append(name)
            self._state.setdefault("enabled", []).remove(name) if name in self._state.get("enabled", []) else None
            self._save_state()
        return {"ok": True}

    def delete(self, name):
        """删除技能"""
        # 找在哪里
        for d in [self.zip_skill_dir, self.captured_dir, self.pending_dir]:
            p = os.path.join(d, name)
            if os.path.isdir(p):
                import shutil
                shutil.rmtree(p)
                return {"ok": True}
            md = p + ".md"
            if os.path.exists(md):
                os.remove(md)
                return {"ok": True}
        return {"ok": False, "error": "技能不存在"}

    def run(self, *a):
        """标准入口"""
        return {"ok": True, "skills": self.list_all()}
