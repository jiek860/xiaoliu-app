# -*- coding: utf-8 -*-
"""B8: 测试 crypto 加解密往返"""
import unittest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.crypto import encrypt, decrypt, hash_password, verify_password


class TestCrypto(unittest.TestCase):
    def test_encrypt_decrypt(self):
        """加密解密往返"""
        text = "测试敏感信息123"
        enc = encrypt(text)
        dec = decrypt(enc)
        self.assertEqual(dec, text)
        print("✅ 加解密往返正常")

    def test_hash_password(self):
        """密码哈希验证"""
        h = hash_password("mypassword")
        self.assertTrue(verify_password("mypassword", h))
        self.assertFalse(verify_password("wrongpassword", h))
        print("✅ 密码哈希验证正常")


if __name__ == "__main__":
    unittest.main()
