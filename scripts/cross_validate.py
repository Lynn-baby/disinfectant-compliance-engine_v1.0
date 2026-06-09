"""
交叉验证脚本：LlamaParse vs EasyOCR 对比 GB 38850 成分清单解析质量。

三指标策略：
  1. 相对召回率 — 以两引擎并集为近似真值，各自计算召回
  2. 一致率 — 两引擎都提取到的条目中，CAS+名称完全一致的占比
  3. 冲突率 — 都提取到但字段不一致的条目占比 → 人工复核清单

用法：
  python cross_validate.py

依赖：
  pip install easyocr pdfplumber --break-system-packages
"""

import json
import os
import ssl
import certifi

# 修复 macOS Python 3.14 的 SSL 证书路径
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
import os
import re
from pathlib import Path
from collections import defaultdict

# ─── 配置 ─────────────────────────────────────────

PDF_PATH = "/Users/ml/Desktop/GB 38850-2020 消毒剂原料清单及禁限用物质.pdf"
LLAMAPARSE_MD = "/Users/ml/Desktop/ai_sale_agent001/parsed_docs/GB 38850-2020 消毒剂原料清单及禁限用物质.md"
OUT_DIR = Path("/Users/ml/Desktop/ai_sale_agent001/ocr_output")
CACHE_FILE = OUT_DIR / "easyocr_raw.json"

# Table 1 页面范围 (1-indexed)
TABLE1_PAGES = [6, 7, 8, 9]
# Table 2 页面范围
TABLE2_PAGES = [9, 10, 11, 12, 13]


# ─── Step 1: EasyOCR 解析 ─────────────────────────

def run_easyocr():
    """对所有页面跑 EasyOCR，缓存结果到 JSON。"""
    import easyocr
    import pdfplumber

    if CACHE_FILE.exists():
        print(f"[EasyOCR] 使用缓存: {CACHE_FILE}")
        return json.loads(CACHE_FILE.read_text())

    print("[EasyOCR] 初始化 reader (ch_sim + en, CPU)...")
    reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)

    # 先转图片
    print("[EasyOCR] 转换 PDF 页面为图片 (300 DPI)...")
    image_paths = []
    with pdfplumber.open(PDF_PATH) as pdf:
        for i, page in enumerate(pdf.pages):
            img_path = str(OUT_DIR / f"page_{i+1:02d}.png")
            if not os.path.exists(img_path):
                img = page.to_image(resolution=300)
                img.save(img_path)
            image_paths.append(img_path)

    # OCR 每一页
    all_results = {}
    for i, img_path in enumerate(image_paths, 1):
        print(f"[EasyOCR] 处理第 {i}/{len(image_paths)} 页...")
        result = reader.readtext(img_path, detail=1, paragraph=False)
        # 只保留 [confidence, text, bbox] 的简化格式
        simplified = []
        for bbox, text, conf in result:
            if conf > 0.3:
                x = float(bbox[0][0])
                y = float(bbox[0][1])
                w = float(bbox[2][0]) - x
                h = float(bbox[2][1]) - y
                simplified.append({
                    "text": text.strip(),
                    "conf": round(float(conf), 3),
                    "x": round(x, 1),
                    "y": round(y, 1),
                    "w": round(w, 1),
                    "h": round(h, 1),
                })
        all_results[str(i)] = simplified

    CACHE_FILE.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"[EasyOCR] 结果已缓存: {CACHE_FILE}")
    return all_results


# ─── Step 2: 行分组 — 把 OCR 文本块按 y 坐标聚合成行 ──

def group_into_rows(page_results, y_tolerance=12):
    """将一页的文本块按 y 坐标聚合成行。"""
    if not page_results:
        return []

    # 按 y 排序
    sorted_blocks = sorted(page_results, key=lambda b: b["y"])

    rows = []
    current_row = [sorted_blocks[0]]
    current_y = sorted_blocks[0]["y"]

    for block in sorted_blocks[1:]:
        if abs(block["y"] - current_y) <= y_tolerance:
            current_row.append(block)
        else:
            # 当前行按 x 排序
            current_row.sort(key=lambda b: b["x"])
            rows.append(current_row)
            current_row = [block]
            current_y = block["y"]

    if current_row:
        current_row.sort(key=lambda b: b["x"])
        rows.append(current_row)

    return rows


# ─── Step 3: 从 OCR 行中提取结构化成分记录 ──────────

CAS_PATTERN = re.compile(r'\b\d{2,8}[-—–]\d{2,4}[-—–]\d{1,4}\b')
# 宽松 CAS 模式 — OCR 可能把连字符识别错
CAS_PATTERN_LOOSE = re.compile(r'\b(\d{2,8})[-—–\s](\d{2,4})[-—–\s](\d{1,4})\b')


def extract_cas(text):
    """从文本中提取 CAS 编码，返回标准化格式 (xxx-xx-x)。"""
    m = CAS_PATTERN.search(text)
    if m:
        return m.group(0).replace('–', '-').replace('—', '-')
    return None


def is_header_or_noise(row_text, min_chinese=1, max_ratio=0.6):
    """判断一行是否是表头或噪声（过多英文/数字，过少中文）。"""
    if not row_text:
        return True
    chinese_chars = sum(1 for c in row_text if '一' <= c <= '鿿')
    if chinese_chars < min_chinese:
        return True
    # 如果中文占比太低（如纯英文行），跳过
    total_chars = len(row_text.replace(' ', ''))
    if total_chars > 0 and chinese_chars / total_chars < max_ratio:
        # 但短行（<20 chars）可能是正常的化学名，不跳过
        if total_chars > 20:
            return True
    return False


def extract_records_from_page(page_results, table_label="unknown"):
    """从单页 OCR 结果中提取成分记录。"""
    rows = group_into_rows(page_results)
    records = []

    for row_blocks in rows:
        # 行文本 = 所有块的拼接
        row_text = " ".join(b["text"] for b in row_blocks)

        # 跳过空行、表头、噪声
        if not row_text.strip():
            continue
        if is_header_or_noise(row_text):
            # 但有 CAS 号的除外（可能是英文名称为主的成分行）
            if not extract_cas(row_text):
                continue

        # 尝试提取结构化字段
        cas = extract_cas(row_text)
        # 用第一个文本块（通常是序号或中文名）
        first_text = row_blocks[0]["text"] if row_blocks else ""
        chinese_name = ""
        for b in row_blocks:
            t = b["text"]
            # 中文名称: 中文字符占主要且不是 CAS
            chinese_count = sum(1 for c in t if '一' <= c <= '鿿')
            if chinese_count >= 2 and not extract_cas(t):
                chinese_name = t
                break

        if cas or (chinese_name and len(chinese_name) >= 2):
            records.append({
                "row_text": row_text[:200],
                "chinese_name": chinese_name,
                "cas": cas or "",
                "source_page_table": table_label,
            })

    return records


# ─── Step 4: 从 LlamaParse Markdown 提取记录 ───────

def extract_llamaparse_records(md_path):
    """从 LlamaParse 解析的 Markdown 中提取结构化成分列表。"""
    content = Path(md_path).read_text(encoding='utf-8')

    records = []
    seen_cas = set()

    # 匹配 Markdown 表格行: | 序号 | 中文名 | 英文名 | CAS | 范围 |
    # Table rows start with | number |
    table_pattern = re.compile(
        r'^\|\s*(\d+)\s*\|'
        r'\s*(.+?)\s*\|'
        r'\s*(.+?)\s*\|'
        r'\s*(.+?)\s*\|'
        r'\s*(.+?)\s*\|',
        re.MULTILINE
    )

    for m in table_pattern.finditer(content):
        seq = m.group(1)
        chinese_name = m.group(2).strip()
        english_name = m.group(3).strip()
        cas_raw = m.group(4).strip()
        usage = m.group(5).strip()

        # 清理中文名中的 <br/> 标签
        chinese_name_clean = re.sub(r'<br/?>', '', chinese_name).strip()
        # 清理 CAS 中的 <br/> 和换行
        cas_clean = re.sub(r'<br/?>|\n', '', cas_raw).strip()

        # 提取纯 CAS 号
        cas_match = CAS_PATTERN.search(cas_clean)
        cas = cas_match.group(0).replace('–', '-').replace('—', '-') if cas_match else cas_clean

        if cas and cas != '——' and cas != '--':
            if cas in seen_cas:
                continue  # 跨页继续表的重复行
            seen_cas.add(cas)

        records.append({
            "seq": seq,
            "chinese_name": chinese_name_clean,
            "english_name": english_name.strip(),
            "cas": cas,
            "usage": usage.strip(),
        })

    return records


# ─── Step 5: 条目对齐与匹配 ────────────────────────

def normalize_cas(cas):
    """CAS 标准化：去空格，统一连字符，处理 OCR 多 CAS 格式。"""
    if not cas or cas in ('——', '--', ''):
        return None
    # 处理 OCR 中的混乱格式
    cas = cas.strip().replace('–', '-').replace('—', '-').replace(' ', '')
    cas = cas.replace('<br/>', '').replace('\n', '')
    # 有时 OCR 输出类似 "8001-54-5/63449-41-2" -> 取第一个
    cas = cas.split('/')[0]
    return cas.strip()


def match_by_cas(ocr_records, llama_records):
    """以 CAS 编码为主键匹配两引擎的记录。"""
    # 建索引
    llama_by_cas = {}
    llama_no_cas = []
    for r in llama_records:
        ncas = normalize_cas(r["cas"])
        if ncas:
            llama_by_cas[ncas] = r
        else:
            llama_no_cas.append(r)

    ocr_by_cas = {}
    ocr_no_cas = []
    for r in ocr_records:
        ncas = normalize_cas(r["cas"])
        if ncas:
            ocr_by_cas[ncas] = r
        else:
            ocr_no_cas.append(r)

    # 匹配
    all_cas = set(llama_by_cas.keys()) | set(ocr_by_cas.keys())

    both = []       # 两引擎都有
    only_llama = [] # 仅 LlamaParse
    only_ocr = []   # 仅 OCR
    conflicts = []  # 都有但字段不一致

    for cas in sorted(all_cas):
        l = llama_by_cas.get(cas)
        o = ocr_by_cas.get(cas)

        if l and o:
            # 比较中文名称（简单清洗后）
            l_name = clean_name(l["chinese_name"])
            o_name = clean_name(o["chinese_name"])
            if l_name == o_name:
                both.append({"cas": cas, "llama": l, "ocr": o})
            else:
                conflicts.append({
                    "cas": cas,
                    "llama_name": l["chinese_name"],
                    "ocr_name": o["chinese_name"],
                    "llama": l,
                    "ocr": o,
                })
        elif l and not o:
            only_llama.append({"cas": cas, "llama": l})
        elif o and not l:
            only_ocr.append({"cas": cas, "ocr": o})

    # 无 CAS 的条目：尝试用中文名匹配
    remaining_ocr = list(ocr_no_cas)
    for l in llama_no_cas:
        l_name = clean_name(l["chinese_name"])
        found = False
        for o in remaining_ocr:
            o_name = clean_name(o["chinese_name"])
            if l_name == o_name or (len(l_name) >= 4 and l_name in o_name):
                both.append({"cas": f"name:{l_name}", "llama": l, "ocr": o})
                remaining_ocr.remove(o)
                found = True
                break
        if not found:
            only_llama.append({"cas": "no_cas", "llama": l})

    for o in remaining_ocr:
        only_ocr.append({"cas": "no_cas", "ocr": o})

    return both, only_llama, only_ocr, conflicts


def clean_name(name):
    """清洗中文名称用于比较。"""
    if not name:
        return ""
    # 去掉括号内容和 <br/> 标签
    name = re.sub(r'<br/?>', '', name)
    name = re.sub(r'（[^）]*）', '', name)
    name = re.sub(r'\([^)]*\)', '', name)
    # 去空格
    name = name.strip()
    return name


# ─── Step 6: 报告生成 ─────────────────────────────

def generate_report(both, only_llama, only_ocr, conflicts, ocr_total, llama_total):
    """生成三指标报告 + 人工复核清单。"""
    union = len(both) + len(only_llama) + len(only_ocr) + len(conflicts)

    if union == 0:
        print("错误: 无数据可比")
        return

    # 三指标
    llama_recall = (len(both) + len(conflicts)) / union * 100
    ocr_recall = (len(both) + len(conflicts)) / union * 100
    agreement = len(both) / (len(both) + len(conflicts)) * 100 if (len(both) + len(conflicts)) > 0 else 0
    conflict_rate = len(conflicts) / (len(both) + len(conflicts)) * 100 if (len(both) + len(conflicts)) > 0 else 0
    single_sided = len(only_llama) + len(only_ocr)
    single_rate = single_sided / union * 100

    print("=" * 65)
    print("  GB 38850 成分清单交叉验证报告")
    print("  引擎: LlamaParse (AI视觉) vs EasyOCR (传统OCR)")
    print("=" * 65)
    print()
    print(f"  并集条目总数: {union}")
    print(f"  LlamaParse 提取: {len(both) + len(conflicts) + len(only_llama)}")
    print(f"  EasyOCR 提取:   {len(both) + len(conflicts) + len(only_ocr)}")
    print()
    print(f"  召回率:  LlamaParse {llama_recall:.1f}%    EasyOCR {ocr_recall:.1f}%")
    print(f"  一致率:  {agreement:.1f}% ({len(both)}/{len(both) + len(conflicts)} 条目无需复核)")
    print(f"  冲突率:  {conflict_rate:.1f}% ({len(conflicts)} 条目需人工复核)")
    print(f"  仅单侧:  {single_rate:.1f}% ({single_sided} 条目需补全)")
    print()

    # 人工复核清单
    print("-" * 65)
    print("  人工复核清单 (按优先级)")
    print("-" * 65)

    # P0: 冲突条目
    if conflicts:
        print(f"\n  [P0-冲突] {len(conflicts)} 条目 — CAS 一致但名称不同\n")
        for i, c in enumerate(conflicts[:20], 1):
            print(f"  {i:2d}. CAS {c['cas']}")
            print(f"      LlamaParse: {c['llama_name'][:60]}")
            print(f"      EasyOCR:    {c['ocr_name'][:60]}")
            print()

    # P1: 仅单侧
    if only_llama:
        print(f"\n  [P1-仅LlamaParse] {len(only_llama)} 条目 — OCR 未提取到")
        for i, item in enumerate(only_llama[:10], 1):
            r = item["llama"]
            print(f"  {i:2d}. CAS {r['cas']} | {r['chinese_name'][:50]}")
    if only_ocr:
        print(f"\n  [P1-仅EasyOCR] {len(only_ocr)} 条目 — LlamaParse 未提取到")
        for i, item in enumerate(only_ocr[:10], 1):
            r = item["ocr"]
            print(f"  {i:2d}. CAS {r['cas']} | {r['chinese_name'][:50]}")

    print()
    print("=" * 65)
    print(f"  总结: {union} 条目 → {len(conflicts) + single_sided} 条需人工审核")
    print(f"  自动化率: {(len(both) / union * 100):.1f}%")
    print("=" * 65)

    # 保存详细结果
    report = {
        "summary": {
            "union": union,
            "llama_recall": round(llama_recall, 1),
            "ocr_recall": round(ocr_recall, 1),
            "agreement_rate": round(agreement, 1),
            "conflict_rate": round(conflict_rate, 1),
            "single_sided_rate": round(single_rate, 1),
            "agreement_count": len(both),
            "conflict_count": len(conflicts),
            "only_llama_count": len(only_llama),
            "only_ocr_count": len(only_ocr),
        },
        "conflicts": [
            {"cas": c["cas"], "llama_name": c["llama_name"], "ocr_name": c["ocr_name"]}
            for c in conflicts
        ],
        "only_llama": [
            {"cas": item["llama"]["cas"], "name": item["llama"]["chinese_name"]}
            for item in only_llama
        ],
        "only_ocr": [
            {"cas": item["ocr"]["cas"], "name": item["ocr"]["chinese_name"]}
            for item in only_ocr
        ],
    }
    report_path = OUT_DIR / "cross_validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n  详细报告已保存: {report_path}")


# ─── Main ─────────────────────────────────────────

def main():
    # 1. 获取 EasyOCR 结果
    ocr_data = run_easyocr()

    # 2. 提取 EasyOCR 结构化记录
    print("\n[提取] EasyOCR 记录...")
    ocr_records = []
    for page_num_str in sorted(ocr_data.keys(), key=int):
        page_num = int(page_num_str)
        page_results = ocr_data[page_num_str]

        if page_num in TABLE1_PAGES:
            label = "table1"
        elif page_num in TABLE2_PAGES:
            label = "table2"
        else:
            label = "other"

        if label == "other":
            continue  # 跳过封面、目录、前言等

        records = extract_records_from_page(page_results, label)
        ocr_records.extend(records)

    print(f"  EasyOCR 提取到 {len(ocr_records)} 条记录")
    # 去重 (同一 CAS 可能出现在跨页继续表中)
    seen_cas = set()
    deduped = []
    for r in ocr_records:
        ncas = normalize_cas(r["cas"])
        if ncas and ncas in seen_cas:
            continue
        if ncas:
            seen_cas.add(ncas)
        deduped.append(r)
    ocr_records = deduped
    print(f"  去重后: {len(ocr_records)} 条")

    # 保存 OCR 提取结果
    ocr_output = OUT_DIR / "easyocr_records.json"
    ocr_output.write_text(json.dumps(ocr_records, ensure_ascii=False, indent=2))

    # 3. 提取 LlamaParse 记录
    print("\n[提取] LlamaParse 记录...")
    llama_records = extract_llamaparse_records(LLAMAPARSE_MD)
    print(f"  LlamaParse 提取到 {len(llama_records)} 条记录")

    lp_output = OUT_DIR / "llamaparse_records.json"
    lp_output.write_text(json.dumps(llama_records, ensure_ascii=False, indent=2))

    # 4. 对齐匹配
    print("\n[匹配] 对齐两引擎记录...")
    both, only_llama, only_ocr, conflicts = match_by_cas(ocr_records, llama_records)
    print(f"  一致: {len(both)}, 冲突: {len(conflicts)}, 仅LlamaParse: {len(only_llama)}, 仅OCR: {len(only_ocr)}")

    # 5. 生成报告
    print()
    generate_report(both, only_llama, only_ocr, conflicts,
                    len(ocr_records), len(llama_records))


if __name__ == "__main__":
    main()
