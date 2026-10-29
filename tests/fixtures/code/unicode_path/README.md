# unicode_path 编码 fixture

现象：写中文内容到中文文件名后，用 UTF-8 读回来是乱码/解码失败。

任务：修复 `io_util.py`，统一使用 UTF-8。

运行 `py -3 check.py` 应失败；修好后应输出 `ok`。
