# -*- coding: utf-8 -*-
"""真符号解析：Python 用 AST，JS/TS 优先 tree-sitter，缺失时退回正则。

为什么单独一层
--------------
`find_symbols` 之前只做"符号名子串匹配"，而非 Python 文件根本没有符号 ——
实际上等于正则搜索。这里把"从源码得到符号"独立出来：

* Python：标准库 `ast`，100% 结构化（类/方法/函数/嵌套函数/异步）；
* JS/TS：装了 `tree_sitter_languages` 就用它，否则用保守正则并标注
  `engine="regex"`、`confidence=0.6`，调用方可以据此决定要不要信；
* 每个符号带 `file/line/end_line/kind/name/engine/confidence`，
  后续做跳转、outline、影响面分析都靠这份结构。

注意：正则解析只用于"找不到就降级"，绝不假装自己等于 AST。
"""
from __future__ import annotations

import ast
import re

PY_EXT = {".py"}
JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".mjs": "javascript",
    ".cjs": "javascript",
}

_TS_PARSER_CACHE = {}
_TS_IMPORT_ERROR = None

_JS_SYMBOLS = (
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"),
     "class"),
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
                r"([A-Za-z_$][\w$]*)"), "function"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
                r"\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
     "function"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
                r"\s*=\s*(?:async\s+)?function\b"), "function"),
    (re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)"), "interface"),
    (re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*[=<]"), "type"),
    (re.compile(r"^\s*(?:export\s+)?enum\s+([A-Za-z_$][\w$]*)"), "enum"),
    (re.compile(r"^\s*(?:export\s+)?namespace\s+([A-Za-z_$][\w$]*)"), "namespace"),
)
_JS_IMPORT = re.compile(
    r"^\s*import\s+(?:[^'\"]+?\s+from\s+)?['\"]([^'\"]+)['\"]")
_JS_REQUIRE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")


def language_of(ext):
    return LANG_BY_EXT.get(str(ext or "").lower(), "text")


def _tree_sitter_parser(ext):
    """返回 tree-sitter parser；没装或加载失败返回 None（只降级，不报错）。"""
    global _TS_IMPORT_ERROR
    lang = LANG_BY_EXT.get(str(ext or "").lower())
    if not lang or _TS_IMPORT_ERROR:
        return None
    if lang in _TS_PARSER_CACHE:
        return _TS_PARSER_CACHE[lang]
    try:
        from tree_sitter_languages import get_parser  # type: ignore
        parser = get_parser(lang)
    except Exception as e:  # 可选依赖缺失：标记一次，后面直接走正则
        _TS_IMPORT_ERROR = str(e)[:160]
        return None
    _TS_PARSER_CACHE[lang] = parser
    return parser


def _node_name(node, src):
    name = node.child_by_field_name("name")
    if name is not None:
        return src[name.start_byte:name.end_byte].decode("utf-8", "replace")
    return ""


def _tree_sitter_symbols(path, rel, ext):
    parser = _tree_sitter_parser(ext)
    if parser is None:
        return None
    try:
        src = open(path, "rb").read()
        tree = parser.parse(src)
    except OSError:
        return []
    wanted = {
        "class_declaration": "class", "class": "class",
        "function_declaration": "function", "function": "function",
        "method_definition": "method", "interface_declaration": "interface",
        "type_alias_declaration": "type", "enum_declaration": "enum",
    }
    out = []

    def walk(node, prefix=""):
        kind = wanted.get(node.type)
        if kind:
            name = _node_name(node, src)
            if name:
                out.append({
                    "name": (prefix + "." + name) if prefix else name,
                    "kind": kind, "file": rel,
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "engine": "tree-sitter", "confidence": 0.95,
                })
                child_prefix = (prefix + "." + name) if prefix else name
            else:
                child_prefix = prefix
        else:
            child_prefix = prefix
        for child in node.children:
            walk(child, child_prefix)

    walk(tree.root_node)
    return out


def parse_python(path, rel):
    meta = {"language": "python", "classes": 0, "functions": 0,
            "syntax_error": "", "symbol_engine": "ast"}
    symbols, imports = [], []
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
        tree = ast.parse(src)
    except SyntaxError as e:
        meta["syntax_error"] = "line %s: %s" % (e.lineno, e.msg)
        return {"meta": meta, "symbols": [], "imports": []}
    except OSError:
        return {"meta": meta, "symbols": [], "imports": []}

    def visit(node, scope="", parent_kind="module"):
        for child in getattr(node, "body", []) or []:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
                qualified = (scope + "." + name) if scope else name
                if parent_kind == "class":
                    kind = "method"
                elif parent_kind in ("function", "method", "nested_function"):
                    kind = "nested_function"
                else:
                    kind = "function"
                meta["functions"] += 1
                symbols.append({
                    "name": qualified, "kind": kind, "file": rel,
                    "line": child.lineno,
                    "end_line": getattr(child, "end_lineno", child.lineno),
                    "engine": "ast", "confidence": 1.0,
                    "async": isinstance(child, ast.AsyncFunctionDef),
                })
                visit(child, qualified, kind)
            elif isinstance(child, ast.ClassDef):
                qualified = (scope + "." + child.name) if scope else child.name
                meta["classes"] += 1
                symbols.append({
                    "name": qualified, "kind": "class", "file": rel,
                    "line": child.lineno,
                    "end_line": getattr(child, "end_lineno", child.lineno),
                    "engine": "ast", "confidence": 1.0,
                })
                visit(child, qualified, "class")
            elif isinstance(child, ast.Import):
                imports.extend(a.name for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                mod = child.module or ""
                imports.extend("%s.%s" % (mod, a.name) for a in child.names)

    visit(tree)
    return {"meta": meta, "symbols": symbols,
            "imports": sorted(set(imports))}


def parse_js_like(path, rel):
    meta = {"language": language_of(
                "." + str(path).rsplit(".", 1)[-1].lower()),
            "classes": 0, "functions": 0, "syntax_error": "",
            "symbol_engine": "regex"}
    ts_symbols = _tree_sitter_symbols(path, rel, "." + path.rsplit(".", 1)[-1])
    if ts_symbols is not None:
        meta["symbol_engine"] = "tree-sitter"
        for s in ts_symbols:
            if s["kind"] == "class":
                meta["classes"] += 1
            if s["kind"] in ("function", "method"):
                meta["functions"] += 1
        return {"meta": meta, "symbols": ts_symbols, "imports": []}
    symbols, imports = [], []
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return {"meta": meta, "symbols": [], "imports": []}
    for i, line in enumerate(lines, 1):
        for pat, kind in _JS_SYMBOLS:
            m = pat.match(line)
            if not m:
                continue
            name = m.group(1)
            symbols.append({
                "name": name, "kind": kind, "file": rel, "line": i,
                "end_line": i, "engine": "regex", "confidence": 0.6,
            })
            if kind == "class":
                meta["classes"] += 1
            if kind == "function":
                meta["functions"] += 1
            break
        m = _JS_IMPORT.match(line) or _JS_REQUIRE.search(line)
        if m:
            imports.append(m.group(1))
    return {"meta": meta, "symbols": symbols,
            "imports": sorted(set(imports))}


def parse_source(path, rel):
    """按扩展名选择解析器；不支持的语言返回空结果。"""
    ext = str(path).lower().rsplit(".", 1)[-1]
    if ext == "py":
        return parse_python(path, rel)
    if ext in ("js", "jsx", "ts", "tsx", "mjs", "cjs"):
        return parse_js_like(path, rel)
    return {"meta": {"language": "text", "classes": 0, "functions": 0,
                     "syntax_error": "", "symbol_engine": "none"},
            "symbols": [], "imports": []}


def ts_available():
    return _tree_sitter_parser(".js") is not None
