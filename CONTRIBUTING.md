# 贡献指南
## 新模块开发规范
1.  在modules/installed/目录下新建your_module.py
2.  定义类，签名必须是def __init__(self, trunk=None)
3.  实现run()方法作为统一入口
4.  启动时自动被trunk扫描注册，不需要手动改lazy_config
## 代码规范
- 文件名小写下划线：my_module.py
- 类名大驼峰：MyModule
- 不要硬编码绝对路径，统一用trunk.base获取项目根目录
- 不要吞异常，except里至少写一行日志
- 模块之间不要互相import，全部通过trunk.call()调用
## 改完代码自检
双击根目录的check.bat，自动跑语法检查、硬编码检查、测试，全部通过再启动程序。
## 禁止做的事
- 不要改core/lazy_config.py里已有的模块键名，会导致老配置不兼容
- 不要直接写data/下的数据库文件，用现成的chat_store/vector_store接口
- 不要把API Key硬编码在代码里，全部存在config.json里
