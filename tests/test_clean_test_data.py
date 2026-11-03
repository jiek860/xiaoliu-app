# -*- coding: utf-8 -*-
"""测试数据清理脚本（tools/clean_test_data.py）。

为什么单独测：这脚本**真删用户数据**。判据错了就是把真聊天删掉，
所以每条裁剪规则都要有用例钉住 —— 尤其是"整句相等才删"这条：
用包含匹配的话，真用户顺口说的"测试"会被连坐。
"""
import io
import json
import os

from tools import clean_test_data as clean


def _memory():
    return {
        "u1": [],
        "checker": [{"u": "checker", "a": "我上次问你天气"}],
        "userA": [{"u": "A", "a": "说1"}],
        "回归": [],
        "default": [
            {"u": "[压缩记忆]",
             "a": "此前聊过: 测试；你好，测试一下本地模型回复是否正常；你好",
             "compressed": True},
            {"u": "测试用户消息", "a": "测试AI回复"},
            {"u": "检测测试", "a": "这是自动检测发的消息"},
            {"u": "今天天气怎么样", "a": "今天重庆多云，22 到 28 度。"},
            {"u": "你好小6最近的烧烤店有「你好啊」", "a": "你说的是哪家店？"},
            {"u": "成功了", "a": "行，那就好。"},
        ],
        "_schema_version": 2,
    }


# ---------------------------------------------------------------- 判据
def test_fixture_exact_matches_whole_text_only():
    assert clean.is_test_text("我的猫叫豆豆") is True
    assert clean.is_test_text("第 3 轮提问") is True
    # 包含但不相等的**不删**：真聊天里可能出现这些词
    assert clean.is_test_text("帮我测试一下这个接口") is False
    assert clean.is_test_text("") is False
    assert clean.is_test_text(None) is False


def test_selfcheck_marker_matches_inside_text():
    assert clean.is_test_text("你好，测试一下本地模型回复是否正常") is True
    assert clean.is_test_text("这是自动检测发的消息") is True


def test_ambiguous_short_phrase_not_deleted_from_memory():
    """「成功了」只清日志，不清记忆库 —— 真用户完全可能这么说"""
    assert clean.is_test_text("成功了", clean.LOG_EXACT) is True
    assert clean.is_test_text("成功了", clean.MEMORY_EXACT) is False


# ---------------------------------------------------------------- 记忆库
def test_clean_memory_drops_test_keys_and_rows():
    memory = _memory()
    new, detail = clean.clean_memory(memory)
    assert set(detail["用户键"]) == {"u1", "checker", "userA", "回归"}
    assert detail["条目"] == 3
    assert set(new) == {"default", "_schema_version"}
    assert new["_schema_version"] == 2          # 版本号不能被清掉
    users = [row["u"] for row in new["default"]]
    assert "测试用户消息" not in users
    assert "检测测试" not in users
    assert not any(row.get("compressed") for row in new["default"])   # 压缩记忆整条删
    assert "今天天气怎么样" in users
    assert "成功了" in users                      # 真聊天留着


def test_clean_memory_does_not_mutate_input():
    memory = _memory()
    before = json.dumps(memory, ensure_ascii=False, sort_keys=True)
    clean.clean_memory(memory)
    assert json.dumps(memory, ensure_ascii=False, sort_keys=True) == before


def test_suspicious_rows_reports_repeats_only():
    rows = [{"u": "什么是量子纠缠"}, {"u": "什么是量子纠缠"},
            {"u": "什么是量子纠缠"}, {"u": "今天天气怎么样"},
            {"u": "测试"}, {"u": "测试"}]
    got = clean.suspicious_rows(rows)
    assert got == [("什么是量子纠缠", 3)]


# ---------------------------------------------------------------- 日志
def test_clean_shadow_keeps_bad_lines():
    lines = ['{"text": "我的猫叫豆豆"}\n',
             '{"text": "你好小6最近的烧烤店有"}\n',
             "这不是 json\n",
             "\n"]
    kept, dropped = clean.clean_shadow_lines(lines)
    assert dropped == 1
    assert "这不是 json\n" in kept
    assert "\n" in kept
    assert len(kept) == 3


def test_clean_failure_lines_parses_jsonl():
    """失败库是 jsonl —— 传进去的是**行**不是 dict，别当 json.loads 出来的用"""
    lines = ['{"用户": "测试用户消息", "类别": "general"}\n',
             '{"用户": "可以帮我查看最近的烧烤店吗", "类别": "off_topic"}\n',
             "坏行\n"]
    kept, dropped = clean.clean_failure_lines(lines)
    assert dropped == 1
    assert len(kept) == 2
    assert "烧烤店" in kept[0]
    assert kept[1] == "坏行\n"


def test_clean_rows_for_failure_library():
    rows = [{"用户": "测试用户", "类别": "general"},
            {"用户": "可以帮我查看最近的烧烤店吗", "类别": "off_topic"}]
    kept, dropped = clean.clean_rows(rows)
    assert dropped == 1
    assert kept[0]["用户"] == "可以帮我查看最近的烧烤店吗"


# ---------------------------------------------------------------- 端到端
def _make_data(base):
    data = os.path.join(str(base), "data")
    os.makedirs(os.path.join(data, "plugin_data", "self_reflect"), exist_ok=True)
    with io.open(os.path.join(data, "memory.json"), "w", encoding="utf-8") as f:
        json.dump(_memory(), f, ensure_ascii=False)
    with io.open(os.path.join(data, "chat_shadow.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"text": "我的猫叫豆豆"}\n{"text": "你好小6最近的烧烤店有"}\n')
    with io.open(os.path.join(data, "chat_failures.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"用户": "测试用户消息"}\n{"用户": "菜单"}\n')
    with io.open(os.path.join(data, "plugin_data", "self_reflect",
                              "reflect_history.json"), "w", encoding="utf-8") as f:
        json.dump([{"用户": "测试一下人格"}, {"用户": "给我讲讲易经啊"}], f,
                  ensure_ascii=False)
    return data


def test_dry_run_does_not_touch_files(tmp_path):
    data = _make_data(tmp_path)
    before = {}
    for name in os.listdir(data):
        path = os.path.join(data, name)
        if os.path.isfile(path):
            before[name] = os.path.getsize(path)
    result = clean.plan(tmp_path)
    assert result["memory.json"]["detail"]["条目"] == 3
    after = {}
    for name in os.listdir(data):
        path = os.path.join(data, name)
        if os.path.isfile(path):
            after[name] = os.path.getsize(path)
    assert before == after


def test_apply_cleans_and_backs_up(tmp_path):
    data = _make_data(tmp_path)
    written, backup_dir = clean.apply(clean.plan(tmp_path), tmp_path)
    assert written == 4
    assert os.path.isdir(backup_dir)
    # 备份按 data/ 下的相对路径摆（平铺文件名会在 Windows 上撑爆 MAX_PATH）
    for name in ("memory.json", "chat_shadow.jsonl", "chat_failures.jsonl"):
        assert os.path.exists(os.path.join(backup_dir, "data", name))
    assert os.path.exists(os.path.join(backup_dir, "data", "plugin_data",
                                       "self_reflect", "reflect_history.json"))
    memory = json.loads(io.open(os.path.join(data, "memory.json"),
                                encoding="utf-8").read())
    assert "userA" not in memory
    assert memory["_schema_version"] == 2
    shadow = io.open(os.path.join(data, "chat_shadow.jsonl"), encoding="utf-8").read()
    assert "豆豆" not in shadow
    reflect = json.loads(io.open(os.path.join(data, "plugin_data", "self_reflect",
                                              "reflect_history.json"),
                                 encoding="utf-8").read())
    assert [row["用户"] for row in reflect] == ["给我讲讲易经啊"]


def test_second_run_is_noop(tmp_path):
    data = _make_data(tmp_path)
    clean.apply(clean.plan(tmp_path), tmp_path)
    again = clean.plan(tmp_path)
    assert all(not clean._has_change(item) for item in again.values())
    written, _ = clean.apply(again, tmp_path)
    assert written == 0


def test_missing_files_are_skipped(tmp_path):
    assert clean.plan(tmp_path) == {}
    assert clean.apply({}, tmp_path) == (0, "")


def test_main_defaults_to_dry_run(tmp_path, capsys):
    _make_data(tmp_path)
    assert clean.main(["--base", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "干跑" in out
    assert "没有动任何文件" in out


def test_main_json_output_is_parseable(tmp_path, capsys):
    _make_data(tmp_path)
    assert clean.main(["--base", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "memory.json" in payload
