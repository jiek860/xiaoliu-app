# -*- coding: utf-8 -*-
"""首次设置向导的布局不能被压扁（用户截图报的问题）

用户截图报的现象
----------------
「配置模型」页里，本地 Ollama 那行的「地址」和「模型」输入框被压成
几十像素，文字截成 `http://localhost:...` 和 `qwen2.5-coder...` 两条残影 ——
既没法核对也没法修改。

根因
----
那一行塞了 **4 个控件**：`地址：|输入框|模型：|输入框`，
两个输入框都设了 `stretch=1`。容器一窄，Qt 就把两个可拉伸项
双双压到最小宽度。（云端那边本来就是拆成两行的，本地这边漏了。）

本文件守住：**每个输入框在任何窗口尺寸下都得有能用的宽度**，
以及模型框是"检测到就自动填进去"的下拉框。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit  # noqa: E402
_app = QApplication.instance() or QApplication(sys.argv)

from tests.conftest import make_trunk               # noqa: E402

# 阈值：低于这个宽度就属于"文字会被截断、没法核对"的不可用状态
MIN_OK = 100

FIELDS = [("本地地址", "ed_ollama"), ("本地模型", "ed_local_model"),
          ("云端地址", "ed_cloud_url"), ("云端模型", "ed_cloud_model"),
          ("云端Key", "ed_cloud_key")]

_w = None


@pytest.fixture(scope="module")
def wiz():
    """建一次向导，并**切到第 2 页（模型配置）**

    ⚠️ 两个坑，都踩过：
    ① 不切页的话第 2 页的控件根本没被布局，测得的位置全是默认值 ——
       第一版 y 坐标两边都是 39，看着像"在同一行"，其实只是没布局。
    ② **必须把异步探测改成同步**：向导 `_prefill()` 会起一个
       `onboarding-probe` 线程去 urllib 请求 Ollama。测试跑完时这个
       daemon 线程可能还在跑，解释器拆除阶段撞上它 -> 整个 pytest
       进程硬崩（Windows fatal exception: access violation，
       退出码 0xC0000005，连是哪个用例都打不出来）。
       实测就是这么挂的：跑到 63% 直接没输出。
    """
    global _w
    if _w is None:
        import gui.onboarding_wizard as ow
        orig = ow.OnboardingWizard._refresh_local_status
        # 把"异步"强制走同步分支 —— 不起线程，也就没有拆除期崩溃
        ow.OnboardingWizard._refresh_local_status = (
            lambda self, async_=True: orig(self, async_=False))
        try:
            _w = ow.OnboardingWizard(make_trunk())
            _w.resize(760, 640)
            _w.show()
            _app.processEvents()
            for i in range(_w.pageIds().__len__()):
                if "模型" in (_w.page(i).title() or ""):
                    _w.setStartId(i)
                    break
            _w.restart()
            _app.processEvents()
            _app.processEvents()
        finally:
            ow.OnboardingWizard._refresh_local_status = orig
    return _w


def test_we_are_on_the_model_page(wiz):
    """先确认测的确实是那一页 —— 否则下面全是假通过"""
    assert "模型" in (wiz.currentPage().title() or ""), \
        "没切到模型配置页，测的是：%s" % wiz.currentPage().title()


@pytest.mark.parametrize("size", [(660, 520), (760, 560), (900, 640)])
def test_fields_are_wide_enough(wiz, size):
    """每个输入框在任何窗口尺寸下都不能被压成条

    这条就是抓用户截图里那个问题。
    """
    wiz.resize(*size)
    _app.processEvents()
    narrow = []
    for label, attr in FIELDS:
        w = getattr(wiz, attr).width()
        if w < MIN_OK:
            narrow.append("%s 只有 %d px" % (label, w))
    assert not narrow, (
        "窗口 %dx%d 时这些输入框被压扁了（文字会被截断）：%s\n"
        "改法：别把多个可拉伸输入框塞进同一行 —— 拆成各占一行，"
        "并给每个设 setMinimumWidth。"
        % (size[0], size[1], "；".join(narrow)))


def test_minimum_width_is_set_as_defense(wiz):
    """输入框要设最小宽度（防"窗口被拖窄"时的第二层保护）

    为什么要单独测这个：拆成两行之后，正常尺寸下输入框本来就占满整行，
    所以 `setMinimumWidth` 在当前窗口尺寸范围内**测不出差别** ——
    负向测试把这几行删掉，660~900 的用例全都照样通过（这是真的，
    不是测试写得不好；它就是一层冗余防御）。

    但它管的是真实场景里会遇到的两种窄：
        · 用户把窗口拖到很小
        · 系统字体放大，导致布局需求变宽
    没有它，输入框会退化成没法核对的一条。

    这条**只读属性**，不改窗口（第一版我在这里折腾 resize/setFixedWidth，
    结果把控件状态搞乱，基线自己就挂了）。
    """
    for label, attr in FIELDS:
        w = getattr(wiz, attr).minimumWidth()
        assert w >= MIN_OK, (
            "%s 的最小宽度是 %d px（应 >= %d）—— 窗口拖窄时它会退化成条。\n"
            "改法：给每个输入框加 setMinimumWidth(240)。"
            % (label, w, MIN_OK))


def test_local_row_is_split_not_crowded(wiz):
    """本地那行不能又是"4 个控件挤一行"

    结构检查（比逐尺寸量宽度更早发现问题）：地址和模型必须**各占一行**，
    也就是它们的 y 坐标不能相同。
    """
    y_addr = wiz.ed_ollama.mapTo(wiz, wiz.ed_ollama.rect().topLeft()).y()
    y_model = wiz.ed_local_model.mapTo(wiz, wiz.ed_local_model.rect().topLeft()).y()
    assert y_addr != y_model, \
        "地址和模型还在同一行（y 都是 %d）—— 窄窗口下必然被压" % y_addr


def test_cloud_model_and_key_are_on_separate_rows(wiz):
    """云端的模型和 Key 也要各占一行"""
    y_m = wiz.ed_cloud_model.mapTo(wiz, wiz.ed_cloud_model.rect().topLeft()).y()
    y_k = wiz.ed_cloud_key.mapTo(wiz, wiz.ed_cloud_key.rect().topLeft()).y()
    assert y_m != y_k, "云端模型和 Key 还在同一行（y 都是 %d）" % y_m


def test_local_model_is_a_editable_combobox(wiz):
    """模型框要是可编辑下拉框 —— 检测到就自动列出来，不用手打

    手打模型名错一个字符，表现就是"发消息没反应"，用户很难自己查出来。
    同类程序的做法是检测到模型后自动刷进下拉框。
    """
    assert isinstance(wiz.ed_local_model, QComboBox), \
        "模型框不是下拉框（用户只能手打模型名）"
    assert wiz.ed_local_model.isEditable(), \
        "下拉框不可编辑 —— 自己训的模型名就填不进去了"


def test_detected_models_are_filled_in(wiz):
    """检测到 Ollama 里的模型后，要自动出现在下拉框里"""
    from core import model_setup
    url = wiz.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA
    info = model_setup.probe_ollama(url, timeout=3)
    if not info.get("reachable") or not info.get("models"):
        pytest.skip("本机 Ollama 没在跑或没有模型，跳过")
    wiz._apply_local_status(info, url)
    _app.processEvents()
    got = [wiz.ed_local_model.itemText(i)
           for i in range(wiz.ed_local_model.count())]
    missing = [m for m in info["models"] if m not in got]
    assert not missing, "检测到的模型没进下拉框：%s" % missing


def test_selected_model_survives_refresh(wiz):
    """已经选好的模型，重新检测后不能被冲掉

    （每次刷新都把用户的选择重置成第一项，是很烦人的体验。）
    """
    if wiz.ed_local_model.count() < 2:
        pytest.skip("候选不足 2 个，跳过")
    target = wiz.ed_local_model.itemText(1)
    wiz.ed_local_model.setCurrentText(target)
    from core import model_setup
    info = model_setup.probe_ollama(
        wiz.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA, timeout=3)
    if not info.get("reachable"):
        pytest.skip("Ollama 没在跑")
    wiz._apply_local_status(info, info.get("url", ""))
    assert wiz.ed_local_model.currentText() == target, \
        "重新检测把用户选的模型冲掉了"


def test_missing_ollama_gives_actionable_steps(wiz):
    """连不上 Ollama 时，要给**能照着做**的步骤，不是一句"去装个 Ollama"

    对比同类程序：它们把下载做成程序内一键完成。
    小6 这边还是引导用户自己去官网 —— 那至少要把
    "下载地址 / 跑什么命令 / 多大 / 装完回哪一步" 写清楚。
    """
    wiz._apply_local_status(
        {"reachable": False, "models": [], "error": "测试"}, "http://x")
    _app.processEvents()
    txt = wiz.lbl_local_howto.text()
    assert "ollama.com/download" in txt or "下载" in txt, "没给下载地址：%s" % txt
    assert "ollama run" in txt, "没给要跑的命令：%s" % txt
    assert "重新检测" in txt, "没说装完回哪一步：%s" % txt
    assert "2GB" in txt or "进度" in txt, "没说明要等多久/多大：%s" % txt


def test_status_label_has_no_truncation_marker(wiz):
    """状态栏文字里不该出现被截断的省略号残影（那种"看起来就是坏的"）"""
    wiz._apply_local_status(
        {"reachable": False, "models": [], "error": "x"}, "http://localhost")
    txt = wiz.lbl_local_status.text()
    assert "http://localhost" in txt, \
        "连不上时没把地址说出来（用户没法核对填的对不对）：%s" % txt
