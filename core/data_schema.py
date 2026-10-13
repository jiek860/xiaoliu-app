# -*- coding: utf-8 -*-
"""数据文件版本登记 —— 防止"格式变了但没人知道"

要解决什么
----------
这一轮修的两个真问题，根子都是**格式假设 + 没有版本校验**：
    · memory_organizer.auto_organize  假定每行都是合法 JSON，
      解析失败就跳过，写回却全量覆盖 -> 坏行被永久删除
    · startup_optimizer.precompile    假定 py_compile 会抛异常（它不会）

数据文件散着 45 个，**逐个版本化是过度设计**。所以只做两件最值钱的事：

    ① **降级保护**：数据是更新版本的程序写的，当前版本读它要**警告**，
       而不是按旧格式静默误读、甚至覆盖回去把数据搞坏。
    ② 给将来的迁移**留一个挂点**：格式真要变时，有地方记"该迁到几版"。

只登记**有真实格式假设**的文件（见 WATCHED）。像 weather_cache.json
那种"坏了就重下"的缓存不登记 —— 登记了只会产生噪声。

落地方式：data/_schema.json
    {
      "data_schema": 1,
      "files": {"memory_cards.jsonl": 1, "config.json": 1, ...}
    }
放在**单独文件**里而不是塞进数据文件头：jsonl 多加一行头会让所有
按行解析的旧代码把它当数据（我们刚为"坏行保留"改过 auto_organize，
最不该在数据里塞特殊行）。
"""
import json
import os
import time

# 数据登记表的版本（登记表本身的格式）
DATA_SCHEMA = 1

# 只登记有真实格式假设的：升级后旧代码会**误读**的那些
# 值 = 该文件当前的格式版本；将来改格式时 +1 并在这里写迁移
WATCHED = {
    "memory_cards.jsonl": 1,   # 每行一个 {"facts": [...], "time": ...}
    "dreams.jsonl": 1,         # 每行一个梦境记录
    "personality.json": 1,     # {"birth_time", "relation_stage", "traits", ...}
    "config.json": 1,          # 靠"合并 DEFAULTS + 类型校验"迁移，见 core/config.py
    "chats.db": 1,             # messages 表结构
    "vectors.db": 1,           # vectors 表结构
    "graph.db": 1,             # 知识图谱三元组表
    "memory.json": 1,          # 长期记忆
}

_REL = os.path.join("data", "_schema.json")


def _path(base):
    return os.path.join(base, _REL)


def load(base):
    """读版本登记表；没有或坏了都返回空表（不抛）

    静默是故意的：登记表坏了/不存在**不是错误状态** ——
    首次运行本来就没有它；坏了就当"还没登记过"，由 check() 报成
    "unknown"（提示性），而不是让整个自检崩掉。
    """
    try:
        d = json.load(open(_path(base), encoding="utf-8"))
        if isinstance(d, dict):
            return d
    # 静默是故意的：登记表不存在/坏了不是错误状态（首次运行本来就没有），
    # 由 check() 报成 unknown 提示，不该让自检崩掉
    except Exception:
        pass
    return {}


def save(base, data):
    """原子写（先 .tmp 再 replace）—— 中途崩不会毁掉登记表

    静默是故意的：写不进去（盘满/权限）时返回 False 让调用方知道，
    这里不再重复抛 —— stamp() 本来就把返回值给了调用方。
    """
    p = _path(base)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    # 静默是故意的：写不进去（盘满/权限）时用返回值告诉调用方，
    # 这里不再重复抛 —— stamp() 会把 False 传上去
    except Exception:
        return False


def stamp(base, name, version=None):
    """把某个数据文件标成当前版本（写数据之后调用）"""
    d = load(base) or {}
    d["data_schema"] = DATA_SCHEMA
    files = d.setdefault("files", {})
    files[name] = int(version if version is not None
                      else WATCHED.get(name, 1))
    d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return save(base, d)


def stamp_all(base):
    """把登记表里所有存在的文件都标成当前版本（首次运行时用）"""
    for name in WATCHED:
        if os.path.exists(os.path.join(base, "data", name)):
            stamp(base, name)
    return load(base)


def check(base):
    """检查数据版本，返回

        {
          "ok": bool,                 # 有没有需要担心的事
          "warning": [...],           # 降级风险（数据比程序新）—— 最要紧的
          "info": [...],              # 正常/提示
          "unknown": [...],           # 没有版本记录的文件（旧数据）
        }
    """
    d = load(base)
    files = d.get("files") or {}
    out = {"ok": True, "warning": [], "info": [], "unknown": []}

    if not d:
        out["unknown"] = ["还没有版本登记表（data/_schema.json）—— "
                          "首次运行会自动建立"]
        return out

    if int(d.get("data_schema", 0)) > DATA_SCHEMA:
        out["warning"].append(
            "数据登记表是更新版本的程序写的（v%d > 本程序 v%d）—— "
            "建议升级程序再打开，否则可能误读数据"
            % (int(d["data_schema"]), DATA_SCHEMA))
        out["ok"] = False

    for name, want in sorted(WATCHED.items()):
        p = os.path.join(base, "data", name)
        if not os.path.exists(p):
            continue
        got = files.get(name)
        if got is None:
            out["unknown"].append("%s 没有版本记录（旧数据或新加的）" % name)
            continue
        got = int(got)
        if got > want:
            out["warning"].append(
                "%s 的格式版本是 v%d，本程序只认 v%d —— "
                "**这是更新版本写的，先别改它**，升级程序再动"
                % (name, got, want))
            out["ok"] = False
        elif got < want:
            out["warning"].append(
                "%s 的格式版本 v%d 落后于本程序的 v%d —— 需要迁移"
                % (name, got, want))
            out["ok"] = False
        else:
            out["info"].append("%s v%d 正常" % (name, got))
    return out


def describe(base):
    """给自检/界面用的一句话摘要"""
    r = check(base)
    if r["warning"]:
        return "⚠️ 数据版本有问题：%s" % "；".join(r["warning"][:2])
    if r["unknown"]:
        return "数据版本登记不完整（%d 项）" % len(r["unknown"])
    return "数据版本正常（%d 个文件已登记）" % len(r["info"])
