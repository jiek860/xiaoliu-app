# 小6智能助手 · API 文档

## 核心类

### Trunk（躯干）
```python
from core.trunk import Trunk
t = Trunk()

# 回复
reply = t.reply("你好")

# 调用模块结果 = t.call("模块名", "方法名", 参数)
result = t.call("deep_search", "search", "今天天气")

# 读配置
value = t.get_cfg("model_mode", "默认值")

# 获取LLM
llm = t.get_llm()
```

## 模块列表

| 模块名 | 说明 | 主要方法 |
|---|---|---|
| l45_personality | 人格引擎 | mood(), feel() |
| deep_search | 深度搜索 | search(query) |
| code_runner | 代码执行 | run(code) |
| memory_loop | 记忆闭环 | remember(), recall() |
| self_heal | 自愈闭环 | diagnose(), fix() |
| six_loops | 六大闭环 | error_loop(), performance_loop() |
| agent_loop | Agent闭环 | plan_steps(), execute_step() |
| tts | 文字转语音 | speak(text) |
| ocr | 图片识别 | recognize(path) |
| translate | 翻译 | translate(text) |

## 配置文件

config.json 字段：
- model_mode: 本地路由/云端
- local_model: 本地模型名
- cloud_model: 云端模型名
- ollama_url: Ollama地址
- search_cache_sec: 搜索缓存秒数
- agent_max_steps: Agent最大步数

## 写新模块

1. 在 modules/installed/ 新建 你的模块.py
2. 继承 trunk
3. 实现 run() 方法
4. 在 core/lazy_config.py 注册
