"""
从 LlamaParse 解析的 GB 38850-2020 Markdown 文件中程序化提取
活性成分清单（表1）和惰性成分清单（表2）。

数据源:
  - 1号修改单 (权威): 表1 scope code，含最新变更
  - 原版: 表2 惰性成分（修改单不含表2）

输出: 可直接替换 ingredient_compliance.py 中硬编码字典的 Python 代码。
"""

import re
import sys
import os

PARSED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "parsed_docs")
MODIFICATION = os.path.join(PARSED_DIR, "GB 38850-2020 消毒剂原料清单及禁限用物质(1号修改文件).md")
ORIGINAL = os.path.join(PARSED_DIR, "GB 38850-2020 消毒剂原料清单及禁限用物质.md")


def clean_cell(text: str) -> str:
    """去除 <br/>、前后空白、多余换行。"""
    text = re.sub(r'<br\s*/?>', '', text)
    text = text.replace('\n', ' ').strip()
    return text


def parse_name(full: str) -> tuple[str, str]:
    """
    从表格名称列提取 (显示名称, 完整化学名)。

    例: "1,3'-二溴...(二溴海因)" → ("二溴海因", "1,3'-二溴-5,5'-二甲基乙内酰脲")
         "乙酸"                 → ("乙酸", "乙酸")
         "三氯羟基二苯醚(三氯生)" → ("三氯生", "三氯羟基二苯醚")
    """
    full = clean_cell(full)
    # 清理上标标记: 仅删除紧跟在汉字后的 "a"（如 "溶菌酶a"→"溶菌酶"），
    # 保留产品等级标识（如 "氯胺 T" 的 T）
    full = re.sub(r'(?<=[一-鿿])aa?$', '', full)
    # 匹配 "全名(简称)" 或 "全名（简称）"
    m = re.match(r'^(.+?)[（(]([^)）]+)[）)]$', full)
    if m:
        outer = m.group(1).strip()
        inner = m.group(2).strip()
        # 启发式: 括号内容比主体长 → 描述性注释（如"包括微酸性电解水"），不是简称
        if len(inner) > len(outer):
            return outer, outer
        return inner, outer
    return full, full


def parse_cas(raw: str) -> str:
    """提取 CAS 编码。多值时取第一个（如 '8001-54-5/63449-41-2'）。"""
    raw = clean_cell(raw)
    if '/' in raw and raw != '—' and raw != '——':
        # "8001-54-5/<br/>63449-41-2" → "8001-54-5"
        return raw.split('/')[0].strip()
    return raw


def parse_scope(raw: str) -> str:
    """
    解析使用范围。
    输入: "E、H、M" 或 "A、E、H、M" 或 "H *E*" (修改单标记) 或 "E、--" (移除标记)
    输出: "E/H/M" (代码格式，/ 分隔)
    #E 表示仅限物体表面（与 E 不同），需保留 # 前缀。
    """
    raw = clean_cell(raw)
    # 规范化分隔符: 空格 → 顿号（修改单中部分行用空格代替顿号）
    raw = raw.replace(' ', '、')
    # 去掉修改单的 ** 或 * 标记（注意：不删除 #，它是受限范围标记 #E ≠ E）
    raw = raw.replace('*', '')
    # 去掉移除标记 "--"
    raw = raw.replace('--', '')
    # "、" → "/"，再清理可能产生的空段
    parts = [p for p in raw.replace('、', '/').split('/') if p and p not in ('', '-')]
    # 合并孤立的 # 前缀到下一段: "#/E/M" → "#E/M"
    merged = []
    i = 0
    while i < len(parts):
        if parts[i] == '#' and i + 1 < len(parts):
            merged.append('#' + parts[i + 1])
            i += 2
        else:
            merged.append(parts[i])
            i += 1
    return '/'.join(merged)


def extract_table_rows(content: str, table_label: str) -> list[dict]:
    """
    从 Markdown 中提取指定表格的所有行。

    table_label: "表 1" 或 "表 2"
    """
    # 找到表格起始位置: "# 表 1" / "### 表 2" 等 heading 格式
    # 或 "表 1 (续)" / "表 2 (续)" 续页标记
    heading_pat = rf'^#+\s+{table_label}\s'  # e.g. "# 表 1 消毒剂..."
    cont_pat = rf'{table_label}\s*[（(]续[)）]'      # e.g. "表 1 (续)"
    pattern = rf'(?:{heading_pat}|{cont_pat})'
    matches = list(re.finditer(pattern, content, re.MULTILINE))
    if not matches:
        print(f"  警告: 未找到 {table_label}")
        return []

    rows = []
    start = matches[0].start()
    # 找下一个顶级标题（# 但不是 ##）
    next_h1 = re.search(r'^# [^#]', content[start+1:], re.MULTILINE)

    # 对于表1: 在下一个表格开始前截断，避免混入惰性成分
    if table_label == "表 1":
        next_table = re.search(r'^#+\s+表\s*2\b|^##\s+4\.2\b', content[start+1:], re.MULTILINE)
        if next_table:
            end = start + 1 + next_table.start()
        elif next_h1:
            end = start + 1 + next_h1.start()
        else:
            end = len(content)
    else:
        if next_h1:
            end = start + 1 + next_h1.start()
        else:
            end = len(content)

    section = content[start:end]
    lines = section.split('\n')

    in_table = False
    for line in lines:
        line = line.strip()
        # 表格行: | 数字 | 或 | **数字** | (修改单末尾有加粗)
        if re.match(r'^\|\s*(?:\*\*)?\s*\d+\s*(?:\*\*)?\s*\|', line):
            in_table = True
            cols = [c.strip() for c in line.split('|')[1:-1]]  # 去掉首尾空
            if len(cols) >= 4:
                seq_raw = cols[0].strip().replace('*', '').replace('**', '')
                name_raw = cols[1].strip().replace('**', '')
                # 英文名列在 cols[2] (跳过)
                cas_raw = cols[-2].strip() if len(cols) >= 4 else ''
                scope_raw = cols[-1].strip() if len(cols) >= 5 else ''

                if seq_raw.isdigit():
                    rows.append({
                        'seq': int(seq_raw),
                        'name_raw': name_raw,
                        'cas_raw': cas_raw,
                        'scope_raw': scope_raw,
                    })
        elif in_table and not line.startswith('|'):
            # 表格间的内容（页码、SAC logo、表头等）
            if line and not line.startswith('注') and not line.startswith('<sup'):
                pass  # 跳过非表格内容

    return rows


def extract_active_ingredients() -> list[dict]:
    """从修改单提取活性成分（权威 scope），缺失条目用原版补充。"""
    print("读取修改单...")
    with open(MODIFICATION) as f:
        mod = f.read()

    print("读取原版...")
    with open(ORIGINAL) as f:
        orig = f.read()

    mod_rows = extract_table_rows(mod, "表 1")
    print(f"  修改单表1: {len(mod_rows)} 行")

    # 建立序号→条目映射
    by_seq = {r['seq']: r for r in mod_rows}

    # 手动补充修改单中非表格格式的条目
    # 过碳酸钠 (1号修改单新增, 序号84)
    # 修改单中这行是 OCR 红色文本: "84 Sodi um percarbonate 15630-89-4 E W"
    # 必须在原版补充之前运行，否则原版的溶菌酶会先占位
    if 84 not in by_seq:
        m = re.search(r'84.*?(?:Sodi\s*um?\s*)?percarbonate.*?([\d\-]+)\s+([A-Z])\s+([A-Z])', mod, re.IGNORECASE)
        if m:
            by_seq[84] = {
                'seq': 84,
                'name_raw': '过碳酸钠',
                'cas_raw': m.group(1),
                'scope_raw': f'{m.group(2)}、{m.group(3)}',
            }
            print(f"  补充序号 84 (过碳酸钠, OCR): CAS={m.group(1)}, scope={m.group(2)}、{m.group(3)}")
        else:
            print(f"  警告: 未能从修改单提取过碳酸钠(序号84)")

    # 补充修改单缺失的条目（如末尾行等）
    # 从原版提取补全
    orig_rows = extract_table_rows(orig, "表 1")
    print(f"  原版表1: {len(orig_rows)} 行")

    for r in orig_rows:
        if r['seq'] not in by_seq:
            by_seq[r['seq']] = r
            print(f"  补充序号 {r['seq']}: {r['name_raw'][:60]}")

    # 解析为结构化数据
    result = []
    for seq in sorted(by_seq.keys()):
        r = by_seq[seq]
        short_name, long_name = parse_name(r['name_raw'])
        cas = parse_cas(r['cas_raw'])
        scope = parse_scope(r['scope_raw'])

        if not short_name or short_name in ('—', '——', ''):
            continue

        result.append({
            'seq': seq,
            'name': short_name,
            'full_name': long_name if long_name != short_name else '',
            'cas': cas,
            'scope': scope,
        })

    print(f"  有效条目: {len(result)}")
    return result


def extract_inert_ingredients() -> list[dict]:
    """从原版提取惰性成分（修改单不含表2）。"""
    print("\n读取原版表2...")
    with open(ORIGINAL) as f:
        orig = f.read()

    rows = extract_table_rows(orig, "表 2")
    print(f"  原版表2: {len(rows)} 行")

    result = []
    for r in rows:
        short_name, long_name = parse_name(r['name_raw'])
        cas = parse_cas(r['cas_raw'])
        scope = parse_scope(r['scope_raw'])

        if not short_name or short_name in ('—', '——', ''):
            continue

        result.append({
            'seq': r['seq'],
            'name': short_name,
            'full_name': long_name if long_name != short_name else '',
            'cas': cas,
            'scope': scope,
        })

    print(f"  有效条目: {len(result)}")
    return result


def extract_restriction_limits() -> dict:
    """从修改单第6条提取限用物质限量。"""
    print("\n读取限用物质...")
    with open(MODIFICATION) as f:
        mod = f.read()

    limits = {'skin': {}, 'mucosal': {}}

    # 6.1 皮肤
    m = re.search(r'6\.1.*?(?:葡萄糖酸氯己定|醋酸氯己定).*?≤\s*([\d.]+).*?'
                  r'(?:三氯|2,4,4.*?二苯醚).*?≤\s*([\d.]+).*?'
                  r'(?:苯扎溴铵|苯扎氯铵).*?≤\s*([\d.]+)',
                  mod, re.DOTALL)
    if m:
        limits['skin'] = {
            '葡萄糖酸氯己定': {'limit': float(m.group(1)), 'unit': 'g/L', 'rule': '6.1'},
            '醋酸氯己定': {'limit': float(m.group(1)), 'unit': 'g/L', 'rule': '6.1'},
            '三氯生': {'limit': float(m.group(2)), 'unit': 'g/L', 'rule': '6.1'},
            '苯扎溴铵': {'limit': float(m.group(3)), 'unit': 'g/L', 'rule': '6.1'},
            '苯扎氯铵': {'limit': float(m.group(3)), 'unit': 'g/L', 'rule': '6.1'},
        }
        print(f"  皮肤消毒剂限量: {len(limits['skin'])} 种")

    # 6.2 黏膜
    m = re.search(r'6\.2.*?(?:葡萄糖酸氯己定|醋酸氯己定).*?≤\s*([\d.]+).*?'
                  r'(?:三氯|2,4,4.*?二苯醚).*?≤\s*([\d.]+).*?'
                  r'(?:苯扎溴铵|苯扎氯铵).*?≤\s*([\d.]+)',
                  mod, re.DOTALL)
    if m:
        limits['mucosal'] = {
            '葡萄糖酸氯己定': {'limit': float(m.group(1)), 'unit': 'g/L', 'rule': '6.2'},
            '醋酸氯己定': {'limit': float(m.group(1)), 'unit': 'g/L', 'rule': '6.2'},
            '三氯生': {'limit': float(m.group(2)), 'unit': 'g/L', 'rule': '6.2'},
            '苯扎溴铵': {'limit': float(m.group(3)), 'unit': 'g/L', 'rule': '6.2'},
            '苯扎氯铵': {'limit': float(m.group(3)), 'unit': 'g/L', 'rule': '6.2'},
        }
        print(f"  黏膜消毒剂限量: {len(limits['mucosal'])} 种")

    return limits


def _esc(s: str) -> str:
    """转义反斜杠和双引号，确保生成的 Python 字符串字面量合法。"""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def generate_python_code(active: list[dict], inert: list[dict],
                         limits: dict) -> str:
    """生成可替换 ingredient_compliance.py 数据段的 Python 代码。"""

    lines = []
    lines.append("# ═══════════════════════════════════════════════════════════════")
    lines.append("# GB 38850-2020 表1：活性（有效）成分清单（含第1号修改单）")
    lines.append(f"# 共 {len(active)} 条，由 extract_ingredients.py 自动提取")
    lines.append("# ═══════════════════════════════════════════════════════════════")
    lines.append("# 使用范围代码: A=室内空气 C=污染物 D=生活饮用水 E=环境及物体表面")
    lines.append("#              H=人体 K=集中空调 M=医疗器械 S=游泳池水 W=医院污水")
    lines.append("#              #E=仅限于物体表面")
    lines.append("")
    lines.append("ACTIVE_INGREDIENTS = {")

    for ing in active:
        name = _esc(ing['name'])
        cas = _esc(ing['cas'])
        scope = _esc(ing['scope'])
        # alias 仅存储名称字符串，外部 [ ] 由 f-string 提供
        alias_val = _esc(ing['full_name']) if ing['full_name'] and ing['full_name'] != name else ''
        lines.append(f'    "{name}": ("{cas}", "{scope}", ["{alias_val}"]),'
                     if alias_val else
                     f'    "{name}": ("{cas}", "{scope}", []),')

    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("# ═══════════════════════════════════════════════════════════════")
    lines.append("# GB 38850-2020 表2：惰性成分清单")
    lines.append(f"# 共 {len(inert)} 条，由 extract_ingredients.py 自动提取")
    lines.append("# ═══════════════════════════════════════════════════════════════")
    lines.append("")
    lines.append("INERT_INGREDIENTS = {")

    for ing in inert:
        name = _esc(ing['name'])
        cas = _esc(ing['cas'])
        scope = _esc(ing['scope'])
        alias_val = _esc(ing['full_name']) if ing['full_name'] and ing['full_name'] != name else ''
        lines.append(f'    "{name}": ("{cas}", "{scope}", ["{alias_val}"]),'
                     if alias_val else
                     f'    "{name}": ("{cas}", "{scope}", []),')

    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("# ═══════════════════════════════════════════════════════════════")
    lines.append("# GB 38850-2020 第6条：限用物质（浓度限量）")
    lines.append(f"# 由 extract_ingredients.py 自动提取")
    lines.append("# ═══════════════════════════════════════════════════════════════")
    lines.append("")
    lines.append("RESTRICTION_LIMITS = {")

    for scope_type in ("skin", "mucosal"):
        lines.append(f'    "{scope_type}": {{  # {"6.1 皮肤消毒剂限量" if scope_type == "skin" else "6.2 黏膜消毒剂限量"}')
        for name, info in limits[scope_type].items():
            lines.append(f'        "{name}": {{"limit": {info["limit"]}, '
                         f'"unit": "{info["unit"]}", "rule": "{info["rule"]}"}},')
        lines.append("    },")

    lines.append("}")
    lines.append("")

    return '\n'.join(lines)


def validate_extraction(active: list[dict], inert: list[dict], limits: dict) -> bool:
    """校验提取结果的质量。"""
    errors = []

    # 活性成分 check — 精确匹配已知值
    if len(active) != 86:
        errors.append(f"活性成分 {len(active)} 条，预期 86 条（GB 38850-2020 表1 + 1号修改单）")
    if len(active) > 86:
        errors.append(f"活性成分超出 86 条，可能存在重复提取")

    # 惰性成分 check — 精确匹配已知值
    if len(inert) != 115:
        errors.append(f"惰性成分 {len(inert)} 条，预期 115 条（GB 38850-2020 表2）")

    # 检查必需成分是否存在
    required_active = ["乙醇", "次氯酸钠", "苯扎溴铵", "三氯生", "过氧化氢", "碘"]
    for name in required_active:
        found = any(ing['name'] == name for ing in active)
        if not found:
            errors.append(f"必需活性成分缺失: {name}")

    # 检查限用物质
    for scope in ("skin", "mucosal"):
        if len(limits.get(scope, {})) < 4:
            errors.append(f"限用物质 {scope} 不足 4 种")

    # 检查 scope 格式
    for ing in active:
        if ing['scope'] and not re.match(r'^[A-Z#/]+$', ing['scope']):
            errors.append(f"scope 格式异常: {ing['name']} → {ing['scope']}")

    if errors:
        print("\n⚠ 校验发现问题:")
        for e in errors:
            print(f"  - {e}")
        return False

    print(f"\n✅ 校验通过: {len(active)} 活性 + {len(inert)} 惰性 + 限用 {sum(len(v) for v in limits.values())} 种")
    return True


def main():
    print("=" * 60)
    print("GB 38850-2020 成分数据提取脚本")
    print("=" * 60)

    # 1. 提取活性成分
    active = extract_active_ingredients()

    # 2. 提取惰性成分
    inert = extract_inert_ingredients()

    # 3. 提取限用物质
    limits = extract_restriction_limits()

    # 4. 校验
    print("\n" + "=" * 60)
    print("数据校验")
    print("=" * 60)
    if not validate_extraction(active, inert, limits):
        print("\n校验未通过，请检查提取逻辑。")
        sys.exit(1)

    # 5. 生成代码
    print("\n" + "=" * 60)
    print("生成 Python 代码")
    print("=" * 60)
    code = generate_python_code(active, inert, limits)

    output_path = os.path.join(os.path.dirname(__file__), "..",
                               "coze_workflow", "code_nodes", "_generated_ingredients.py")
    output_path = os.path.abspath(output_path)
    with open(output_path, 'w') as f:
        f.write(code)
    print(f"已写入: {output_path}")
    print(f"  活性成分: {len(active)} 条")
    print(f"  惰性成分: {len(inert)} 条")
    print(f"  限用物质: skin {len(limits.get('skin', {}))} + mucosal {len(limits.get('mucosal', {}))} 种")

    # 6. 差异报告
    print("\n" + "=" * 60)
    print("与现有代码的差异")
    print("=" * 60)
    print("请将生成的 _generated_ingredients.py 与 ingredient_compliance.py 对比。")
    print("替换 ACTIVE_INGREDIENTS、INERT_INGREDIENTS、RESTRICTION_LIMITS 三个字典即可。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
