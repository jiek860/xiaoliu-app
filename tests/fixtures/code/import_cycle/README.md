# import_cycle 循环导入 fixture

现象：`import a` 时因为 `a` 与 `b` 互相导入而失败。

任务：修复导入关系（例如把公共常量移到独立模块或延迟导入），保持 `a.VALUE == 1`、`a.run() == 2`。

运行 `py -3 check.py` 应失败；修好后应输出 `ok`。
