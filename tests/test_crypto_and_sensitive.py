# -*- coding: utf-8 -*-
"""加密与敏感信息处理的测试（这两个模块此前**从没被测试碰过**）

为什么优先补这两个
------------------
    memory_crypto      加密 —— 坏了用户的记忆就取不回来
    sensitive_detector 安全 —— 该脱敏的没脱，等于泄露

实测（2026-10-13）它们在所有测试文件里出现次数为 0。
"""
import json
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.memory_crypto import MemoryCrypto          # noqa: E402
from core.sensitive_detector import SensitiveDetector  # noqa: E402


class _T:
    def __init__(self, base):
        self.base = base


def _mkbase(cards=3):
    d = tempfile.mkdtemp(prefix="x6crypto_")
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    p = os.path.join(d, "data", "memory_cards.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for i in range(cards):
            f.write(json.dumps({"facts": ["第%d条记忆" % i], "time": 9e9},
                               ensure_ascii=False) + "\n")
    return d, p


# ══════════════════════════════════════════════════════════════
# memory_crypto
# ══════════════════════════════════════════════════════════════
def test_export_then_import_roundtrip():
    """加密导出 -> 解密导入，内容要一模一样"""
    src, _p = _mkbase(3)
    dst, dstp = _mkbase(0)                 # 目标库先清空
    os.remove(dstp)
    out = os.path.join(tempfile.gettempdir(), "x6_mem_test.bin")
    try:
        mc1 = MemoryCrypto(_T(src))
        r = mc1.export_encrypted(out, "正确密码123")
        assert r.get("ok") is True, r
        assert r.get("条数") == 3, r
        assert os.path.exists(out) and os.path.getsize(out) > 0

        mc2 = MemoryCrypto(_T(dst))
        r2 = mc2.import_encrypted(out, "正确密码123")
        assert r2.get("ok") is True, r2
        assert r2.get("条数") == 3, r2
        content = open(dstp, encoding="utf-8").read()
        for i in range(3):
            assert "第%d条记忆" % i in content, "导入后少了第 %d 条" % i
    finally:
        if os.path.exists(out):
            os.remove(out)


def test_export_does_not_leak_plaintext():
    """导出文件里不能有明文（这是加密的全部意义）"""
    src, _p = _mkbase(2)
    out = os.path.join(tempfile.gettempdir(), "x6_mem_test2.bin")
    try:
        MemoryCrypto(_T(src)).export_encrypted(out, "pw")
        raw = open(out, "rb").read()
        assert "第0条记忆".encode("utf-8") not in raw, \
            "导出文件里能直接搜到明文 —— 没加密"
        assert b"facts" not in raw, "结构字段都还在明文里"
    finally:
        if os.path.exists(out):
            os.remove(out)


def test_wrong_password_gives_clear_error_not_json_crash():
    """密码错要给**说得清的错误**，不能抛 JSON 解析异常

    原来 import_encrypted 把"AES 解密失败"和"没装 cryptography"
    混在同一个 except 里 —— 密码错也会掉进 XOR 回退分支，
    XOR 解出乱码 -> json.loads 抛异常 -> 用户看到的是
    "Expecting value: line 1 column 1"，完全看不出是密码错了。
    """
    src, _p = _mkbase(2)
    out = os.path.join(tempfile.gettempdir(), "x6_mem_test3.bin")
    dst, _dp = _mkbase(0)
    try:
        MemoryCrypto(_T(src)).export_encrypted(out, "对的密码")
        mc = MemoryCrypto(_T(dst))
        try:
            r = mc.import_encrypted(out, "错的密码")
        except Exception as e:
            pytest.fail("密码错时抛了原始异常（%s: %s），"
                        "应返回可读的错误" % (type(e).__name__, str(e)[:50]))
        assert isinstance(r, dict), r
        assert r.get("ok") is False, "密码错却报成功：%s" % r
        msg = str(r)
        # 必须**点名是密码不对** —— 笼统的"解密失败"不够：
        # 用户看到"解密失败：InvalidTag"根本不知道该做什么。
        # （第一版断言写成 `"密码" in msg or "解密" in msg`，
        #   结果"解密失败"这四个字就满足了，负向测试直接漏过。）
        assert "密码" in msg, \
            "错误信息没点名是密码问题，实际：%s" % msg
        assert "InvalidTag" not in msg, \
            "错误信息里别把原始异常名甩给用户：%s" % msg
    finally:
        if os.path.exists(out):
            os.remove(out)


def test_export_reports_skipped_bad_lines():
    """导出时跳过的坏行要报出来（和 auto_organize 同一类问题）

    原来导出的"条数"只数**解析成功**的行，坏行静默跳过 ——
    用户以为导出完整。
    """
    d, p = _mkbase(2)
    with open(p, "a", encoding="utf-8") as f:
        f.write("这是坏行\n")
        f.write("{不完整的 json\n")
    out = os.path.join(tempfile.gettempdir(), "x6_mem_test4.bin")
    try:
        r = MemoryCrypto(_T(d)).export_encrypted(out, "pw")
        assert r.get("条数") == 2, r
        assert r.get("跳过") == 2, \
            "坏行没报出来（导出会看起来完整）：%s" % r
    finally:
        if os.path.exists(out):
            os.remove(out)


def test_export_to_bad_path_does_not_crash_process():
    """写到不可写路径要返回错误，不能把异常抛穿"""
    src, _p = _mkbase(1)
    mc = MemoryCrypto(_T(src))
    try:
        r = mc.export_encrypted("Z:\\不存在的盘\\x.bin", "pw")
        assert isinstance(r, dict), r
    except Exception as e:
        pytest.fail("写失败时抛了异常：%s: %s" % (type(e).__name__, str(e)[:50]))


# ══════════════════════════════════════════════════════════════
# sensitive_detector
# ══════════════════════════════════════════════════════════════
def test_detects_phone_in_chinese_context():
    """中文语境下也要能认出手机号（这是这个模块历史上失效过的地方）"""
    sd = SensitiveDetector()
    found = sd.detect("我的手机号是13812345678，记一下")
    assert any(f["type"] == "手机号" for f in found), \
        "中文语境下没认出手机号：%s" % found


@pytest.mark.parametrize("text,kind", [
    ("身份证 110101199003071234 请收好", "身份证"),
    ("邮箱是 someone@example.com", "邮箱"),
    ("key=sk-abcdefghijklmnopqrstuvwx", "API密钥"),
])
def test_detects_each_pattern(text, kind):
    sd = SensitiveDetector()
    found = sd.detect(text)
    assert any(f["type"] == kind for f in found), \
        "%s 没被认出来：%s" % (kind, found)


def test_detect_result_does_not_contain_the_secret():
    """⚠️ **检测结果里不能带上敏感信息本身**

    原来 detect() 返回 {"value": m.group()[:20] + "..."} ——
    也就是把密钥的前 20 个字符原样带出来，而后 20 位往往已经是
    可用的密钥片段。这个结果一旦进日志、发给模型、或显示在界面上，
    **"检测敏感信息"这个动作本身就成了泄露渠道**。

    正确做法：只报类型与位置/长度，值本身给个不可还原的提示。
    """
    sd = SensitiveDetector()
    secret = "sk-abcdefghijklmnopqrstuvwx"
    found = sd.detect("我的 key=%s 别外传" % secret)
    assert found, "没检测到密钥"
    blob = json.dumps(found, ensure_ascii=False)
    assert secret not in blob, "检测结果里带了完整密钥：%s" % blob
    assert secret[:16] not in blob, \
        "检测结果里带了密钥前 16 位（已足够危险）：%s" % blob


def test_mask_does_not_leave_short_secrets_mostly_visible():
    """较短但**确实匹配到模式**的敏感串，不能被"只遮中间"漏掉大部分

    ⚠️ 第一版这里拿 `1381234`（7 位）当输入 —— 那**不是手机号**
    （手机号是 11 位），根本没匹配到任何模式，所以原样返回是**正确行为**，
    我的断言写错了。改用真正会匹配的短串：`password=abc123` 这类。
    """
    sd = SensitiveDetector()
    raw = "password=abc123"
    masked = sd.mask(raw)
    assert "abc123" not in masked, "密码值没被遮掉：%r" % masked
    # 被遮掉的字符要占大多数
    visible = sum(1 for c in masked if c.isalnum() and c not in "password")
    assert visible <= 3, "遮完还剩太多可见字符：%r" % masked


def test_short_id_number_is_fully_masked():
    """4 位以内的匹配内容应当全遮"""
    sd = SensitiveDetector()
    # 银行卡最少 16 位，身份证 18 位 —— 用密码这种短的来验全遮
    m = sd.mask("pwd=1234")
    assert "1234" not in m, "短密码没被全遮：%r" % m


def test_mask_keeps_readable_for_normal_phone():
    """正常长度的手机号，脱敏后要还能看出是同一类信息"""
    sd = SensitiveDetector()
    m = sd.mask("电话 13812345678")
    assert "*" in m, "没脱敏：%s" % m
    assert "13812345678" not in m
    assert len([c for c in m if c.isdigit()]) <= 7, \
        "露出的数字太多：%s" % m


def test_check_and_mask_shape():
    sd = SensitiveDetector()
    r = sd.check_and_mask("没有敏感信息的一句话")
    assert r["safe"] is True and r["found"] == []
    r2 = sd.check_and_mask("手机 13812345678")
    assert r2["safe"] is False
    assert "13812345678" not in r2["masked"]


def test_mask_is_idempotent():
    """已经脱敏过的文本再脱一次不该变样（否则会越遮越乱）"""
    sd = SensitiveDetector()
    once = sd.mask("手机 13812345678")
    twice = sd.mask(once)
    assert once == twice, "%r -> %r" % (once, twice)
