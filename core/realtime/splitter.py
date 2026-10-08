# -*- coding: utf-8 -*-
"""流式分句器：喂token吐句子"""
class SentenceSplitter:
    END = set("。！？!?；;\n")
    SOFT = set("，,")
    MAX_LEN = 100

    def __init__(self):
        self.buf = ""
        self._in_code = False

    def feed(self, token):
        out = []
        self.buf += token
        while "```" in self.buf:
            idx = self.buf.index("```")
            head = self.buf[:idx]
            if head: out += self._split_head(head, consume=False)
            self._in_code = not self._in_code
            self.buf = self.buf[idx+3:]
        if self._in_code:
            while "\n" in self.buf:
                i = self.buf.index("\n")
                seg = self.buf[:i].strip()
                if seg: out.append(seg)
                self.buf = self.buf[i+1:]
            return out
        out += self._split_head(self.buf, consume=True)
        return out

    def _split_head(self, text, consume=False):
        out = []; start = 0
        for i, ch in enumerate(text):
            if ch in self.END:
                seg = text[start:i+1].strip()
                if seg: out.append(seg)
                start = i+1
        if consume:
            self.buf = text[start:]
            while len(self.buf) > self.MAX_LEN:
                cut = -1
                for j in range(self.MAX_LEN-1, self.MAX_LEN//2, -1):
                    if j < len(self.buf) and self.buf[j] in self.SOFT:
                        cut = j; break
                if cut < 0: cut = self.MAX_LEN
                seg = self.buf[:cut+1].strip()
                if seg: out.append(seg)
                self.buf = self.buf[cut+1:]
        return out

    def flush(self):
        s = self.buf.strip(); self.buf = ""; self._in_code = False
        return [s] if s else []
