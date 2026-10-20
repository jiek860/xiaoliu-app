# -*- coding: utf-8 -*-
"""默认通知凭据的静态加密存储。

注意
----
这里不是把密钥交给服务器保管，而是避免默认凭据以明文出现在
源码/默认配置和普通文本扫描中。程序运行时必须在内存里还原明文才能
调用飞书接口，因此本方案只能提高静态读取门槛，不能抵御能逆向二进制
或 dump 进程内存的攻击者。

新凭据请优先写入用户本机的 data/config.json（Windows 下由 DPAPI 加密），
本文件仅保留产品默认值。
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "x6enc:v1:"
_AAD = b"x6-default-secrets-v1"
_KEY = bytes.fromhex("a8eb9dbbf427bbaaa2fb26954396d91223978ef19df41463a30086e1d3d2434a")

# 只保存密文，不保存明文。
_FEISHU_WEBHOOK = "x6enc:v1:QvbBAueCjihbA4W5sOunot_70pS8U3pEPLhra0v1djohJTq50BLVTsT1K-aZsLx8Y_WhcqTgNr1aHAQm_vA_ann0R7n6_H-lkG6_sa-DPTQgmp-RFeJSnAE7xHPOlg0ElT5b3f7YjLADOSvc9g=="
_FEISHU_SECRET = "x6enc:v1:XdhGP6IkjMS9OUVjyegrsI2sxdE_YDvLEkY2EvoprBA8ddS1DNj-CYFKp6FSdAofmhk="


def decrypt_text(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        raw = base64.urlsafe_b64decode(value[len(PREFIX):].encode("ascii"))
        nonce, ciphertext = raw[:12], raw[12:]
        return AESGCM(_KEY).decrypt(nonce, ciphertext, _AAD).decode("utf-8")
    except Exception:
        return value


def encrypt_text(text):
    if not isinstance(text, str) or not text:
        return text
    nonce = os.urandom(12)
    ct = AESGCM(_KEY).encrypt(nonce, text.encode("utf-8"), _AAD)
    return PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_tree(obj):
    if isinstance(obj, dict):
        return {k: decrypt_tree(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decrypt_tree(v) for v in obj]
    if isinstance(obj, str) and obj.startswith(PREFIX):
        return decrypt_text(obj)
    return obj


def get_default_feishu_webhook():
    return decrypt_text(_FEISHU_WEBHOOK)


def get_default_feishu_secret():
    return decrypt_text(_FEISHU_SECRET)
