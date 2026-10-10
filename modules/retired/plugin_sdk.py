# -*- coding: utf-8 -*-
"""P2-12: 插件开发SDK - 插件模板生成器"""
import os


PLUGIN_TEMPLATE = '''# -*- coding: utf-8 -*-
"""插件: {name}
描述: {desc}
作者: {author}
"""


class {Class}:
    def __init__(self, trunk=None):
        self.trunk = trunk

    def run(self, *args):
        return {{"插件": "{name}", "状态": "运行中"}}
'''


class PluginSDK:
    """插件开发工具"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def create_plugin(self, name, desc="", author="me"):
        """生成新插件模板"""
        dir_name = name.lower().replace(" ", "_")
        plugin_dir = os.path.join(self.base, "modules", "installed", dir_name)
        os.makedirs(plugin_dir, exist_ok=True)

        class_name = "".join(w.capitalize() for w in dir_name.split("_"))

        code = PLUGIN_TEMPLATE.format(
            name=name,
            desc=desc,
            author=author,
            Class=class_name,
        )

        init_path = os.path.join(plugin_dir, "__init__.py")
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(code)

        return {"ok": True, "path": init_path, "类名": class_name}

    def list_plugins(self):
        """列出所有插件"""
        plugin_dir = os.path.join(self.base, "modules", "installed")
        return [d for d in os.listdir(plugin_dir) if os.path.isdir(os.path.join(plugin_dir, d))]

    def run(self, *a):
        return {"插件数": len(self.list_plugins())}
