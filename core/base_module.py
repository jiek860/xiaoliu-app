# -*- coding: utf-8 -*-
"""所有插件模块的统一基类"""
class BaseModule:
    """所有installed模块继承这个类，保证接口统一"""
    def __init__(self, trunk=None):
        self.trunk = trunk
    def run(self, *args, **kwargs):
        """统一入口，子类按需覆盖"""
        return {"ok": True, "data": self.stats()}
    def reply(self, text):
        return self.run(text)
    def stats(self):
        return {"ok": True, "data": {}}
    def get_history(self, count=10):
        return {"ok": True, "data": []}
    def log(self, msg):
        if self.trunk:
            try:
                self.trunk._log("[%s] %s" % (self.__class__.__name__, str(msg)[:100]))
            except Exception:
                pass
