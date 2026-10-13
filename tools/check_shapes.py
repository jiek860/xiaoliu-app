# -*- coding: utf-8 -*-
r"""结构假设检查器 —— 抓「共享数据的结构变了，调用方没全改」

为什么需要它
------------
这个项目里已经反复出现过同一类 bug：**共享数据的结构变了，但读取方没跟上**。
它们全都不是语法错误，编译、import、静态检查一律通过，
只有在用户点开某个界面时才炸出来：

  · LAZY_MAP 的值从 2 元组变成 3 元组（v3.0 保留中文名）
      -> plugin_market.install() 按错误文件名去找仓库文件
      -> plugin_market.list_all() 解包抛 too many values to unpack
         （界面显示「扫描失败」，整个插件市场不可用）
  · 向量库从 JSON 改成 SQLite + numpy 矩阵
      -> 自检读 vs.embeddings 恒为 0，永远报「向量嵌入不对齐」
  · 聊天记录从 chat_history.jsonl 改成 chats.db
      -> 自检永远显示「聊天记录 0 条」、日志窗口的「操作记录」页签永远空白
  · agent_generic.py 从 modules/installed 移到 core
      -> 发布仓库里的三个薄壳 import 失效

用正则扫源码找这类问题误报太多（会把注释、字符串、撞名的局部变量都算进去），
所以这里用 AST 解析拿精确的调用点，再和运行时的真实结构对账。

三类检查
--------
  1. 解包宽度   for k, (a, b) in X.items()
                  —— 值真实是几个元素，就必须解几个
  2. 调用目标   trunk.call("模块", "方法")
                  —— 那个模块必须真的有这个方法（否则界面弹「功能不可用」）
  3. 结构契约   登记表 / 清单 / 数据文件的形状是否还是个调用方以为的样子

用法
----
    python tools/check_shapes.py            检查，有问题返回码 1
    python tools/check_shapes.py --update   把当前形状写回基准快照
    python tools/check_shapes.py -v         打印全部明细（含通过项）
"""
import argparse
import ast
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

SCAN_DIRS = ("core", "gui", "modules", "modules_repo", "tests", "tools", "scripts", "plugins")
SNAPSHOT = os.path.join(BASE, "tests", "shape_snapshot.json")

# 加载时会占音频设备/端口的模块，检查调用目标时跳过
SKIP_LOAD = {"voice", "stt"}

# 清单条目必须带的字段（modules_repo/manifest.json）
MANIFEST_REQUIRED_KEYS = {
    "name", "title", "file", "cls", "desc", "group",
    "version", "button", "needs_model", "depends", "size",
    "sha256", "signature",
}


# ----------------------------------------------------------------- 工具

def iter_py(roots=None):
    dirs = tuple(roots) if roots else SCAN_DIRS
    for sub in dirs:
        root = sub if os.path.isabs(sub) else os.path.join(BASE, sub)
        if not os.path.isdir(root):
            continue
        for r, ds, fs in os.walk(root):
            ds[:] = [d for d in ds if d != "__pycache__"]
            for f in fs:
                if f.endswith(".py"):
                    p = os.path.join(r, f)
                    try:
                        rel = os.path.relpath(p, BASE)
                    except ValueError:
                        # 测试会把临时文件放别的盘符下，relpath 跨盘会抛
                        rel = p
                    yield rel, p


def parse(rel, path):
    try:
        return ast.parse(open(path, "rb").read())
    except Exception:
        return None


def unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return ""


# ----------------------------------------------------------------- 检查 1

def scan_unpack_sites(targets=("LAZY_MAP", "_lazy"), roots=None):
    """找出 `for k, (a, b, ...) in <target>.items()` 这类解包点及其解包宽度

    返回 [(文件, 行号, 宽度 或 None, 迭代表达式)]
    宽度为 None 表示第二项是单个名字（不透明，不构成形状假设）
    """
    sites = []
    for rel, path in iter_py(roots):
        tree = parse(rel, path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            t = node.target
            if not (isinstance(t, ast.Tuple) and len(t.elts) == 2):
                continue
            second = t.elts[1]
            width = len(second.elts) if isinstance(second, ast.Tuple) else None
            src = unparse(node.iter)
            if any(tg in src for tg in targets):
                sites.append((rel, node.lineno, width, src[:70]))
    return sites


def check_unpack(actual_arity, roots=None):
    """解包宽度必须等于值的真实元数"""
    problems, checked = [], 0
    for rel, ln, width, src in scan_unpack_sites(roots=roots):
        if width is None:
            continue
        checked += 1
        if width != actual_arity:
            problems.append(
                "%s:%d  按 %d 个解包，但 %s 的值其实是 %d 元组"
                % (rel, ln, width, src, actual_arity))
    return checked, problems


# ----------------------------------------------------------------- 检查 2

def scan_call_sites(roots=None):
    """AST 精确抓出 call("模块", "方法") 的字面量调用点

    只认第一个参数是字符串字面量的形式 —— 变量形式（self.call(name, ...)）
    抓不到也不该抓。
    """
    sites = []
    for rel, path in iter_py(roots):
        tree = parse(rel, path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "call"):
                continue
            if len(node.args) < 2:
                continue
            a, b = node.args[0], node.args[1]
            if (isinstance(a, ast.Constant) and isinstance(a.value, str)
                    and isinstance(b, ast.Constant) and isinstance(b.value, str)):
                sites.append((rel, node.lineno, a.value, b.value))
    return sites


def is_probe(method):
    """双下划线包起来的"方法名"是故意的探针，不算 bug。

    代码里有一批这种写法：
        self.trunk.call("task_loop", "__no__")
        ll = self.trunk.modules.get("task_loop")
    利用的是 trunk.call() 会先懒加载模块、再派发调用这一点 ——
    方法名故意写错，调用必然失败（返回值也没人看），目的只是把模块加载起来。
    惯用法有点绕，但它是有意为之，不是"调用了不存在的方法"。

    判据只认 `__xxx__` 这种双下划线形式，不用"下划线开头" ——
    那样会把 `_log`、`_connect` 这些真实私有方法一起放过，
    它们的拼写错误反而查不出来了。
    """
    return method.startswith("__") and method.endswith("__")


def load_module_api(skip=SKIP_LOAD):
    """真实加载每个登记模块，收集它的公开方法名

    返回 ({模块名: set(方法名)}, [加载失败的 (模块, 原因)])
    """
    from core.trunk import Trunk
    from core.lazy_config import LAZY_MAP

    t = Trunk()
    api, failed = {}, []
    for k in sorted(LAZY_MAP):
        if k in skip:
            continue
        try:
            m = t._load_lazy(k)
        except Exception as e:
            failed.append((k, "%s: %s" % (type(e).__name__, str(e)[:50])))
            continue
        if m is None:
            failed.append((k, "加载返回 None"))
            continue
        api[k] = {n for n in dir(m) if not n.startswith("__")}
    # 核心模块也一并收进来（有些 call 目标是核心模块）
    for k in ("trunk", "llm", "vector_store", "knowledge_graph", "auth",
              "backup", "rules_engine", "error_lib", "cache"):
        m = t.modules.get(k) or t._load_lazy(k)
        if m is not None:
            api.setdefault(k, set()).update({n for n in dir(m) if not n.startswith("__")})
    return api, failed


def check_call_targets(api, roots=None):
    """每个 call("模块","方法") 的方法必须真的存在

    返回 (检查数, 问题列表, 模块没加载起来的提示, 探针惯用法列表)
    """
    problems, checked, unknown_mod, probes = [], 0, [], []
    for rel, ln, mod, method in scan_call_sites(roots):
        if is_probe(method):
            probes.append("%s:%d  call(%r, %r)" % (rel, ln, mod, method))
            continue
        if mod not in api:
            unknown_mod.append("%s:%d  call(%r, %r) —— 模块本身没加载起来"
                               % (rel, ln, mod, method))
            continue
        checked += 1
        if method not in api[mod]:
            problems.append("%s:%d  %s 没有方法 %r（调用会返回「功能不可用」）"
                            % (rel, ln, mod, method))
    return checked, problems, unknown_mod, probes


# ----------------------------------------------------------------- 检查 2b

# 把模块绑定到变量的几种写法：
#     x = self.trunk._load_lazy("mod")
#     x = self.trunk.modules.get("mod")
#     x = self.trunk.modules.get("mod") if self.trunk else None
#     x = self.trunk.modules.get("mod") or self.trunk._load_lazy("mod")
BIND_FUNCS = ("_load_lazy", "get")


def _module_of_expr(node):
    """从一个赋值右值里找出它绑定的是哪个模块

    会在整棵子树里找 _load_lazy("X") / modules.get("X") 这类调用。
    返回模块名字符串；找不到或有多个不同名字则返回 None。
    """
    if node is None:
        return None
    found = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        if not isinstance(f, ast.Attribute) or f.attr not in BIND_FUNCS:
            continue
        if not sub.args:
            continue
        a = sub.args[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            # 只认 _load_lazy / modules.get 这两种形状，别把别的 .get 也算进来
            if f.attr == "_load_lazy" or unparse(f.value).endswith("modules"):
                found.add(a.value)
    if len(found) == 1:
        return found.pop()
    return None


def _scope_nodes(tree):
    """产出 (作用域名, 该作用域的子树)

    模块级只取"不在任何函数/类里的语句"。这一点很关键：
    如果模块级直接 walk 整棵树，某个函数里 `gc = self._load_lazy("group_chat")`
    的绑定就会泄漏到另一个函数，把标准库的 `gc.collect()` 误判成
    group_chat 没有 collect 方法。
    """
    mod_body = [n for n in tree.body
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    if mod_body:
        yield "<module>", ast.Module(body=mod_body, type_ignores=[])
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node


def scan_module_attr_sites(roots=None):
    """找出「变量 = 取模块(...)」之后对该变量属性的访问

    返回 [(文件, 行号, 模块名, 属性名, 变量名, 是否被 hasattr 保护)]
    """
    sites = []
    for rel, path in iter_py(roots):
        tree = parse(rel, path)
        if tree is None:
            continue
        for _scope, node in _scope_nodes(tree):
            # 1. 收集 变量 -> 模块名；同一个名字绑到不同模块就作废
            binds, ambiguous = {}, set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    mod = _module_of_expr(sub.value)
                    for tg in sub.targets:
                        if isinstance(tg, ast.Name):
                            if tg.id in binds and binds[tg.id] != mod:
                                ambiguous.add(tg.id)
                            binds[tg.id] = mod
                elif isinstance(sub, ast.AnnAssign):
                    mod = _module_of_expr(sub.value)
                    if isinstance(sub.target, ast.Name):
                        if sub.target.id in binds and binds[sub.target.id] != mod:
                            ambiguous.add(sub.target.id)
                        binds[sub.target.id] = mod
            binds = {k: v for k, v in binds.items() if v and k not in ambiguous}
            if not binds:
                continue

            # 2. 收集 hasattr(x, "attr") —— 这些属性是被保护过的，不算 bug
            guarded = set()
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name) and sub.func.id == "hasattr"
                        and len(sub.args) == 2
                        and isinstance(sub.args[0], ast.Name)
                        and isinstance(sub.args[1], ast.Constant)
                        and isinstance(sub.args[1].value, str)):
                    guarded.add((sub.args[0].id, sub.args[1].value))

            # 3. 找对这些变量的属性访问（只算读取，赋值不算）
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Attribute):
                    continue
                if not isinstance(sub.ctx, ast.Load):
                    continue
                v = sub.value
                if not (isinstance(v, ast.Name) and v.id in binds):
                    continue
                mod = binds[v.id]
                sites.append((rel, sub.lineno, mod, sub.attr, v.id,
                              (v.id, sub.attr) in guarded))
    # 模块级作用域会把整个文件都走一遍，函数作用域又各走一遍，
    # 同一个访问点会被收进来多次，这里按位置去重
    seen, uniq = set(), []
    for s in sites:
        k = (s[0], s[1], s[2], s[3], s[4])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)
    uniq.sort(key=lambda x: (x[0], x[1]))
    return uniq


def check_module_attrs(api, roots=None):
    """变量取到模块之后，访问的属性必须真的存在

    这一条能抓到 self._load_lazy("vector_store") 之后读 vs.embeddings 这类问题 ——
    属性早就不存在了，getattr 默认值兜住不报错，但逻辑是错的（自检永远显示不对齐）。
    """
    problems, checked, guarded_n = [], 0, 0
    for rel, ln, mod, attr, var, guarded in scan_module_attr_sites(roots):
        if guarded:
            guarded_n += 1
            continue
        if attr.startswith("__"):
            continue
        if mod not in api:
            continue
        checked += 1
        if attr not in api[mod]:
            problems.append("%s:%d  %s（变量 %s）没有属性 %r"
                            % (rel, ln, mod, var, attr))
    return checked, problems, guarded_n


# ----------------------------------------------------------------- 检查 3b

# 纳入结构快照的数据存储（代码定义的、结构稳定的那些）
# 不含 logs / 截图 / 导出物这类会随手增减的东西
#
# self_eval.json 已移出：全项目没有写入方（曾经是 quick_eval 的目标，
# 但 quick_eval 实际写的是 reflect_history.json），给它做结构快照没有意义。
DATA_STORES = ("config.json", "memory.json", "graph.json",
               "chats.db", "vectors.db")

# 这几个文件的主键是用户名 —— 属于用户数据，只记值的形状，
# 不把用户名写进快照（快照是要进 git 的）
DATA_USER_KEYED = ("memory.json",)


def _shape_of_json(obj, depth=0, hide_keys=False):
    """只记结构，不记值 —— 避免把用户数据/密钥写进快照

    hide_keys=True 时，形如 {用户名: [记录]} 的映射只记值的形状。
    """
    if depth > 2:
        return {"kind": "deep"}
    if isinstance(obj, dict):
        vals = [v for v in obj.values()]
        if hide_keys and vals and all(isinstance(v, (list, dict)) for v in vals):
            return {"kind": "map-of", "value": _shape_of_json(vals[0], depth + 1,
                                                              hide_keys)}
        return {"kind": "dict", "keys": sorted(obj)[:80]}
    if isinstance(obj, list):
        keys = set()
        kinds = set()
        for it in obj[:200]:
            kinds.add(type(it).__name__)
            if isinstance(it, dict):
                keys |= set(it)
        return {"kind": "list", "item_kinds": sorted(kinds),
                "item_keys": sorted(keys)[:60]}
    return {"kind": type(obj).__name__}


def runtime_data_schema():
    """收集数据存储的结构（表/列/键），用于发现 v5->v6 那种静默迁移"""
    out = {}
    data = os.path.join(BASE, "data")
    for name in DATA_STORES:
        p = os.path.join(data, name)
        key = "data." + name
        if not os.path.exists(p):
            out[key] = {"kind": "absent"}
            continue
        try:
            if name.endswith(".db"):
                import sqlite3
                con = sqlite3.connect(p)
                tabs = {}
                for (t,) in con.execute(
                        "select name from sqlite_master where type='table'"):
                    if t.startswith("sqlite_"):
                        continue
                    tabs[t] = sorted(c[1] for c in
                                     con.execute('PRAGMA table_info("%s")' % t))
                con.close()
                out[key] = {"kind": "sqlite", "tables": tabs}
            else:
                obj = json.load(open(p, encoding="utf-8"))
                out[key] = _shape_of_json(obj, hide_keys=(name in DATA_USER_KEYED))
        except Exception as e:
            out[key] = {"kind": "error", "error": str(e)[:60]}
    return out


# ----------------------------------------------------------------- 检查 3

def runtime_shapes():
    """收集共享结构的真实形状"""
    from core.lazy_config import LAZY_MAP

    shapes = {}
    arities = {len(v) if isinstance(v, (list, tuple)) else None for v in LAZY_MAP.values()}
    shapes["LAZY_MAP.size"] = len(LAZY_MAP)
    shapes["LAZY_MAP.value_arity"] = sorted(a for a in arities if a is not None)

    mpath = os.path.join(BASE, "modules_repo", "manifest.json")
    if os.path.exists(mpath):
        try:
            mf = json.load(open(mpath, encoding="utf-8-sig"))
            shapes["manifest.count"] = len(mf)
            keys = set()
            for m in mf:
                if isinstance(m, dict):
                    keys |= set(m)
            shapes["manifest.keys"] = sorted(keys)
        except Exception as e:
            shapes["manifest.error"] = str(e)[:80]
    shapes.update(runtime_data_schema())
    return shapes


def check_manifest():
    """清单自身的契约：字段齐全、文件存在、名字在登记表里"""
    problems = []
    mpath = os.path.join(BASE, "modules_repo", "manifest.json")
    if not os.path.exists(mpath):
        return ["modules_repo/manifest.json 不存在"], 0

    from core.lazy_config import LAZY_MAP
    mf = json.load(open(mpath, encoding="utf-8-sig"))
    by_file = {v[0] for v in LAZY_MAP.values()}

    for m in mf:
        if not isinstance(m, dict):
            problems.append("清单里有非字典条目: %r" % (m,))
            continue
        name = m.get("name", "?")
        miss = MANIFEST_REQUIRED_KEYS - set(m)
        if miss:
            problems.append("条目 %s 缺字段: %s" % (name, sorted(miss)))
        f = m.get("file", "")
        if not f:
            problems.append("条目 %s 的 file 为空" % name)
        elif not os.path.exists(os.path.join(BASE, "modules_repo", f)):
            problems.append("条目 %s 指向的文件不存在: %s" % (name, f))
        elif f[:-3] not in by_file:
            problems.append("条目 %s 的文件 %s 不在 LAZY_MAP 里（装了也不会被加载）"
                            % (name, f))
    return problems, len(mf)


# ----------------------------------------------------------------- 主流程

def run(verbose=False, update=False):
    print("=" * 70)
    print("结构假设检查")
    print("=" * 70)

    all_problems = []

    from core.lazy_config import LAZY_MAP
    arities = sorted({len(v) for v in LAZY_MAP.values() if isinstance(v, (list, tuple))})

    # 1. 解包宽度
    print("\n[1] 解包宽度  for k, (a, b, ...) in <登记表>.items()")
    if len(arities) != 1:
        msg = "LAZY_MAP 的值元数不一致: %s" % arities
        print("   [X] " + msg)
        all_problems.append(msg)
    else:
        checked, probs = check_unpack(arities[0])
        print("   检查 %d 处解包点，值的真实元数 = %d" % (checked, arities[0]))
        if probs:
            for p in probs:
                print("   [X] " + p)
            all_problems += probs
        else:
            print("   [OK] 全部对得上")

    # 2. 调用目标
    print("\n[2] 调用目标  call(\"模块\", \"方法\") 的方法是否存在")
    api, failed = load_module_api()
    if failed:
        print("   有 %d 个模块加载失败（先看 scripts/check_modules.py）:" % len(failed))
        for k, why in failed[:5]:
            print("      %s: %s" % (k, why))
    checked, probs, unknown, probes = check_call_targets(api)
    print("   已加载 %d 个模块的 API，检查 %d 个调用点" % (len(api), checked))
    if probes:
        print("   跳过 %d 处探针惯用法 call(模块, \"__no__\")（故意写错方法名以触发懒加载）"
              % len(probes))
        if verbose:
            for p in probes:
                print("      " + p)
    if unknown:
        print("   有 %d 个调用指向没加载起来的模块（不计入失败，仅提示）:" % len(unknown))
        for u in unknown[:5]:
            print("      " + u)
    if probs:
        for p in probs:
            print("   [X] " + p)
        all_problems += probs
    else:
        print("   [OK] 所有调用目标都存在")

    # 2b. 变量取模块后的属性访问
    print("\n[2b] 属性访问  变量 = _load_lazy(\"模块\") 之后的 变量.属性")
    checked2, probs2, guarded_n = check_module_attrs(api)
    print("   检查 %d 处属性访问（另有 %d 处被 hasattr 保护，跳过）"
          % (checked2, guarded_n))
    if probs2:
        for p in probs2:
            print("   [X] " + p)
        all_problems += probs2
    else:
        print("   [OK] 访问的属性都存在")

    # 3. 结构契约
    print("\n[3] 结构契约")
    shapes = runtime_shapes()
    for k in sorted(shapes):
        if k.startswith("data."):
            continue
        v = shapes[k]
        print("   %-24s %s" % (k, str(v)[:96]))

    print("\n   数据存储结构（v5->v6 那种静默迁移就靠这个发现）:")
    for k in sorted(shapes):
        if k.startswith("data."):
            print("   %-24s %s" % (k, str(shapes[k])[:88]))

    probs, n = check_manifest()
    if probs:
        for p in probs[:10]:
            print("   [X] " + p)
        all_problems += probs
    else:
        print("   [OK] 清单 %d 条契约完好" % n)

    # 快照比对
    if os.path.exists(SNAPSHOT) and not update:
        try:
            old = json.load(open(SNAPSHOT, encoding="utf-8"))
        except Exception:
            old = {}
        drift = [k for k in shapes if k in old and old[k] != shapes[k]]
        if drift:
            for k in drift:
                msg = "结构漂移: %s  %s -> %s" % (k, old[k], shapes[k])
                print("   [X] " + msg)
                all_problems.append(msg)
        elif verbose:
            print("   [OK] 与基准快照一致")

    if update:
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        json.dump(shapes, open(SNAPSHOT, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2, sort_keys=True)
        print("\n基准快照已更新: %s" % os.path.relpath(SNAPSHOT, BASE))
        return 0

    print("\n" + "=" * 70)
    if all_problems:
        print("发现 %d 个问题" % len(all_problems))
        return 1
    print("全部通过")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="把当前形状写回基准快照")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印通过项明细")
    a = ap.parse_args()
    return run(verbose=a.verbose, update=a.update)


if __name__ == "__main__":
    sys.exit(main())
