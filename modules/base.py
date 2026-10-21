# -*- coding: utf-8 -*-
"""模块基类 - 所有功能模块的父类，提供通用方法
减少重复代码：stats / export_report / run
"""
import time

try:
    from core.plugin_api import PLUGIN_API_VERSION
except ImportError:  # 独立加载 modules.base 时保持可用
    PLUGIN_API_VERSION = "1.0"


try:
    from core.module_lifecycle import LifecycleMixin, ModuleLifecycle
except ImportError:  # 独立加载 modules.base 时保持可用
    LifecycleMixin = object
    ModuleLifecycle = None


class BaseModule(LifecycleMixin):
    """所有功能模块的基类。

    新增（2026-10-21，对齐模块级程序标准 4.1/4.2/6.4）：
      * ``start()`` / ``stop()`` / ``health()`` 生命周期契约（幂等）
      * ``close()`` / ``shutdown()`` 作为 ``stop()`` 的别名
      * 子类只需覆盖 ``_on_start`` / ``_on_stop``，不必自己管状态机

    兼容性：历史模块只实现 ``run()``，不写 ``_on_start/_on_stop`` 也照常工作。
    """

    NAME = "未命名模块"
    VERSION = "1.0"
    PLUGIN_API_VERSION = PLUGIN_API_VERSION
    # 标准 1.1：模块不负责什么（子类可覆盖，便于调用方判断边界）
    NOT_RESPONSIBLE = ()

    def __init__(self, trunk=None):
        self.trunk = trunk
        self._count = 0  # 调用次数
        self._history = []  # 历史记录
        self._start_time = time.time()
        if ModuleLifecycle is not None:
            self.lifecycle = ModuleLifecycle(self.NAME)

    def stats(self):
        """统计信息（子类可覆盖）。标准 6.4：健康/指标出口。"""
        out = {
            "模块": self.NAME,
            "版本": self.VERSION,
            "调用次数": self._count,
            "运行时长": "%.1f秒" % (time.time() - self._start_time),
        }
        try:
            out.update(self.health())
        except Exception:  # 静默是故意的：健康信息取不到不该影响 stats
            pass
        return out

    def describe(self):
        """标准 1.1：职责与边界声明。"""
        return {
            "name": self.NAME,
            "version": self.VERSION,
            "purpose": (self.__doc__ or "").strip().splitlines()[0]
            if self.__doc__ else "",
            "not_responsible": list(getattr(self, "NOT_RESPONSIBLE", ()) or ()),
        }

    def export_report(self):
        """导出报告（子类可覆盖）"""
        s = self.stats()
        lines = ["%s 报告" % self.NAME, "=" * 30]
        for k, v in s.items():
            lines.append("%s: %s" % (k, v))
        return {"报告": "\n".join(lines)}

    def clear_history(self):
        """清空历史"""
        self._history.clear()
        return {"ok": True}

    def get_history(self, count=10):
        """获取历史"""
        return {"历史": self._history[-count:]}

    def run(self, *args):
        """入口方法（子类覆盖）"""
        self._count += 1
        if args:
            return {"结果": str(args[0])}
        return self.stats()

    def _add_history(self, item):
        """添加历史记录"""
        self._history.append({
            "time": time.strftime("%H:%M:%S"),
            "item": item
        })
        # 最多保留100条
        if len(self._history) > 100:
            self._history = self._history[-100:]
