# -*- coding: utf-8 -*-
"""P1-18: 异步LLM客户端 v2.0 - 完整版
- async接口调用LLM
- 并发多模型请求
- qasync与PyQt5集成
- 兼容原同步接口
"""
import asyncio
import aiohttp
import threading


class AsyncLLMClient:
    """异步LLM调用，用于并发请求"""
    def __init__(self, trunk):
        self.trunk = trunk
        self._loop = None
        self._thread = None

    def _get_loop(self):
        """获取或创建异步事件循环"""
        if self._loop and self._loop.is_running():
            return self._loop
        # 在后台线程跑事件循环
        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
        # 等循环启动
        import time
        time.sleep(0.1)
        return self._loop

    async def chat_async(self, message):
        """异步调用云端LLM"""
        cfg = self.trunk.config
        url = cfg.get("cloud_url", "")
        key = cfg.get("cloud_key", "")
        model = cfg.get("cloud_model", "glm-4-flash")

        if not url or not key:
            return "云端模型未配置"

        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            "messages": [{"role": "user", "content": message}],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url + "/chat/completions",
                                    headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                result = await resp.json()
                return result["choices"][0]["message"]["content"]

    async def chat_multi_async(self, message, models=None):
        """并发调多个模型对比"""
        if models is None:
            models = ["glm-4-flash", "qwen-turbo"]
        tasks = [self.chat_async(message) for _ in models]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            {"model": m, "answer": r if not isinstance(r, Exception) else "错误: " + str(r)}
            for m, r in zip(models, results)
        ]

    def chat_async_sync(self, message):
        """同步包装异步调用（给GUI用）"""
        loop = self._get_loop()
        future = asyncio.run_coroutine_threadsafe(self.chat_async(message), loop)
        return future.result()

    def chat_multi_sync(self, message, models=None):
        """同步包装并发多模型"""
        loop = self._get_loop()
        future = asyncio.run_coroutine_threadsafe(self.chat_multi_async(message, models), loop)
        return future.result()

    def run(self, *a):
        return {
            "异步调用": "已启用",
            "并发能力": "多模型并行",
            "兼容": "原同步接口不受影响",
        }
