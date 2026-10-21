# -*- coding: utf-8 -*-
"""工具接口契约校验（Module-Level Standard 1.3 / 1.5 / 5.4）。

历史工具声明只有描述和参数中文名：

    {"name": "weather_query", "method": "query", "desc": "查天气",
     "args": {"city": "城市名"}, "hints": [...]}

标准 1.3 要求：名称、参数类型、返回类型、错误类型、副作用。
本模块定义**可选但强校验**的扩展字段（``contract``），并做静态检查：

* 写了 ``contract`` 的：字段必须合法、类型必须在白名单内；
* 没写 ``contract`` 的：兼容通过，但计入 ``missing_contract``，
  由质量门禁决定是否升级为错误。

JSON 可序列化（1.5）在编译期就检查：类型只能取白名单常量，
不允许出现 Python 对象/函数引用。
"""
from __future__ import annotations

TYPE_STRING = "string"
TYPE_INTEGER = "integer"
TYPE_NUMBER = "number"
TYPE_BOOLEAN = "boolean"
TYPE_ARRAY = "array"
TYPE_OBJECT = "object"
TYPE_NULL = "null"

JSON_TYPES = (TYPE_STRING, TYPE_INTEGER, TYPE_NUMBER, TYPE_BOOLEAN,
              TYPE_ARRAY, TYPE_OBJECT, TYPE_NULL)

SIDE_EFFECT_KINDS = ("network", "filesystem_read", "filesystem_write",
                     "process", "ui_control", "config_write")

CONTRACT_SCHEMA_VERSION = "1.0"
CONTRACT_KEYS = {"params", "returns", "errors", "side_effects",
                 "idempotent", "timeout_ms", "concurrency_safe",
                 "description", "not_responsible"}


def _check_type(spec, where, errors):
    if not isinstance(spec, dict):
        errors.append("%s must be an object" % where)
        return
    t = spec.get("type")
    if t not in JSON_TYPES:
        errors.append("%s.type must be one of %s (got %r)"
                      % (where, ", ".join(JSON_TYPES), t))
    if "items" in spec:
        if t != TYPE_ARRAY:
            errors.append("%s.items only valid for array" % where)
        else:
            _check_type(spec.get("items"), where + ".items", errors)
    if "properties" in spec:
        if t != TYPE_OBJECT:
            errors.append("%s.properties only valid for object" % where)
        elif not isinstance(spec.get("properties"), dict):
            errors.append("%s.properties must be an object" % where)


def validate_contract(tool, *, module=""):
    """校验单个工具的 ``contract`` 字段。

    返回 {ok, errors, warnings, missing_contract}。
    ``missing_contract=True`` 表示缺少契约（兼容旧工具，但不算完整合规）。
    """
    tool = tool or {}
    name = str(tool.get("name") or tool.get("method") or "?")
    where = "%s.%s" % (module or "?", name)
    errors, warnings = [], []
    contract = tool.get("contract")
    if contract is None:
        return {"ok": True, "errors": [], "warnings": [],
                "missing_contract": True, "name": name}
    if not isinstance(contract, dict):
        return {"ok": False, "errors": ["%s.contract must be an object" % where],
                "warnings": [], "missing_contract": False, "name": name}
    unknown = set(contract) - CONTRACT_KEYS
    if unknown:
        warnings.append("%s.contract has unknown keys: %s"
                        % (where, sorted(unknown)))
    params = contract.get("params") or {}
    if not isinstance(params, dict):
        errors.append("%s.contract.params must be an object" % where)
    else:
        for pname, spec in params.items():
            pwhere = "%s.params.%s" % (where, pname)
            if not isinstance(spec, dict):
                errors.append("%s must be an object" % pwhere)
                continue
            _check_type(spec, pwhere, errors)
            if spec.get("required") and "default" in spec:
                warnings.append("%s is required but also has a default" % pwhere)
    returns = contract.get("returns")
    if returns is None:
        warnings.append("%s.contract.returns missing（标准 1.3 要求声明返回类型）"
                        % where)
    else:
        _check_type(returns, where + ".returns", errors)
    errs = contract.get("errors") or []
    if not isinstance(errs, (list, tuple)):
        errors.append("%s.contract.errors must be an array" % where)
    else:
        try:
            from core.plugin_errors import is_known_code
        except Exception:
            is_known_code = lambda c: True  # noqa: E731
        for code in errs:
            if not is_known_code(code):
                errors.append("%s.contract.errors has unknown code %r"
                              % (where, code))
    side = contract.get("side_effects") or []
    if not isinstance(side, (list, tuple)):
        errors.append("%s.contract.side_effects must be an array" % where)
    else:
        for item in side:
            kind = str(item).split(":", 1)[0].strip()
            if kind not in SIDE_EFFECT_KINDS:
                errors.append("%s.contract.side_effects has unknown kind %r"
                              % (where, kind))
    if "idempotent" in contract and not isinstance(contract["idempotent"], bool):
        errors.append("%s.contract.idempotent must be boolean" % where)
    timeout = contract.get("timeout_ms")
    if timeout is not None:
        if not isinstance(timeout, int) or timeout <= 0:
            errors.append("%s.contract.timeout_ms must be a positive integer"
                          % where)
        elif timeout > 600000:
            warnings.append("%s.contract.timeout_ms > 10min，建议拆小" % where)
    if "concurrency_safe" in contract and not isinstance(
            contract["concurrency_safe"], bool):
        errors.append("%s.contract.concurrency_safe must be boolean" % where)
    if contract.get("not_responsible") is not None:
        nr = contract["not_responsible"]
        if not isinstance(nr, (list, tuple)) or not all(
                isinstance(x, str) and x.strip() for x in nr):
            errors.append("%s.contract.not_responsible must be a non-empty "
                          "array of strings" % where)
    if not contract.get("description"):
        warnings.append("%s.contract.description missing（标准 1.1 要求声明边界）"
                        % where)
    return {"ok": not errors, "errors": errors[:20], "warnings": warnings[:20],
            "missing_contract": False, "name": name}


def validate_tools(tools, *, module=""):
    """批量校验一个模块的全部工具声明。"""
    tools = list(tools or [])
    per, errors, warnings = [], [], []
    missing = 0
    names = set()
    for tool in tools:
        if not isinstance(tool, dict):
            errors.append("%s: 工具声明必须是对象" % (module or "?"))
            continue
        name = str(tool.get("name") or "")
        if name:
            if name in names:
                errors.append("%s: 工具名重复 %s" % (module or "?", name))
            names.add(name)
        r = validate_contract(tool, module=module)
        per.append(r)
        errors.extend(r["errors"])
        warnings.extend(r["warnings"])
        if r["missing_contract"]:
            missing += 1
    return {"ok": not errors, "errors": errors[:30], "warnings": warnings[:30],
            "total": len(tools), "missing_contract": missing,
            "per_tool": per}


def is_json_serializable(value, depth=0):
    """递归判断是否是纯 JSON 类型（标准 1.5）。"""
    if depth > 6:
        return False
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_json_serializable(v, depth + 1)
                   for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return all(is_json_serializable(v, depth + 1) for v in value)
    return False
