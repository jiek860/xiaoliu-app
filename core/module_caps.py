# -*- coding: utf-8 -*-
r"""能力注册表：把"模块能做什么"合并成一张工具表

两个来源
--------
    来源 A  插件模块（modules/installed 里那 48 个）
            模块里声明 TOOLS → 运行时**从源码读**（AST），
            清单里的同名字段只是副本，供市场列表/界面显示。
    来源 B  core 模块（core/ 里那 24 个，不是插件、没有清单条目）
            在 core/core_caps.py 里集中声明

为什么来源 A 读源码而不是读清单
------------------------------
modules_repo 的 RSA 签名签的是**模块文件的 sha256**
（core/plugin_signer.calc_hash / tools/sign_modules.py），
清单条目的其它字段（包括 tools）**不在签名覆盖范围内** ——
清单里的 tools 被改了，验签照样通过。
而改模块源码必然改变文件哈希 → 验签失败。
所以把"能力声明"放在源码里、运行时读源码，它才真正被签名保护。

为什么要分开：72 个登记模块里 48 个是插件、24 个在 core，
而"只能靠点按钮到达"的功能（统计报表/记忆整理/成长报告…）绝大多数在 core 那批里 ——
只升级 manifest 覆盖不到它们。

设计约束（照 core/module_buttons.py 的做法）
------------------------------------------
    · 不依赖 Qt，可单独测试
    · 任何异常都返回空结果，绝不因为能力数据把界面搞崩
    · 只返回**文件确实已安装**的模块的能力（没装的不该出现在工具表里）
"""
import ast
import json
import os

MANIFEST_REL = os.path.join("modules_repo", "manifest.json")
INSTALLED_REL = os.path.join("modules", "installed")


def tools_of_source(path, cls=None):
    """从模块源码里取类属性 TOOLS（用 AST，不执行模块代码）

    **这是权威来源，不是清单。**
    原因：modules_repo 的 RSA 签名签的是**模块文件的 sha256**
    （见 core/plugin_signer.calc_hash / tools/sign_modules.py），
    清单条目里的其它字段（包括 tools）**不在签名覆盖范围内**。
    也就是说：清单里的 tools 被人改了，验签照样通过。
    而模块源码改了 -> 文件哈希变了 -> 验签必然失败。

    所以运行时以**源码里的 TOOLS** 为准，清单里的那份只是给
    插件市场列表/界面看的副本。两边不一致时以源码为准。
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if cls and node.name != cls:
            continue
        for sub in node.body:
            if not isinstance(sub, ast.Assign):
                continue
            names = [t.id for t in sub.targets if isinstance(t, ast.Name)]
            if "TOOLS" not in names:
                continue
            try:
                val = ast.literal_eval(sub.value)
            except Exception:
                return []
            if isinstance(val, list):
                return [t for t in val if isinstance(t, dict)]
    return []


def _read_manifest(base):
    """读签名清单；任何异常返回 []"""
    try:
        p = os.path.join(base, MANIFEST_REL)
        if not os.path.exists(p):
            return []
        data = json.load(open(p, encoding="utf-8-sig"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _installed(base, fname):
    try:
        return bool(fname) and os.path.exists(
            os.path.join(base, INSTALLED_REL, fname))
    except Exception:
        return False


def _norm(t, default_mod=None):
    """把一条声明规范化成分发器认识的形状"""
    if not isinstance(t, dict):
        return None
    name = str(t.get("name") or "").strip()
    method = str(t.get("method") or "").strip()
    mod = str(t.get("mod") or default_mod or "").strip()
    if not (name and method and mod):
        return None
    args = t.get("args")
    if not isinstance(args, dict):
        args = {}
    hints = t.get("hints")
    if not isinstance(hints, (list, tuple)):
        hints = []
    out = {
        "desc": str(t.get("desc") or "").strip()[:80],
        "mod": mod, "method": method, "args": args,
        "readonly": bool(t.get("readonly")),
        "confirm": bool(t.get("confirm")),
        "danger": bool(t.get("danger")),
        # bg：长任务标记。聊天触发时 _dispatch 是被回复流程**同步**调用的，
        # 没这个标记就会把回复卡死（自动更新要跑几分钟）。
        # 踩过的坑：加了标记但这里没透出来 —— 归一化时把字段吞了，
        # 表现是"标了也没用"，实测 learn_topic 仍然同步跑了 8 秒。
        "bg": bool(t.get("bg")),
        "hints": [str(h) for h in hints],
        "source": t.get("_source", ""),
    }
    return name, out


def load_tools(base, include_core=True):
    """合并两个来源，返回 {工具名: 声明}

    base 为空或任何环节出错都返回已拿到的部分（最差是 {}），
    调用方 tool_caller 会把它 update 到内置工具表上，空表等于没接 —— 行为与改动前一致。
    """
    out = {}

    # ── 来源 A：插件模块（以**源码里声明的 TOOLS** 为准）──
    #
    # 清单里的 tools 只是副本：RSA 签名签的是模块文件的 sha256，
    # 不覆盖清单条目字段，所以清单里那份改了不起作用（验签也不报）。
    # 源码里的 TOOLS 才是被哈希保护的，运行时读它。
    if base:
        for m in _read_manifest(base):
            if not isinstance(m, dict):
                continue
            fname = str(m.get("file") or "")
            if not _installed(base, fname):
                continue
            src = os.path.join(base, INSTALLED_REL, fname)
            declared = tools_of_source(src, str(m.get("cls") or "") or None)
            if not declared:
                # 源码里没声明才退回清单副本（兼容旧模块）
                declared = m.get("tools") or []
            for t in declared:
                r = _norm(dict(t, _source="plugin"), str(m.get("name") or ""))
                if r:
                    out[r[0]] = r[1]

    # ── 来源 B：core 集中声明 ──
    if include_core:
        try:
            from core.core_caps import CORE_CAPS
            for t in CORE_CAPS:
                r = _norm(dict(t, _source="core"))
                if r:
                    out[r[0]] = r[1]
        except Exception:
            pass

    return out


def _shingles(s):
    """把一段话切成 2 字滑窗（中文用），用于宽松匹配

    为什么需要：hint 写"整理记忆"，用户说的是"帮我整理下记忆" ——
    整串匹配不上，但"整理"这个滑窗能命中。
    PoC 实测就是这么漏掉 memory_organize 的。
    """
    s = str(s or "")
    out = set()
    for i in range(len(s) - 1):
        g = s[i:i + 2]
        if g.strip():
            out.add(g)
    return out


def shortlist(tools, text, limit=15):
    """第一级粗筛：按 hints / 名称 / 说明匹配，缩到 limit 条

    为什么需要：实测 _llm_decide 的提示词在 19 个工具时 1213 字符，
    加到 35 个变 2021（1.7 倍），100 个变 5855（4.8 倍）。
    工具越多模型选错率越高。所以先按关键词把候选缩到 ~15 个再交给 LLM。

    打分：
        +3  hint 整串命中
        +2  hint 的 2 字滑窗命中（宽松，解决"整理记忆" vs "整理下记忆"）
        +2  工具名出现在话里
        +1  说明里的词出现在话里
    兜底：一个都没命中时，返回**内置工具**（没有 source 字段的那些）——
    它们是通用能力，比按字典序取前 N 个有意义。
    """
    try:
        q = str(text or "").strip().lower()
        if not q:
            return list(tools.items())
        qs = _shingles(q)
        scored = []
        for name, info in tools.items():
            score = 0
            for h in info.get("hints") or []:
                hl = str(h).lower()
                if not hl:
                    continue
                if hl in q:
                    score += 3
                elif _shingles(hl) & qs:
                    score += 2
            if name.lower() in q:
                score += 2
            for w in (info.get("desc") or "").lower().replace("：", " ").split():
                if len(w) >= 2 and (w in q or _shingles(w) & qs):
                    score += 1
                    break
            if score:
                scored.append((score, name, info))
        if not scored:
            # 兜底：内置工具优先（通用），再补注册表来的
            builtin = [(n, i) for n, i in tools.items() if not i.get("source")]
            return (builtin or list(tools.items()))[:limit]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(n, i) for _, n, i in scored[:limit]]
    except Exception:
        return list(tools.items())


def describe(base=None):
    """给自检用：报告能力注册情况"""
    try:
        base = base or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools = load_tools(base)
        src = {}
        for v in tools.values():
            src[v.get("source", "?")] = src.get(v.get("source", "?"), 0) + 1
        return {"能力数": len(tools), "按来源": src,
                "只读": sum(1 for v in tools.values() if v.get("readonly")),
                "需确认": sum(1 for v in tools.values() if v.get("confirm"))}
    except Exception as e:
        return {"能力数": 0, "错误": str(e)[:60]}
