# -*- coding: utf-8 -*-
"""新手教程窗口 - 详细版（设置 -> 系统 -> 新手教程，或 Ctrl+K 搜「教程」）"""
import os
import webbrowser

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QPlainTextEdit)

TEXT = """小6智能体 - 使用详细教程
============================================================

【零、兼容性速查（先看这个）】
  - Windows 10 / 11：主支持环境
  - Windows 7 / 8：不建议；Windows Server：部分功能可运行，不是主要目标
  - macOS / Linux：聊天和部分文件功能可能可用，但电脑控制、窗口操作、
    截图、剪贴板等桌面 Agent 能力基本不可用
  - Python 3.10 / 3.11 / 3.12：代码目标兼容，CI 会跑 Windows 兼容矩阵
  - Python 3.9 及以下：不支持；Python 3.13：尚未验证
  - 旧数据：启动时自动检查 data/_schema.json，先备份到
    data/_migrations/，再按 v0 -> v1 -> v2 逐级迁移；失败不会静默覆盖
  - 插件：只接受签名且 api_version 兼容的模块；第三方插件禁止依赖
    core 私有实现，只能用公开 API（当前插件 API v1.0）

【一、第一次用：3 步】
  1) 登录 / 激活
     启动后会弹登录框。
     - 有激活码：点「激活」-> 输入账号名 + 激活码
     - 已激活过：直接输入账号名登录
     - 一个激活码只能激活一个账号

  2) 配模型（唯一必须做的一步）
     - 本地（免费、断网可用）
         装 Ollama（下方有下载按钮）-> 设置 -> 模型 -> 检测本地模型
     - 云端（效果更好、按量付费）
         设置 -> 模型 -> 配置云端模型
         先选「服务商」：OpenAI / Anthropic / Gemini / OpenRouter /
         Azure OpenAI / LM Studio / llama.cpp / vLLM / 自定义
         地址和模型会自动带出；Azure 还要填 deployment 和 API version
     - 左下角两个小圆点是状态灯：本地模型 / 云端模型
     - 想看 Token、延迟和估算费用：Ctrl+K 搜「用量成本」

  3) 开始聊天
     底部输入框打字：
         Enter        发送
         Shift+Enter  换行

============================================================

【二、主界面怎么看】
  - 左侧栏
      新建对话 / 历史对话列表 / 模块（装了才显示）
      / 设置 / 登录 / 清空聊天
  - 中间
      聊天记录区（支持 Markdown、代码块高亮）
  - 底部
      输入框 + 一行按钮：
      + 附件 / 语音输入 / 实时对话 / 模型切换 / 代码编辑器 / 发送
  - 右上角内容区
      「?」按钮（如果这个版本有）或 设置 -> 系统 -> 新手教程

============================================================

【三、命令面板 Ctrl+K（最先要记住的功能）】
  按 Ctrl+K 打开一个搜索框，输入几个字就能找到全部能力：
      - 直接执行：查天气 / 识别图片 / 整理记忆 / 加待办 / 统计报表 ...
      - 打开面板：历史记录 / 日志 / 系统自检 / 任务中心 / 安全中心 / 数据统计 ...
      - 输入「反馈」可以给开发者留言
      - 输入「教程」可以重新打开本教程

  为什么没有一堆按钮：
      按钮太多会占满屏幕，而且模块一改还得手工维护。
      命令面板的条目来自模块自己的能力声明 -- 装了新插件会自动出现。

  如果 Ctrl+K 没反应：
      设置 -> 工具 -> 「命令面板」按钮，同样能打开。

============================================================

【四、它能干什么（举例）】
  - 聊天 / 写作 / 翻译 / 写代码 / 改代码
  - 电脑控制：打开软件、找文件、操作窗口
       设置 -> 工具 -> 电脑控制（危险操作会弹窗确认）
  - 浏览器：直接说「帮我打开 xxx」「搜一下 xxx」
  - 记忆：它会记住你说过的事
       设置 -> 记录 -> 记忆可视化（可查看 / 编辑）
  - 语音：
       底部「语音输入」= 说一句转成文字
       底部「实时对话」= 连续多轮语音对话，可随时打断
  - 代码编辑器：底部「代码编辑器」，多标签 / 运行 / AI 修复
  - 图片：把截图或图片发给它，能识别内容
  - 群聊 / 辩论：让它几个「角色」一起讨论
  - 插件 / MCP：设置 -> 扩展，扩展额外能力
      插件 API v1.0：只装带签名、清单 api_version 兼容的插件；
      第三方插件不能用 core 私有模块，违规包会被拒绝安装
  - 数据统计 / 模块星图 / 桌宠：设置 -> 记录 / 工具

============================================================

【五、设置里有什么】
  模型   模型模式、本地/云端配置、服务商选择、能力预览、用量成本
  界面   字号、主题
  工具   电脑控制、机器人、语音、日历、命令面板、模块星图
  扩展   插件市场（检查更新/更新/回滚）、MCP
  记录   历史、日志、搜索、记忆、统计、RAG 知识库
  团队   用户/角色、集中配置、审计导出（Ctrl+K 搜「团队管理」）
  系统   安全中心、任务中心、自检、首次向导、新手教程、检查更新、意见反馈

============================================================

【六、出问题了怎么办】
  - 某个功能没反应
      设置 -> 记录 -> 日志，看最近的 error
  - 想给开发者报问题
      设置 -> 系统 -> 意见反馈（或 Ctrl+K 搜「反馈」）
      也可以：日志中心 -> 导出日志包，把生成的 zip 发过来
  - 程序崩了 / 卡死
      data/logs/faulthandler.log  全部线程的 Python 栈
      data/logs/crashes.log       Python 层异常
  - 「它记不住事」
      data/vectors.db + 设置 -> 记录 -> 记忆可视化
  - 旧数据迁移失败 / 数据版本警告
      设置 -> 系统 -> 深度自检；看 data/logs/trunk.log。
      迁移前备份在 data/_migrations/backup_*，不会自动删原数据。
      开发机可先预演：py -3 tools/migrate_data.py --dry-run

============================================================

【七、新功能入口（2026-10-20）】
  - 模型服务商：设置 -> 模型 -> 配置云端模型，支持 8 类后端
  - 模型能力/成本：Ctrl+K 搜「用量成本」或「模型用量」
  - RAG 知识库：Ctrl+K 搜「RAG管理」
      可导入文件/目录、设置 ACL 角色、检索并查看引用页码和 offset
  - 团队/多用户：Ctrl+K 搜「团队管理」或「多用户」
      可添加用户、设置 owner/admin/editor/viewer/auditor、保存集中配置、导出审计
  - 插件更新：插件市场 -> 检查更新
      兼容更新可一键应用，更新前自动保留回滚副本；单插件可回滚
  - 电脑 Agent：失败重试时会显示修复计划（刷新界面、滚动、换定位源等）
  - 注意：远程插件默认关闭；开启后仍要求 HTTPS、主机白名单和 RSA 签名

============================================================

【七点五、界面空白怎么办（先看底部状态栏）】
  类型 A：底部状态栏有字，中间一片空白、没有按钮
      含义：主界面被清空（旧版本 bug，2026-10-21 已修复）
      处理：更新到最新版本；源码启动请确认 gui/app_pyqt.py 是最新的

  类型 B：连按钮上的文字都是空白色块
      含义：Qt 找不到字体
      处理：新版会自动注册 C:\\Windows\\Fonts 的微软雅黑/黑体/Segoe UI；
            仍不行就看 设置 -> 系统 -> 深度自检 的"字体"一行

  类型 C：一直停在"正在启动…"
      含义：主界面装配失败
      处理：看 data/logs/trunk.log 末尾有没有"启动失败"

  自查：trunk.log 搜"[启动耗时]"，里面有字体数量、界面显示时间。

============================================================

【八、文件都在哪】
  data/config.json        配置（含 API Key，别外传）
  data/chats.db           聊天记录
  data/logs/              日志
  data/memory.json        长期记忆
  data/memory_cards.jsonl 记忆卡
  data/vectors.db         向量库
  data/_schema.json       数据版本登记表
  data/_migrations/       迁移前自动备份
  data/backups/           自动备份

============================================================

【八、快捷键】
  Enter         发送
  Shift+Enter   换行
  Ctrl+K        命令面板
"""


def show_tutorial_dialog(parent):
    """新手教程（模态）"""
    d = QDialog(parent)
    d.setWindowTitle("\U0001F4D6 新手教程")
    d.setMinimumSize(760, 720)
    l = QVBoxLayout(d)

    txt = QPlainTextEdit()
    txt.setReadOnly(True)
    txt.setPlainText(TEXT)
    txt.setStyleSheet("font-size:13px;")
    l.addWidget(txt)

    # 完整版说明用超链接打开（QLabel 不算按钮，不涨按钮预算）
    # 不用 try/except：os.path 与 QLabel 都不会抛，文件不存在就不显示链接。
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc = os.path.join(base, "使用说明-小白版.txt")
    if os.path.exists(doc):
        link = QLabel(
            '<a href="file:///%s">打开完整《使用说明-小白版》</a>'
            % doc.replace("\\", "/"))
        link.setOpenExternalLinks(True)
        l.addWidget(link)

    row1 = QHBoxLayout()
    row1.addWidget(QLabel("Ollama 下载："))
    for label, url in [
        ("官网", "https://ollama.com/download/windows"),
        ("GitHub", "https://github.com/ollama/ollama/releases/latest"),
        ("加速镜像", "https://ghproxy.net/https://github.com/ollama/ollama/releases/latest"),
    ]:
        b = QPushButton(label)
        b.setStyleSheet("padding:4px 10px;")
        b.clicked.connect(lambda _, u=url: webbrowser.open(u))
        row1.addWidget(b)
    l.addLayout(row1)

    row2 = QHBoxLayout()
    row2.addWidget(QLabel("模型："))
    for label, url in [
        ("Qwen2.5", "https://ollama.com/library/qwen2.5:4b"),
        ("DeepSeek-R1", "https://ollama.com/library/deepseek-r1:7b"),
        ("魔搭社区", "https://modelscope.cn/models?name=qwen2.5"),
        ("HF镜像", "https://hf-mirror.com/models?search=qwen2.5"),
    ]:
        b = QPushButton(label)
        b.setStyleSheet("padding:4px 10px;")
        b.clicked.connect(lambda _, u=url: webbrowser.open(u))
        row2.addWidget(b)
    l.addLayout(row2)

    btn = QPushButton("知道了")
    btn.clicked.connect(d.close)
    l.addWidget(btn)
    d.exec_()
