# -*- coding: utf-8 -*-
"""检查可选依赖运行环境。

用法：
    .runtime-venv\\Scripts\\python.exe tools\\check_optional_env.py
    .runtime-venv\\Scripts\\python.exe tools\\check_optional_env.py --playwright-smoke
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


OPTIONAL_MODULES = {
    "PIL": "图像处理",
    "pyautogui": "鼠标键盘",
    "pyperclip": "剪贴板",
    "win32api": "Windows API",
    "edge_tts": "语音合成",
    "pyaudio": "麦克风录音",
    "faster_whisper": "语音识别",
    "av": "音频解码",
    "huggingface_hub": "模型下载",
    "cv2": "OpenCV 视觉",
    "playwright": "浏览器自动化",
    "jedi": "代码补全",
    "pypdf": "PDF 解析",
    "docx": "Word 解析",
    "openpyxl": "Excel 解析",
    "pptx": "PPT 解析",
    "yaml": "YAML",
    "lxml": "XML/HTML",
    "onnxruntime": "VAD/ONNX",
}


def probe(import_modules=True):
    missing = []
    if import_modules:
        for name, feature in OPTIONAL_MODULES.items():
            try:
                importlib.import_module(name)
            except Exception as e:
                missing.append({"module": name, "feature": feature,
                                "error": str(e)[:160]})
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
    if not browser_path:
        browser_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "browsers")
    chromium = []
    if os.path.isdir(browser_path):
        chromium = [x for x in os.listdir(browser_path)
                    if x.startswith("chromium")]
    voice_backend = ""
    try:
        from modules.installed.voice import _detect_backend
        voice_backend = _detect_backend() or ""
    except Exception as e:
        # 静默是故意的：语音后端探测失败只表示当前环境不可用，
        # 由报告里的 voice_backend 为空体现，不应让整个可选环境检查崩溃。
        _ = e
    return {"ok": not missing,
            "missing": missing,
            "checked": len(OPTIONAL_MODULES),
            "playwright_browsers_path": browser_path,
            "chromium_dirs": chromium,
            "voice_backend": voice_backend}


def playwright_smoke():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<title>X6-OK</title><h1>ok</h1>")
        title = page.title()
        text = page.locator("h1").inner_text()
        browser.close()
    return title, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--playwright-smoke", action="store_true")
    a = ap.parse_args()
    r = probe()
    if a.playwright_smoke and not r["missing"]:
        try:
            title, text = playwright_smoke()
            r["playwright_smoke"] = {"ok": title == "X6-OK" and text == "ok",
                                     "title": title, "text": text}
            if not r["playwright_smoke"]["ok"]:
                r["ok"] = False
        except Exception as e:
            r["playwright_smoke"] = {"ok": False, "error": str(e)[:300]}
            r["ok"] = False
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("可选依赖检查: %d 项" % r["checked"])
        if r["missing"]:
            print("[X] 缺失:")
            for m in r["missing"]:
                print("    %-18s %s (%s)" % (m["module"], m["feature"], m["error"]))
        else:
            print("[OK] 可选 Python 包全部可导入")
        print("Chromium 目录:", ", ".join(r["chromium_dirs"]) or "未安装")
        print("语音后端:", r["voice_backend"] or "不可用")
        if "playwright_smoke" in r:
            print("Playwright 冒烟:", r["playwright_smoke"])
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())