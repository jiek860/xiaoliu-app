# -*- coding: utf-8 -*-
"""v26-7.1: 天气工具（wttr.in）"""
from modules.base import BaseModule
import urllib.request, urllib.parse, json


class Weather(BaseModule):
    NAME = "weather"
    VERSION = "1.0"
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
