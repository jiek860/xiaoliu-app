# -*- coding: utf-8 -*-
"""记忆灰度报告（批次 43.5）：读影子日志，算注入字数 / 「还记得」命中率。

口径（与 docs/105 一致）：
    · 主行（无 kind）= 一轮回复，text 是用户原话
    · memory_v2  = v2 本轮预注入的记忆段（preview / v2_chars / legacy_chars）
    · memory_write = 影子期本应写入的记忆
    · 「还记得」命中 = 该主行之前最近的一条 memory_v2 有 preview
"""
import json
import os

from tools.memory_report import load_rows, main, markdown, summarize

BASE_ROWS = [
    {"text": "早上好", "answer_chars": 3},
    {"kind": "memory_v2", "count": 2, "v2_chars": 60,
     "legacy_chars": 100, "preview": "用户喜欢短句"},
    {"text": "你还记得我喜欢什么吗", "answer_chars": 8},
    {"kind": "memory_write", "reason": "strong", "count": 1,
     "preview": ["用户喜欢短句"]},
    {"text": "今天写点代码", "answer_chars": 9},
    {"kind": "memory_v2", "count": 3, "v2_chars": 40,
     "legacy_chars": 100, "preview": "用户在杭州"},
    {"text": "还记得我住哪吗", "answer_chars": 5},
]


def _write_shadow(base, rows):
    path = os.path.join(str(base), "data", "chat_shadow.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        for row in rows:
            fp.write((row if isinstance(row, str)
                      else json.dumps(row, ensure_ascii=False)) + "\n")
    return path


def test_load_rows_missing_file(tmp_path):
    assert load_rows(os.path.join(str(tmp_path), "nope.jsonl")) == []


def test_load_rows_skips_bad_lines(tmp_path):
    path = _write_shadow(tmp_path, ["{bad", {"text": "好行"}])
    rows = load_rows(path)
    assert rows == [{"text": "好行"}]


def test_summarize_counts_turns_and_chars():
    stats = summarize(BASE_ROWS)
    assert stats["turns"] == 4            # 主行 4 条（不含 memory_* 影子行）
    assert stats["memory_shadow"] == 2
    assert stats["v2_chars"] == 100
    assert stats["legacy_chars"] == 200
    assert stats["avg_v2_chars"] == 50.0
    assert stats["avg_legacy_chars"] == 100.0
    assert stats["char_reduction"] == 0.5
    assert stats["write_previews"] == 1


def test_summarize_hit_rate_pairs_preview_with_next_turn():
    stats = summarize(BASE_ROWS)
    # 两次「还记得」都能配到上一条 memory_v2 的 preview
    assert stats["asks"] == 2
    assert stats["hits"] == 2
    assert stats["hit_rate"] == 1.0


def test_summarize_miss_when_no_preview_before_ask():
    stats = summarize([
        {"text": "还记得吗"},
        {"kind": "memory_v2", "count": 0, "v2_chars": 0,
         "legacy_chars": 0, "preview": ""},
        {"text": "还记得吗"},
    ])
    assert stats["asks"] == 2
    assert stats["hits"] == 0
    assert stats["hit_rate"] == 0.0


def test_summarize_falls_back_to_preview_length():
    """旧影子行没写 v2_chars 时，用 preview 长度估算。"""
    stats = summarize([{"kind": "memory_v2", "preview": "abcde"}])
    assert stats["v2_chars"] == 5
    assert stats["avg_v2_chars"] == 5.0


def test_summarize_empty_rows_has_zero_ratios():
    stats = summarize([])
    assert stats["turns"] == 0
    assert stats["avg_v2_chars"] == 0.0
    assert stats["char_reduction"] == 0.0
    assert stats["hit_rate"] == 0.0


def test_markdown_contains_key_numbers():
    text = markdown(summarize(BASE_ROWS))
    assert "记忆 v2 灰度报告" in text
    assert "100.0%" in text             # 命中率
    assert "50.0%" in text              # 字数下降
    assert "shadow" in text             # 切换门槛提示


def test_main_writes_json_and_markdown(tmp_path):
    _write_shadow(tmp_path, BASE_ROWS)
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    stats = main(["--base", str(tmp_path), "--json", str(out_json),
                  "--markdown", str(out_md)])
    assert stats["hits"] == 2
    with open(out_json, encoding="utf-8") as fp:
        saved = json.load(fp)
    assert saved["turns"] == 4
    assert saved["source"].endswith("chat_shadow.jsonl")
    with open(out_md, encoding="utf-8") as fp:
        assert "记忆 v2 灰度报告" in fp.read()


def test_main_without_shadow_file_is_safe(tmp_path):
    stats = main(["--base", str(tmp_path)])
    assert stats["turns"] == 0
    assert stats["source"].endswith("chat_shadow.jsonl")
