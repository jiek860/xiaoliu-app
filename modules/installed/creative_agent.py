# -*- coding: utf-8 -*-
"""创作Agent v2.1 - AI画图 + 多种风格 + 历史记录 + 风格列表 + 尺寸列表 + 清空 + 统计"""
import urllib.request, urllib.parse, os, time, sys
from core.safe import safe
from modules.base import BaseModule


class 创作Agent(BaseModule):
    NAME = "creative_agent"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.save_dir = os.path.join(trunk.base if trunk else ".", "data", "media")
        os.makedirs(self.save_dir, exist_ok=True)
        self.history = []
        self.draw_count = 0
        self.styles = ["卡通", "写实", "油画", "动漫", "水彩", "像素风"]
        self.sizes = ["1024x1024", "1920x1080", "1080x1920", "512x512"]

    @safe
    def 画图(self, prompt, size="1024x1024", style=None):
        """AI画图"""
        if style == "卡通": prompt = "cartoon style, " + prompt
        elif style == "写实": prompt = "realistic photo, " + prompt
        elif style == "油画": prompt = "oil painting, " + prompt
        elif style == "动漫": prompt = "anime style, " + prompt
        elif style == "水彩": prompt = "watercolor, " + prompt
        elif style == "像素风": prompt = "pixel art, " + prompt

        w, h = size.split("x")
        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt) + "?width=%s&height=%s&nologo=true" % (w, h)

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=90).read()
            fname = "img_%d.png" % int(time.time())
            path = os.path.join(self.save_dir, fname)
            open(path, "wb").write(data)

            # 记录历史
            self.draw_count += 1
            self.history.append({
                "提示词": prompt,
                "路径": path,
                "风格": style,
                "尺寸": size,
                "时间": time.strftime("%m-%d %H:%M")
            })
            if len(self.history) > 20:
                self.history = self.history[-20:]

            return {"ok": True, "路径": path, "提示词": prompt, "尺寸": size}
        except Exception as e:
            return {"ok": False, "错误": str(e)[:80]}

    @safe
    def 列出风格(self):
        """列出支持的风格"""
        return self.styles

    @safe
    def 列出尺寸(self):
        """列出支持的尺寸"""
        return self.sizes

    @safe
    def 历史(self, count=10):
        """获取画图历史"""
        return {"历史": self.history[-count:]}

    @safe
    def 统计(self):
        """统计"""
        return {
            "总画图次数": self.draw_count,
            "风格数": len(self.styles),
            "尺寸数": len(self.sizes),
            "历史数": len(self.history)
        }

    @safe
    def 清空历史(self):
        """清空历史"""
        self.history = []
        self.draw_count = 0
        return {"ok": True}

    @safe
    def 删除图片(self, fname):
        """删除图片"""
        path = os.path.join(self.save_dir, fname)
        if os.path.exists(path):
            os.remove(path)
            return {"ok": True}
        return {"错误": "图片不存在"}

    def run(self, query=""):
        if not query:
            return self.统计()
        if any(k in query for k in ("画", "画图", "生成图", "画一张", "画个", "帮我画")):
            for k in ("画一张", "画一个", "画只", "画条", "画个", "画"):
                if k in query:
                    prompt = query.split(k, 1)[1].strip()
                    break
            else:
                prompt = query
            r = self.画图(prompt)
            if r["ok"]:
                return "🎨 已画好: " + r["路径"]
            return "画图失败: " + r.get("错误", "")
        return "说'画一只猫'就画图"
