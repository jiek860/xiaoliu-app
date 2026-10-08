# 小6智能体 架构说明
## 微核设计
核心是Trunk类（core/trunk.py），负责模块注册、懒加载、回复主链路编排、配置读写、日志兜底。所有模块之间不直接互相import，全部通过trunk.call()调用，是星型拓扑，避免模块之间网状耦合。
## 主聊天链路
用户输入 → Trunk.reply()
→ _reply_inner()
→ 优先走pipeline流水线（core/pipeline/）
  1.  并行检索：向量库搜索、记忆卡触发、知识图谱召回
  2.  组装Prompt：人格设定+系统提示+历史对话+检索结果
  3.  模型分发：优先流式调用，失败自动降级非流式
  4.  后处理：群聊消息合并、代码块提取、TTS判断
→ 后台队列异步处理：记忆沉淀、闭环学习、备份
## 模块协议
所有插件在modules/installed/下，格式统一：
- 类名与core/lazy_config.py里登记的一致
- __init__(self, trunk=None)
- 必须实现run()方法作为统一入口
- 可选实现reply()、stats()、get_history()
新增模块直接丢进modules/installed目录，trunk启动时自动扫描注册，不需要手动改代码。
## 数据目录结构
data/
├── config.json          # 全局配置
├── users/<账号名>/       # 每个账号独立的聊天/记忆目录
├── chats.db             # SQLite聊天记录
├── vectors.db           # SQLite向量知识库
├── graph.json            # 知识图谱
├── memory.json           # 长期记忆
├── logs/                 # 所有日志
└── backups/              # 自动备份包
## 配置规则
所有配置统一存在data/config.json，修改后用trunk.save_config()原子写盘，不会写一半损坏。
