# pyqt_form 回调 fixture

现象：表单点“提交”后，回调函数没有被调用。

任务：修复 `form.py`，让 `submit()` 先调用 `self.handler`，再计成功次数。

运行 `py -3 check.py` 应失败；修好后应输出 `ok`。
