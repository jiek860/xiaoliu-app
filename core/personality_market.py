# -*- coding: utf-8 -*-
"""P2-09: 人格市场 - 导出/导入人格包"""
import os, json, zipfile


class PersonalityMarket:
    """人格包分享"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def export_personality(self, out_path):
        """导出人格包（人格+记忆+设置）"""
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            # 人格
            p_path = os.path.join(self.base, "data", "personality.json")
            if os.path.exists(p_path):
                z.write(p_path, "personality.json")
            # 记忆卡
            m_path = os.path.join(self.base, "data", "memory_cards.jsonl")
            if os.path.exists(m_path):
                z.write(m_path, "memory_cards.jsonl")
            # 说明
            z.writestr("说明.txt", "小6人格包，导入后覆盖当前人格")
        return {"ok": True, "path": out_path}

    def import_personality(self, zip_path, overwrite=True):
        """导入人格包"""
        if not os.path.exists(zip_path):
            return {"ok": False, "error": "文件不存在"}
        if not overwrite:
            return {"ok": False, "error": "不覆盖模式暂未实现"}
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(os.path.join(self.base, "data"))
            return {"ok": True, "msg": "人格导入完成，重启生效"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}

    def run(self, *a):
        return {"功能": "人格导出/导入"}
