# -*- coding: utf-8 -*-
"""延迟统计：P50/P95"""
import time

class Metrics:
    def __init__(self):
        self._rounds = {}
        self._data = {"asr": [], "first_token": [], "first_play": [], "total": []}

    def start_round(self, rid):
        self._rounds[rid] = {"t0": time.time()}

    def mark(self, rid, key):
        if rid in self._rounds:
            self._rounds[rid][key] = time.time()

    def end_round(self, rid):
        if rid not in self._rounds: return
        r = self._rounds[rid]
        t0 = r.get("t0")
        if not t0: return
        if "t1" in r: self._data["asr"].append(r["t1"] - t0)
        if "t2" in r: self._data["first_token"].append(r["t2"] - t0)
        if "t3" in r: self._data["first_play"].append(r["t3"] - t0)
        if "t4" in r: self._data["total"].append(r["t4"] - t0)
        del self._rounds[rid]

    def _p(self, lst, p):
        if not lst: return 0
        lst = sorted(lst)
        i = int(len(lst) * p)
        return round(lst[min(i, len(lst)-1)], 2)

    def stats(self):
        out = {"轮数": len(self._data["total"])}
        for k, key in [("asr", "ASR秒"), ("first_token", "首token秒"),
                       ("first_play", "首句播秒"), ("total", "整轮秒")]:
            lst = self._data[k]
            if lst:
                out[key] = {"p50": self._p(lst, 0.5), "p95": self._p(lst, 0.95)}
        return out

    def reset(self):
        self._rounds.clear()
        for k in self._data: self._data[k] = []
