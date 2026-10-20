# -*- coding: utf-8 -*-
"""文档解析：PDF / Word / Excel / PPT / Markdown / HTML / 文本。"""
import os
import re


def _clean(text):
    text = str(text or "").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse(path):
    path = os.path.abspath(str(path or ""))
    if not os.path.isfile(path):
        return {"ok": False, "error": "文件不存在", "path": path}
    try:
        if os.path.getsize(path) > 50 * 1024 * 1024:
            return {"ok": False, "error": "文件超过 50MB，已拒绝解析",
                    "path": path}
    except OSError:
        pass
    ext = os.path.splitext(path)[1].lower()
    text = ""
    meta = {"title": os.path.basename(path), "source": path}
    try:
        if ext in (".txt", ".md", ".log", ".csv", ".json", ".yaml", ".yml"):
            text = open(path, encoding="utf-8", errors="replace").read()
        elif ext in (".html", ".htm"):
            raw = open(path, encoding="utf-8", errors="replace").read()
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw,
                          flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
        elif ext == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader
            reader = PdfReader(path)
            pages = []
            for i, p in enumerate(reader.pages, 1):
                t = p.extract_text() or ""
                pages.append({"page": i, "text": _clean(t)})
            text = "\n\n".join(p["text"] for p in pages)
            meta["pages"] = pages
        elif ext == ".docx":
            from docx import Document
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
        elif ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            rows = []
            for ws in wb.worksheets:
                rows.append("## " + ws.title)
                for row in ws.iter_rows(values_only=True):
                    vals = [str(x) for x in row if x is not None]
                    if vals:
                        rows.append(" | ".join(vals))
            text = "\n".join(rows)
        elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"):
            try:
                from PIL import Image
                import pytesseract
            except ImportError:
                return {"ok": False,
                        "error": "图片 OCR 需要 Pillow + pytesseract（并安装 Tesseract）",
                        "path": path}
            img = Image.open(path)
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            meta["ocr"] = True
        elif ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(path)
            parts = []
            for i, slide in enumerate(prs.slides, 1):
                parts.append("## Slide %d" % i)
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text:
                        parts.append(shape.text)
            text = "\n".join(parts)
        else:
            return {"ok": False, "error": "暂不支持的文件类型: " + ext,
                    "path": path}
    except ImportError as e:
        return {"ok": False, "error": "缺少文档解析依赖: " + str(e)[:80],
                "path": path}
    except Exception as e:
        return {"ok": False, "error": "解析失败: " + str(e)[:120],
                "path": path}
    text = _clean(text)
    return {"ok": True, "path": path, "text": text,
            "chars": len(text), "metadata": meta}


def chunk_text(text, chunk_size=800, overlap=120):
    text = _clean(text)
    if not text:
        return []
    chunks = []
    step = max(1, chunk_size - overlap)
    for i in range(0, len(text), step):
        piece = text[i:i + chunk_size].strip()
        if piece:
            chunks.append({"id": "chunk_%d" % (len(chunks) + 1),
                           "text": piece, "offset": i})
        if i + chunk_size >= len(text):
            break
    return chunks
