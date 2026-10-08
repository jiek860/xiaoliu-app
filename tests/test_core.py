# -*- coding: utf-8 -*-
"""核心功能单元测试 v3.0"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_defaults():
    from core.config import DEFAULTS
    assert "model_mode" in DEFAULTS
    print("✅ config defaults")


def test_safe_decorator():
    from core.safe import safe
    @safe
    def bad_func():
        raise ValueError("test")
    result = bad_func()
    assert result is None
    print("✅ safe decorator")


def test_safe_log_decorator():
    from core.safe import safe_log
    @safe_log
    def bad_func():
        raise ValueError("test")
    try:
        bad_func()
        assert False, "应该抛出异常"
    except ValueError:
        pass
    print("✅ safe_log decorator")


def test_logger():
    from core.logger import get_logger
    log = get_logger()
    log.info("test message")
    print("✅ logger")


def test_lazy_map():
    from core.lazy_config import LAZY_MAP
    assert len(LAZY_MAP) > 15
    print("✅ lazy map: %d 个模块" % len(LAZY_MAP))


def test_chat_store():
    from core.chat_store import ChatStore
    import tempfile
    db = os.path.join(tempfile.gettempdir(), "test_chats2.db")
    cs = ChatStore(db)
    cs.append("user1", "user", "hello", "session1")
    cs.append("user1", "assistant", "hi", "session1")
    msgs = cs.load("user1", "session1")
    assert len(msgs) >= 2
    print("✅ chat store")


def test_crypto():
    from core.crypto import encrypt, decrypt
    text = "测试加密123"
    enc = encrypt(text)
    dec = decrypt(enc)
    assert dec == text
    print("✅ crypto")


def test_license():
    from core.license_core import verify_license, get_machine_code
    assert callable(verify_license)
    assert callable(get_machine_code)
    print("✅ license core")


def test_vector_store():
    from core.vector_store import VectorStore
    assert VectorStore is not None
    print("✅ vector store")


def test_base_module():
    from modules.base import BaseModule
    class TestMod(BaseModule):
        NAME = "测试模块"
    m = TestMod()
    s = m.stats()
    assert "模块" in s
    assert s["模块"] == "测试模块"
    r = m.export_report()
    assert "报告" in r
    print("✅ base module")


def test_bot_server():
    from core.bot_server import BotServer
    assert BotServer is not None
    print("✅ bot server")


def test_rules_engine():
    from core.rules_engine import RuleEngine
    assert RuleEngine is not None
    print("✅ rules engine")


def test_trunk_init():
    from core.trunk import Trunk
    t = Trunk()
    assert len(t.modules) >= 5
    print("✅ trunk init: %d 个模块" % len(t.modules))


if __name__ == "__main__":
    test_config_defaults()
    test_safe_decorator()
    test_safe_log_decorator()
    test_logger()
    test_lazy_map()
    test_chat_store()
    test_crypto()
    test_license()
    test_vector_store()
    test_base_module()
    test_bot_server()
    test_rules_engine()
    test_trunk_init()
    print()
    print("=" * 40)
    print("ALL 13 TESTS PASSED")
    print("=" * 40)
