# -*- coding: utf-8 -*-
"""补全候选（批次 47）：jedi 可选接入 + 候选排序。

纯 Python，不导入 Qt，方便 headless 测试：

    jedi_available()                 —— 装没装 jedi（每个进程只探测一次）
    jedi_completions(...)            —— jedi 推断的 Top-N；没装/出错返回 []
    same_dir_words(path)             —— 同目录 .py 里的 def/class 名（带缓存）
    rank_words(...)                  —— 本文件 > jedi > 近期编辑 > 同目录 > 索引
    complete_words(...)              —— 编排：开关开且 jedi 可用就用 jedi，
                                        否则完全回退到老的关键字候选

为什么默认关（``code_complete.jedi``）
--------------------------------------
jedi 要 import 一整套推断引擎，冷启动会拖慢第一次补全；老机器上没装
jedi 也不能让补全直接消失。所以开关默认关，打开后**失败自动回退**本地
关键字，任何异常都只吞掉不冒泡到 Qt 事件循环。

排序档位
--------
0 本文件符号 > 1 jedi 推断（当前光标上下文的精确结果）> 2 近期编辑
> 3 同目录 > 4 索引 > 5 其它（关键字/内置名）。同档内先看前缀是否**大小写
敏感**命中，再看长度、字典序，保证每次输入候选顺序稳定（不会"跳来跳去"）。
"""
from __future__ import annotations

import os
import re
import sys

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover - 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


_JEDI = None                      # None=没探测过；False=没装；模块对象=可用
_DEF_RE = re.compile(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)", re.M)
_DIR_CACHE = {}                   # dir -> (签名, 名字集合)


def jedi_available(force=False):
    """jedi 是否可用；探测结果缓存，避免每次补全都试 import。"""
    global _JEDI
    if _JEDI is None or force:
        try:
            import jedi  # noqa: F401
            _JEDI = jedi
        except Exception as e:  # 没装或版本坏掉都算不可用
            _x6_swallowed(__name__, e, "import jedi")
            _JEDI = False
    return _JEDI is not False


def jedi_enabled(trunk=None):
    """开关 ``code_complete.jedi``：默认关，读不到也按关处理。"""
    try:
        value = trunk.rule("code_complete.jedi", False) if trunk is not None \
            else False
    except Exception as e:
        _x6_swallowed(__name__, e, "completion switch")
        value = False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "on", "true", "yes", "开")
    return bool(value)


def jedi_completions(code, path="", line=1, column=0, limit=5, root=""):
    """jedi 补全 Top-N：只取名字，过滤 dunder，去重后保持 jedi 的相关性顺序。

    ``line`` 是 1 基、``column`` 是 0 基（jedi 的约定）。``root`` 会临时放进
    ``sys.path``，这样同项目里 ``import`` 的模块也能被推断到（跨文件候选）。
    """
    if not jedi_available():
        return []
    try:
        import jedi
        src = str(code or "")
        kwargs = {"code": src}
        if path:
            kwargs["path"] = str(path)
        added = ""
        if root and str(root) not in sys.path:
            added = str(root)
            sys.path.insert(0, added)
        try:
            script = jedi.Script(**kwargs)
            comps = script.complete(max(1, int(line)), max(0, int(column)))
        finally:
            if added:
                try:
                    sys.path.remove(added)
                except ValueError as e:  # 静默是故意的 - 别的线程先删了
                    _x6_swallowed(__name__, e, "restore sys.path")
        out, seen = [], set()
        for comp in comps:
            name = str(getattr(comp, "name", "") or "")
            if not name or name.startswith("__") or name in seen:
                continue
            seen.add(name)
            out.append(name)
            if len(out) >= max(1, int(limit or 1)):
                break
        return out
    except Exception as e:  # 静默是故意的 - jedi 出错必须回退本地关键字
        _x6_swallowed(__name__, e, "jedi complete")
        return []


def _dir_signature(directory):
    """目录签名：文件名 + mtime，用来判断缓存是否过期。"""
    items = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return ()
    for name in names[:200]:
        if not name.endswith(".py") or name.startswith("."):
            continue
        p = os.path.join(directory, name)
        try:
            items.append((name, os.path.getmtime(p)))
        except OSError:
            continue
    return tuple(items)


def same_dir_words(path, max_files=100):
    """同目录其它 .py 的 def/class 名：只扫正则，不建 ast，带 mtime 缓存。"""
    if not path:
        return set()
    directory = os.path.dirname(os.path.abspath(str(path)))
    sig = _dir_signature(directory)
    cached = _DIR_CACHE.get(directory)
    if cached and cached[0] == sig:
        return set(cached[1])
    names = set()
    count = 0
    for name, _mtime in sig:
        if count >= max_files:
            break
        full = os.path.join(directory, name)
        if os.path.abspath(full) == os.path.abspath(str(path)):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                text = f.read(200000)
        except OSError:
            continue
        names.update(_DEF_RE.findall(text))
        count += 1
    _DIR_CACHE[directory] = (sig, frozenset(names))
    return names


def project_root(trunk=None, path=""):
    """补全用的项目根：优先躯干的工作区，其次当前文件所在目录。"""
    base = getattr(trunk, "base", "") if trunk is not None else ""
    if base:
        return str(base)
    if path:
        return os.path.dirname(os.path.abspath(str(path)))
    return ""


def indexed_words(trunk=None):
    """工作区索引里的符号名（排序第四档）；没有索引就返回空集合。"""
    try:
        if trunk is None:
            return set()
        idx = trunk.get_workspace_index()
        return set((idx.data.get("symbols") or {}).keys())
    except Exception as e:  # 静默是故意的 - 没索引就只按本文件补全
        _x6_swallowed(__name__, e, "completion index")
        return set()


def _tier(name, local, jedi_words, recent, same_dir, indexed):
    if name in local:
        return 0
    if name in jedi_words:
        return 1
    if name in recent:
        return 2
    if name in same_dir:
        return 3
    if name in indexed:
        return 4
    return 5


def rank_words(words, prefix="", *, local=(), jedi_words=(), recent=(),
               same_dir=(), indexed=(), limit=300):
    """按"本文件 > jedi > 近期编辑 > 同目录 > 索引"排序并去重。"""
    local = set(local or ())
    jedi_words = set(jedi_words or ())
    recent = set(recent or ())
    same_dir = set(same_dir or ())
    indexed = set(indexed or ())
    p = str(prefix or "")
    low = p.lower()

    def match_rank(name):
        if p and name.startswith(p):
            return 0
        if p and name.lower().startswith(low):
            return 1
        return 2

    def key(name):
        return (_tier(name, local, jedi_words, recent, same_dir, indexed),
                match_rank(name), len(name), name)

    ordered = sorted({str(w) for w in (words or ()) if str(w)}, key=key)
    limit = int(limit or 0)
    return ordered[:limit] if limit > 0 else ordered


def complete_words(base_words, code, path="", line=1, column=0, *,
                   prefix="", jedi=False, root="", local=(), recent=(),
                   same_dir=(), indexed=(), limit=300, index_hits=50):
    """编排补全：返回 ``{"words": [...], "source": "jedi"|"local"}``。

    ``base_words`` 是调用方原有的关键字/内置名候选（gui 里的
    ``completion_words``），任何情况下都会保留，保证补全不会"空"。
    同目录符号全加；索引符号只加**前缀命中**的前 ``index_hits`` 个，
    否则几千个名字塞进候选会让弹窗过滤变慢。
    """
    words = list(base_words or ())
    jedi_words = []
    if jedi:
        jedi_words = jedi_completions(code, path, line, column, limit=5,
                                      root=root)
    if jedi_words:
        words = jedi_words + words
    low = str(prefix or "").lower()
    words.extend(str(w) for w in (same_dir or ()) if w)
    hits = 0
    for name in sorted(indexed or ()):
        if not str(name).lower().startswith(low):
            continue
        words.append(str(name))
        hits += 1
        if hits >= max(1, int(index_hits or 1)):
            break
    return {
        "words": rank_words(words, prefix, local=local, jedi_words=jedi_words,
                            recent=recent, same_dir=same_dir,
                            indexed=indexed, limit=limit),
        "source": "jedi" if jedi_words else "local",
    }
