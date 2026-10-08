# 小6智能体
住在你电脑里的AI助手，支持本地Ollama模型、云端GLM模型、联网搜索、电脑控制、语音、记忆、多智能体群聊。

## 快速安装
1.  安装Python 3.10或更高版本：https://www.python.org/downloads/
    安装时务必勾选「Add Python to PATH」
2.  双击项目根目录的 `install.bat`，自动安装所有依赖（国内走清华镜像，速度快）
3.  进入gui文件夹，双击 `app_pyqt.py` 启动

## 首次配置
1.  启动后弹出登录框，点「激活」，输入账号名即可生成激活码
2.  配置模型：
    - 本地模型：先装Ollama（https://ollama.com/download），然后命令行执行 `ollama run qwen2.5:3b`
    - 云端模型：打开设置，填GLM的API地址和Key，选云端模式即可
3.  底部输入框打字，回车发送开始聊天

## 常见问题
Q：提示「缺少核心依赖」
A：重新双击install.bat装依赖即可

Q：提示「连不上本地Ollama」
A：确认任务栏有Ollama小羊驼图标，没启动就先启动Ollama

Q：聊天没反应
A：打开功能中心→日志，看trunk.log里的最近报错，或点「导出日志包」

Q：想搬到新电脑
A：把整个项目文件夹复制过去，新电脑上重新跑一遍install.bat就行

## 日志位置
- data/logs/trunk.log：运行日志
- data/logs/crashes.log：崩溃日志
出问题直接在功能中心点「导出日志包」，把生成的zip发出来就行。
