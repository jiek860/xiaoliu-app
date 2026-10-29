# calc 边界 fixture

现象：`average([])` 抛 `ZeroDivisionError`。

任务：修复 `calc.py`，空列表返回 0，非空返回平均值。

运行 `py -3 check.py` 应失败；修好后应输出 `ok`。
