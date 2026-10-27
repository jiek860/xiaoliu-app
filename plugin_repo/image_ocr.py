# -*- coding: utf-8 -*-
"""图片识别 v2.1 - OCR文字识别 + 历史记录 + 可用性检查 + 统计 + 清空 + 导出"""
import os, time
from core.safe import safe
from modules.base import BaseModule


class OCR(BaseModule):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "image_ocr"
    VERSION = "1.0"

    TOOLS = [
        {
         "contract": {
             "params": {},
             "returns": {"type": "object"},
             "description": "检查图片识别功能能不能用（依赖可选组件）",
         },
         "name": "ocr_available", "method": "available",
         "desc": "检查图片识别功能能不能用（依赖可选组件）",
         "args": {},
         "readonly": True,
         "hints": ["ocr能用吗", "图片识别能用吗"]},
        {
         "contract": {
             "params": {
                 "image_path": {"type": "string"}
             },
             "returns": {"type": "object"},
             "description": "识别一张图片里的文字",
         },
         "name": "ocr_read", "method": "recognize",
         "desc": "识别一张图片里的文字",
         "args": {"image_path": "图片路径，如 D:\\截图.png"},
         "hints": ["识别图片", "图片文字", "提取文字", "ocr", "截图识字"]},
        {
         "contract": {
             "params": {
                 "count": {"type": "integer"}
             },
             "returns": {"type": "object"},
             "description": "以前识别过哪些图片",
         },
         "name": "ocr_history", "method": "get_history",
         "desc": "以前识别过哪些图片",
         "args": {"count": "看几条，默认 10"},
         "readonly": True,
         "hints": ["识别历史", "以前识别的图片"]},
    ]
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.history = []
        self.ocr_count = 0

    @safe
    def recognize(self, image_path):
        """识别图片中的文字（GLM-4V多模态直连）"""
        if not os.path.exists(image_path):
            return {"错误": "图片不存在"}
        try:
            import base64, requests
            # 读图片转base64
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            # 读云端配置
            cfg = self.trunk.config
            api_key = cfg.get("cloud_api_key", "")
            url = cfg.get("cloud_url", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
            model = cfg.get("cloud_model", "glm-4v-flash")
            if not api_key:
                return {"错误": "未配置云端API Key"}
            # 构造GLM-4V多模态请求
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请识别这张截图里的所有文字，原样输出，不要解释"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
                    ]
                }],
                "stream": False
            }
            r = requests.post(url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload, timeout=30)
            ans = r.json()
            text = ans["choices"][0]["message"]["content"].strip()
            self.ocr_count += 1
            self.history.append({
                "图片": image_path,
                "识别文字": text[:100],
                "时间": time.strftime("%m-%d %H:%M")
            })
            if len(self.history) > 20:
                self.history = self.history[-20:]
            return {"图片": image_path, "文字": text}
        except Exception as e:
            return {"错误": str(e)[:120]}

    @safe
    def batch_recognize(self, image_paths):
        """批量识别图片"""
        results = []
        for p in image_paths[:5]:
            r = self.recognize(p)
            results.append(r)
        return {"处理数": len(results), "结果": results}

    @safe
    def get_history(self, count=10):
        """获取识别历史"""
        return {"历史": self.history[-count:]}

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.ocr_count = 0
        return {"ok": True}

    @safe
    def available(self):
        """检查是否可用"""
        llm = self.trunk.modules.get("llm")
        return {"可用": llm is not None}

    @safe
    def search_text(self, keyword):
        """在历史中搜索文字"""
        found = [h for h in self.history if keyword in h.get("识别文字", "")]
        return {"找到": len(found), "结果": found}

    @safe
    def stats(self):
        """统计"""
        return {
            "总识别次数": self.ocr_count,
            "历史数": len(self.history)
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        report = f"""图片识别报告
==========
总识别次数: {s['总识别次数']}
历史数: {s['历史数']}
"""
        return {"报告": report}

    def run(self, *args):
        if args:
            return self.recognize(args[0])
        return self.stats()

    @safe
    def get_image_info(self, image_path):
        """获取图片信息"""
        if not os.path.exists(image_path):
            return {"错误": "图片不存在"}
        size = os.path.getsize(image_path)
        return {"图片": image_path, "大小KB": size // 1024}

    @safe
    def compare_images(self, img1, img2):
        """比较两张图片"""
        return {"比较": "需要多模态模型支持"}

    @safe
    def get_accuracy(self):
        """识别准确率"""
        return {"准确率": "需要人工标注对比"}
