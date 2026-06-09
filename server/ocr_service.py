# -*- coding: utf-8 -*-
"""
OCR 流水线服务 — pdfplumber → EasyOCR → jieba → 结构化 JSON。

提供两个核心函数：
- process_file()  — 接收文件路径，返回结构化成分+宣称
- extract_text()  — 仅返回纯文本（用于直接提交场景）
"""

import os
import re
import json
from pathlib import Path
from typing import Optional

# ─── 配置 ───
OCR_CACHE_DIR = Path(__file__).parent.parent / "ocr_output"


def process_file(file_path: str) -> dict:
    """处理产品标签文件，提取结构化信息。

    Args:
        file_path: PDF/PNG/JPG 文件路径

    Returns:
        {
            "success": bool,
            "raw_text": str,           # OCR 原始文本
            "ingredients": list[str],  # 成分列表
            "claims": list[str],       # 检测到的功效宣称
            "error": str | None
        }
    """
    if not os.path.exists(file_path):
        return {"success": False, "raw_text": "", "ingredients": [], "claims": [], "error": f"文件不存在: {file_path}"}

    ext = Path(file_path).suffix.lower()

    try:
        if ext == '.pdf':
            raw_text = _pdf_to_text(file_path)
        elif ext in ('.png', '.jpg', '.jpeg', '.bmp', '.tiff'):
            raw_text = _image_to_text(file_path)
        else:
            return {"success": False, "raw_text": "", "ingredients": [], "claims": [],
                    "error": f"不支持的文件格式: {ext}，仅支持 PDF/PNG/JPG"}

        if not raw_text.strip():
            return {"success": False, "raw_text": raw_text, "ingredients": [], "claims": [],
                    "error": "OCR 未识别到任何文字"}

        # jieba 分词 + 关键词提取
        ingredients = _extract_ingredients(raw_text)
        claims = _extract_claims(raw_text)

        return {
            "success": True,
            "raw_text": raw_text.strip(),
            "ingredients": ingredients,
            "claims": claims,
            "error": None,
        }
    except Exception as e:
        return {"success": False, "raw_text": "", "ingredients": [], "claims": [], "error": str(e)}


def extract_text(file_path: str) -> str:
    """仅提取纯文本，不做结构化分析。用于直接文本提交模式。"""
    result = process_file(file_path)
    return result.get("raw_text", "")


# ─── PDF 处理 ───

def _pdf_to_text(file_path: str) -> str:
    """pdfplumber 提取文本 + EasyOCR 图片识别，合并结果。"""
    import pdfplumber

    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            # 优先使用 pdfplumber 原生文本提取
            page_text = page.extract_text()
            if page_text and len(page_text.strip()) > 20:
                text_parts.append(page_text)
            else:
                # 纯图片页面 → EasyOCR
                img_path = str(OCR_CACHE_DIR / f"page_{i+1:02d}.png")
                if not os.path.exists(img_path):
                    img = page.to_image(resolution=300)
                    img.save(img_path)
                ocr_text = _easyocr_read(img_path)
                text_parts.append(ocr_text)

    return "\n".join(text_parts)


# ─── 图片处理 ───

def _image_to_text(file_path: str) -> str:
    """图片直接走 EasyOCR。"""
    return _easyocr_read(file_path)


def _easyocr_read(image_path: str) -> str:
    """EasyOCR 读取单张图片。"""
    import easyocr

    # 延迟初始化 reader（单例）
    if not hasattr(_easyocr_read, "_reader"):
        _easyocr_read._reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)

    reader = _easyocr_read._reader
    results = reader.readtext(image_path, detail=0, paragraph=True)
    return "\n".join(results)


# ─── jieba 成分/宣称提取 ───

# 常见成分相关关键词（用于 jieba 后的成分识别）
INGREDIENT_SIGNALS = {
    "醇", "酸", "铵", "胺", "酯", "酮", "酚", "醛", "醚",
    "盐", "钠", "钾", "钙", "锌", "银", "碘", "氯",
    "提取物", "精华", "精油", "甘油", "丙二醇", "乙醇", "水杨酸",
    "表面活性剂", "防腐剂", "香精", "香料", "色素",
}

# 常见功效宣称关键词
CLAIM_PATTERNS = [
    r'消毒', r'杀菌', r'抑菌', r'抗菌', r'灭菌',
    r'清洁', r'去污', r'除菌', r'除螨', r'除臭',
    r'抗病毒', r'防霉', r'防蛀', r'驱虫',
    r'止痒', r'舒缓', r'修复', r'护理', r'滋润',
    r'治疗', r'预防',
]


def _extract_ingredients(text: str) -> list[str]:
    """用 jieba 分词 + 成分信号词识别成分列表。"""
    try:
        import jieba
    except ImportError:
        return _fallback_extract(text, INGREDIENT_SIGNALS)

    words = jieba.lcut(text)
    # 取长度 >= 2 且含成分信号词的去重词
    seen = set()
    ingredients = []
    for w in words:
        w = w.strip()
        if len(w) < 2 or w in seen:
            continue
        if any(signal in w for signal in INGREDIENT_SIGNALS):
            seen.add(w)
            ingredients.append(w)

    return ingredients


def _extract_claims(text: str) -> list[str]:
    """用正则匹配功效宣称关键词。"""
    claims = set()
    for pattern in CLAIM_PATTERNS:
        if re.search(pattern, text):
            claims.add(re.search(pattern, text).group())
    return sorted(claims)


def _fallback_extract(text: str, signals: set) -> list[str]:
    """无 jieba 时的备用提取——按常见分隔符切分后过滤。"""
    # 常见成分分隔：、，, ；; 换行 空格
    parts = re.split(r'[、，,；;。\n\s]+', text)
    parts = [p.strip() for p in parts if len(p.strip()) >= 2]
    return [p for p in parts if any(s in p for s in signals)]


# ─── 模块自检 ───

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = process_file(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("用法: python ocr_service.py <文件路径>")
