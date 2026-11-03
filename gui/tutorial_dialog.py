# -*- coding: utf-8 -*-
"""新手教程窗口 - 简明版（设置 -> 系统 -> 新手教程，或 Ctrl+K 搜「教程」）"""
import os

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPlainTextEdit)

from gui.feedback_states import make_url_links

TEXT = """小6智能体 · 新手教程
============================================================
这一页不用背。照着「一、二、三」做一遍就能用；
遇到问题直接翻到「六、出问题了怎么办」。

【一、第一次用：3 步搞定】
  第 1 步 登录
     启动后会弹登录框：
       · 有激活码：点「激活」，填账号名 + 激活码
       · 激活过：填账号名，点「登录」
       · 一个激活码只能激活一个账号

  第 2 步 配模型（唯一必须做的一步；模型 = 它的大脑）
     A. 本地模型（免费，断网也能用）
        1) 点本页下方的「官网 / 加速镜像」下载 Ollama
        2) 双击安装包，一路点「下一步」
        3) 打开「设置 → 模型」（简单模式是「开始」），点「检测本地模型」
        4) 按提示下载模型，下完选中，点「保存」
     B. 云端模型（效果更好，按量付费）
        1) 打开「设置 → 模型 → 配置云端模型」
        2) 选「服务商」（如 DeepSeek、智谱、OpenAI）
        3) 把 Key 粘到「Key」框
        4) 点「🔌 测试云端连通」，显示成功后再点「保存」
     · 左下角两个小圆点是状态灯：亮 = 已连上
     · 忘了在哪配：按 Ctrl+K 搜「模型」

  第 3 步 开始聊天
     在底部输入框打字，Enter 发送，Shift+Enter 换行。
     回得慢 / 没反应：Ctrl+K 搜「系统自检」，按提示补配置。

【二、界面怎么看】
  左边    新建对话、历史对话、设置
  中间    聊天内容（标题、列表、代码块会自动排版）
  底部    输入框 + 「＋」/ 聊天·任务 / 语音 / 实时对话 / 模型 / 工作台 / 发送
  右上角  头像菜单 4 项：切换模式、检查更新、设置、帮助
          （登录 / 换账号用左侧栏底部的「🔑 登录」）

  平时建议留在「简单模式」：只留聊天和常用入口，不容易迷路。
  想用高级功能：头像 → 切换模式 → 高级模式。

【三、命令面板 Ctrl+K（最该记住的）】
  忘了功能在哪，就按 Ctrl+K，打字搜名字。
  所有面板和功能都在里面，例如搜：
      「记忆」「日志」「插件」「教程」「反馈」「用量成本」
  按 Esc 关闭搜索框。

【四、常用功能（用到再看）】
  1) 发文件 / 发截图
     把 PDF、Word、Excel、PPT、Markdown 拖进输入框，会自动变成文字；
     或点输入框左边「＋」→「上传文件 / 📷 发图片」。
     Ctrl+V 可以直接粘贴截图，让它看图回答。
  2) 语音
     底部「语音输入」：点一下录 5 秒；按住说完松开就识别。
     底部「实时对话」：连续多轮语音聊天，随时可打断。
     需要先装可选依赖（见第六条）。
  3) 让它操作电脑
     设置 → 工具 → 电脑控制：开软件、点按钮、打字、找文件。
     危险操作会弹窗确认，不确定就点「取消」。
  4) 记忆
     聊过的重要内容会存成「记忆卡」。
     设置 → 记录 → 记忆可视化（或 Ctrl+K 搜「记忆可视化」）：
     能看、能搜、能改、能删。
  5) 写代码 / 改代码
     底部「🧰 工作台」：用一句话说要写什么，它改完先给你看
     diff，确认后才写文件；写前自动备份，可以撤销。
  6) 知识库 / 团队 / 插件
     Ctrl+K 搜「RAG管理」导入资料做知识库；
     Ctrl+K 搜「团队管理」管理多用户和权限；
     设置 → 扩展 → 插件市场 安装 / 卸载插件（带签名才允许装）。
  7) 群聊 / 辩论
     让它几个角色一起讨论同一个问题，适合做对比和头脑风暴。

【五、设置里有什么（按用途找）】
  简单模式（3 页）
     开始   模型配置（本地 / 云端）
     使用   界面、知识库、通知、更新、模式切换
     帮助   新手教程、安全中心、意见反馈、首次设置向导
  高级模式（9 页）
     模型 / 界面 / 工具 / 扩展 / 记录 / 数据 / 依赖 / 系统 / 开发者

  提示：设置窗口开着时再打开别的功能，关掉新窗口后设置页还在，
       不会连带把前面的页面一起关掉。关窗口按 Esc 或右上角 ×。

【六、出问题了怎么办】
  1) 发消息没反应
     九成是模型没配好：Ctrl+K 搜「系统自检」，按提示补。
  2) 连不上本地 Ollama
     ① Ollama 装了吗 ② 托盘里有没有它（没有就重新打开）
     ③ 地址是否为 http://localhost:11434
  3) 浏览器提示「内核没下载」
     正常现象（内核约 700MB，不随程序分发）。命令行跑一次：
       py -3 -m playwright install chromium
  4) 语音按钮点不动
     可选依赖没装：运行 scripts\\install_optional.bat，然后重启程序。
  5) 界面全白 / 启动卡住
     先看底部状态栏有没有字；再看 data\\logs\\trunk.log 最后几行。
  6) 想报问题
     设置 → 系统 → 意见反馈（会自动带脱敏日志，不含聊天内容）。
  7) 想看更详细的说明
     点本页下方「打开完整《使用说明-小白版》」。

【七、文件都在哪（找数据时看）】
  data\\config.json          配置（含 Key，别外传）
  data\\memory_cards.jsonl   记忆卡
  data\\chats.db             聊天记录
  data\\logs\\                日志
  data\\vectors.db           向量库
  backups\\                  自动备份
  换电脑：整个文件夹拷走；optional_libs 和 data\\browsers 可以不拷。

【八、快捷键】
  Enter          发送消息
  Shift+Enter    换行
  Esc            停止当前回复（已收到的内容保留）/ 关闭窗口
  Ctrl+K         命令面板
  Ctrl+Shift+A   把当前文件或选区发给工作台 AI
  工作台里：
    Ctrl+Enter    开始执行 AI 目标
    Ctrl+J        收起 / 展开 AI 面板
    Ctrl+Shift+P  命令中心（命令或文件名）
    Ctrl+Shift+F  在工作区搜索内容
    Ctrl+\\        左右分屏 / 关闭分屏
    F11           全屏
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
    row1.addWidget(make_url_links([
        ("官网", "https://ollama.com/download/windows"),
        ("GitHub", "https://github.com/ollama/ollama/releases/latest"),
        ("加速镜像", "https://ghproxy.net/https://github.com/ollama/ollama/releases/latest"),
    ]), stretch=1)
    l.addLayout(row1)

    row2 = QHBoxLayout()
    row2.addWidget(QLabel("模型："))
    row2.addWidget(make_url_links([
        ("Qwen2.5", "https://ollama.com/library/qwen2.5:4b"),
        ("DeepSeek-R1", "https://ollama.com/library/deepseek-r1:7b"),
        ("魔搭社区", "https://modelscope.cn/models?name=qwen2.5"),
        ("HF镜像", "https://hf-mirror.com/models?search=qwen2.5"),
    ]), stretch=1)
    l.addLayout(row2)

    # 关闭走 Esc / 窗口右上角；「知道了」按钮撤掉，教程窗口不再占按钮预算
    d.exec_()
