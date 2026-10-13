# -*- coding: utf-8 -*-
"""v26-7.1: 天气工具（wttr.in）

TOOLS 是"能力声明"：告诉系统"我能被这样调用"，由 tools/rebuild_modules_repo.py
写进 modules_repo/manifest.json 的 tools 字段（那份清单是 RSA 签名的）。
字段含义见 core/core_caps.py 的说明。
"""
from modules.base import BaseModule
import urllib.request, urllib.parse, json


class Weather(BaseModule):
    NAME = "weather"
    VERSION = "1.0"

    TOOLS = [
        {"name": "weather_now", "method": "get",
         "desc": "查某个城市现在的天气（温度/天气/湿度）",
         "args": {"city": "城市名，如：杭州、北京；不填用默认城市"},
         "readonly": True,
         "hints": ["天气", "气温", "下雨", "温度", "冷不冷", "热不热"]},
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.city = "Chongqing"

    def get(self, city=None):
        city = city or self.city
        try:
            url = "https://wttr.in/%s?format=j1&lang=zh" % urllib.parse.quote(city)
            r = urllib.request.urlopen(url, timeout=10)
            d = json.loads(r.read())
            cur = d["current_condition"][0]
            return {
                "城市": city,
                "温度": cur["temp_C"] + "°C",
                "天气": cur["weatherDesc"][0]["value"],
                "湿度": cur["humidity"] + "%",
            }
        except Exception as e:
            return {"错误": str(e)[:80]}

    def run(self, *a):
        return self.get()
