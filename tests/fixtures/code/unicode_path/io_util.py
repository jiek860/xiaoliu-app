# -*- coding: utf-8 -*-
def write_text(path, text):
    with open(path, "w", encoding="gbk") as fp:
        fp.write(text)
