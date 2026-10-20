# -*- coding: utf-8 -*-
"""登录窗口 - 账号+登录+激活"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt


def show_login_dialog(parent, trunk, base, on_login_success):
    """登录对话框。返回 True=登录成功"""
    # 登录前再次检查协议
    try:
        from core.agreement import Agreement
        from gui.agreement_dialog import AgreementDialog
        ag = Agreement(trunk)
        if ag.need_show():
            dlg = AgreementDialog(trunk, parent)
            dlg.exec_()
            if not dlg.agreed:
                return False
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass

    d = QDialog(parent)
    d.setWindowTitle("登录 - 小6智能助手")
    d.setFixedSize(380, 220)
    try:
        d.setWindowFlags(d.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    except Exception as e:
        _x6_swallowed(__name__, e)
    l = QVBoxLayout(d)
    l.addWidget(QLabel("请输入账号名："))
    u = QLineEdit()
    u.setPlaceholderText("输入你的账号名")
    l.addWidget(u)
    # 自动登录
    cache = os.path.join(base, "data", "login_cache.json")
    try:
        if os.path.exists(cache):
            cu = json.load(open(cache, encoding="utf-8")).get("u", "")
            if cu: u.setText(cu)
    except Exception as e:
        _x6_swallowed(__name__, e)
    result = {"ok": False}

    def do_login():
        r = trunk.call("auth", "login", u.text())
        ok = r.get("ok", False) if isinstance(r, dict) else bool(r)
        msg = r.get("msg", r.get("user", "")) if isinstance(r, dict) else str(r)
        if ok:
            username = r.get("user") or u.text().strip()
            json.dump({"u": username}, open(cache, "w", encoding="utf-8"))
            result["ok"] = True
            d.accept()
            try: on_login_success(username)
            except Exception as e:
                _x6_swallowed(__name__, e)
        else:
            QMessageBox.warning(d, "登录失败", msg)

    def do_activate():
        ad = QDialog(d)
        ad.setWindowTitle("激活账号")
        ad.setFixedSize(430, 290)
        al = QVBoxLayout(ad)
        al.addWidget(QLabel("账号名："))
        au = QLineEdit(u.text().strip())
        al.addWidget(au)
        al.addWidget(QLabel("激活码："))
        ak = QLineEdit()
        # 不能设成 Password 掩码：RSA 长码有 500 多字符，掩码之后没法核对贴对没有。
        ak.setPlaceholderText("粘贴激活码（Ctrl+V），短码约 45 字符，长码约 538 字符")
        al.addWidget(ak)

        # 实时识别贴进来的是什么码，贴错立刻能看出来
        hint = QLabel("")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b;font-size:11px;")
        al.addWidget(hint)

        def _classify():
            t = ak.text().strip()
            if not t:
                hint.setText("")
                return
            try:
                from core import license_core as lc
                raw = lc.parse_code(t)
                if len(raw) == lc.PAYLOAD_SIZE + 256:
                    hint.setText("✅ 识别为 RSA 长码（%d 字符），可以点激活了" % len(t))
                    hint.setStyleSheet("color:#16a34a;font-size:11px;")
                elif len(raw) == lc.PAYLOAD_SIZE + 6:
                    hint.setText("✅ 识别为 HMAC 短码（%d 字符）" % len(t))
                    hint.setStyleSheet("color:#16a34a;font-size:11px;")
                else:
                    hint.setText("⚠️ 长度不对（%d 字符），可能没贴全" % len(t))
                    hint.setStyleSheet("color:#d97706;font-size:11px;")
            except Exception:
                hint.setText("⚠️ 这串字符不像是激活码（共 %d 字符），检查是否贴漏或贴错"
                             % len(t))
                hint.setStyleSheet("color:#dc2626;font-size:11px;")

        ak.textChanged.connect(_classify)

        def do_act():
            r = trunk.call("auth", "activate", au.text(), ak.text())
            if r.get("ok"):
                QMessageBox.information(ad, "激活成功", r.get("msg", "激活成功"))
                u.setText(au.text().strip())
                ad.close()
            else:
                QMessageBox.warning(ad, "激活失败", r.get("msg", "激活失败"))
        al.addWidget(QPushButton("激活", clicked=do_act))
        al.addStretch(1)
        ad.exec_()

    row = QHBoxLayout()
    row.addWidget(QPushButton("登录", clicked=do_login))
    row.addWidget(QPushButton("激活", clicked=do_activate))
    l.addLayout(row)
    d.exec_()
    return result["ok"]
