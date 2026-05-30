"""
清洗 virus_detection_prices.xlsx 中后 3 个 Sheet，
使其表结构和数据格式与第 1 个数据 Sheet 完全对齐。

输出列: No. | 测试项目 | 测试方法 | 技术指导价 | 销售价 | 周期 | 样品量 | 资质 | 是否内部测试 | (预留)
"""

import openpyxl
from openpyxl.utils import get_column_letter
from copy import copy
import re

INPUT_FILE = '/Users/ml/Desktop/ai_sale_agent001/virus_detection_prices.xlsx'
OUTPUT_FILE = '/Users/ml/Desktop/ai_sale_agent001/virus_detection_prices_cleaned.xlsx'


def has_price(val):
    """判断单元格是否包含价格信息"""
    if not val:
        return False
    s = str(val).strip()
    return bool(re.search(r'[\d,]+元|[\d,]+\s*万', s))


def is_category_title(c1, c2, c3):
    """判断是否为分类标题行（非数据行）"""
    c1s = str(c1).strip() if c1 else ''
    c2s = str(c2).strip() if c2 else ''
    c3s = str(c3).strip() if c3 else ''

    # "2．消毒器械测试（...）" 这种大类标题
    if re.match(r'^\d+[\.\．]', c1s) and '测试' in c1s and not has_price(c3):
        if '病毒' not in c2s or c2s == '':
            return True

    # "2.1 抗病毒性能" 这种 - Col3 为空且 Col2 不含具体病毒
    if re.match(r'^\d+\.\d+$', c1s) and not c3s:
        return True

    return False


def is_group_header(c1, c2, c3, c4):
    """判断是否为分组标题行（有方法但无价格，下面跟子项目）"""
    c1s = str(c1).strip() if c1 else ''
    c2s = str(c2).strip() if c2 else ''
    c3s = str(c3).strip() if c3 else ''
    c4s = str(c4).strip() if c4 else ''

    # 章节号开头且有方法描述但无价格
    if re.match(r'^\d+\.\d+(\.\d+)?$', c1s) and c3s and not has_price(c4s):
        return True
    return False


def is_shifed_sub_item(c1, c2, c3, c4):
    """判断是否为列偏移的子项目行（C1 为空，C2 是数字，C3 是病毒名，C4 有价格）"""
    c1s = str(c1).strip() if c1 else ''
    c2s = str(c2).strip() if c2 else ''
    c3s = str(c3).strip() if c3 else ''

    if not c1s and c2s and c3s:
        # C2 是纯数字或简单编号
        if re.match(r'^\d+$', c2s) and has_price(c3) == False:
            # C3 包含病毒相关信息
            if re.search(r'病毒|PV-|HSV|H1N1|H3N2|HPV|RSV|EV71|CV|CA|FCV|VSV|CMV|HIV', c3s):
                return True
    return False


def is_direct_item(c1, c2, c4):
    """判断是否为直接数据行（C1 是章节号，C2 含产品+病毒，C4 有价格）"""
    c1s = str(c1).strip() if c1 else ''
    c2s = str(c2).strip() if c2 else ''

    if re.match(r'^\d+\.\d+(\.\d+)?$', c1s) and has_price(c2) == False:
        # 有价格 → 直接数据行
        return True
    return False


def clean_virus_name(text):
    """清洗病毒名称，提取纯病毒名 + 别名"""
    if not text:
        return text
    text = str(text).strip()
    # 去掉首尾多余空白和换行
    text = re.sub(r'\s+$', '', text)
    return text


def clean_method_text(text):
    """清洗测试方法文本"""
    if not text:
        return ''
    text = str(text).strip()
    return text


def clean_pricing_text(text):
    """规范化价格文本"""
    if not text:
        return ''
    text = str(text).strip()
    # 如果文本没有换行但有两个价格项连在一起，拆分
    if '\n' not in text:
        text = re.sub(r'(元/[^每，,]+)(每增加)', r'\1\n\2', text)
        text = re.sub(r'(元/样[；;]?)([≥\d])', r'\1\n\2', text)
        text = re.sub(r'(元/病毒株)(每增加)', r'\1\n\2', text)
        text = re.sub(r'(元/病毒/时间点)(每增加)', r'\1\n\2', text)
        text = re.sub(r'(元/病毒)(每增加)', r'\1\n\2', text)
        text = re.sub(r'([；;])(\s*[≥\d])', r'\1\n\2', text)
    return text


def cell_copy_style(src_cell, dst_cell):
    """复制单元格样式"""
    if src_cell.has_style:
        dst_cell.font = copy(src_cell.font)
        dst_cell.border = copy(src_cell.border)
        dst_cell.fill = copy(src_cell.fill)
        dst_cell.number_format = copy(src_cell.number_format)
        dst_cell.protection = copy(src_cell.protection)
        dst_cell.alignment = copy(src_cell.alignment)


def process_sheet(src_sheet, category_label, template_headers):
    """
    处理单个 Sheet，返回清洗后的数据行列表。
    每行是 10 个值的列表。
    """
    rows_out = []

    # 状态追踪
    current_group_method = ''  # 当前分组的方法（用于子项目继承）
    current_group_name = ''    # 当前分组名称（如 "抗病毒性能-载体法"）

    for r in range(1, src_sheet.max_row + 1):
        # 读取 10 列
        raw = []
        for c in range(1, 11):
            raw.append(src_sheet.cell(row=r, column=c).value)

        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = raw
        c1s = str(c1).strip() if c1 else ''
        c2s = str(c2).strip() if c2 else ''
        c3s = str(c3).strip() if c3 else ''
        c4s = str(c4).strip() if c4 else ''

        # 跳过空行
        if not c1s and not c2s and not c3s and not c4s:
            continue

        # 跳过表头行 (No. | 测试项目 | ...)
        if c1s == 'No.' and c2s == '测试项目':
            continue

        # 跳过大类标题行 (如 "2．消毒器械测试（...）")
        if is_category_title(c1, c2, c3):
            continue

        # 检测分组标题行 (2.1, 2.1.3, 3.1, 4.1 等)
        if is_group_header(c1, c2, c3, c4):
            current_group_name = c2s.replace('\n', ' ').strip()
            current_group_method = c3s
            continue

        # 检测子类别标题 (2.1, 3.1, 4.1 - 无方法无价格的纯标题)
        if re.match(r'^\d+\.\d+$', c1s) and not c3s and not c4s:
            continue

        # --- 处理数据行 ---
        out = [''] * 10

        # 模式1: 列偏移的子项目 (C1=NULL, C2=编号, C3=病毒名)
        if is_shifed_sub_item(c1, c2, c3, c4):
            # 测试项目: C3 (病毒名)
            out[1] = clean_virus_name(c3)
            # 测试方法: 检查 C3 是否包含方法信息
            if '参考' in c3s or '《' in c3s or 'ISO' in c3s or 'GB' in c3s:
                # C3 包含了方法和备注，提取方法部分
                parts = re.split(r'\s*[（(]\s*可供|参考', c3s)
                virus_part = parts[0].strip()
                method_from_c3 = c3s[len(virus_part):].strip()
                out[1] = clean_virus_name(virus_part)
                out[2] = current_group_method + ('\n' + method_from_c3 if method_from_c3 else '')
            else:
                # C3 是纯病毒名，方法继承自分组标题
                out[2] = current_group_method

            # 价格 C4, C5 (偏移了一列)
            out[3] = clean_pricing_text(c4) if c4 else ''
            out[4] = clean_pricing_text(c5) if c5 else ''
            out[5] = str(c6).strip() if c6 else ''
            out[6] = str(c7).strip() if c7 else ''
            out[7] = str(c8).strip() if c8 else ''
            out[8] = str(c9).strip() if c9 else ''

        # 模式2: 直接数据行 (C1=章节号, C2=产品+病毒, C3=方法)
        elif re.match(r'^\d+\.\d+(\.\d+)?$', c1s) and has_price(c4s):
            # 测试项目: C2 (可能包含产品名和病毒)
            out[1] = clean_virus_name(c2)
            # 测试方法: C3
            out[2] = clean_method_text(c3) if c3 else ''
            # 价格
            out[3] = clean_pricing_text(c4) if c4 else ''
            out[4] = clean_pricing_text(c5) if c5 else ''
            out[5] = str(c6).strip() if c6 else ''
            out[6] = str(c7).strip() if c7 else ''
            out[7] = str(c8).strip() if c8 else ''
            out[8] = str(c9).strip() if c9 else ''

        # 模式3: 纺织品/塑料制品的带编号数据行 (C2=编号, C3=病毒名)
        elif c1s in ('', '-') and re.match(r'^\d+$', c2s) and c3s:
            # C2 是原始编号，C3 是病毒名
            # 检查 C3 是否包含方法（有些行会带方法）
            if '参考' in c3s or '可供' in c3s:
                parts = re.split(r'\s*[（(]\s*可供|参考', c3s)
                virus_part = parts[0].strip()
                out[1] = clean_virus_name(virus_part)
                method_extra = c3s[len(virus_part):].strip()
                out[2] = current_group_method + ('\n' + method_extra if method_extra else '')
            else:
                out[1] = clean_virus_name(c3)
                out[2] = current_group_method

            out[3] = clean_pricing_text(c4) if c4 else ''
            out[4] = clean_pricing_text(c5) if c5 else ''
            out[5] = str(c6).strip() if c6 else ''
            out[6] = str(c7).strip() if c7 else ''
            out[7] = str(c8).strip() if c8 else ''
            out[8] = str(c9).strip() if c9 else ''

        else:
            # 未知模式，跳过
            continue

        # 清理空值: NULL/None → ''
        for i in range(len(out)):
            if out[i] is None or out[i] == 'None' or out[i] == 'NULL':
                out[i] = ''
            out[i] = str(out[i]) if out[i] else ''

        # 跳过完全空的数据行（测试项目为空）
        if not out[1].strip():
            continue

        rows_out.append(out)

    return rows_out


def main():
    wb = openpyxl.load_workbook(INPUT_FILE, data_only=True)

    # 模板（Sheet 1）表头
    template_sheet = wb[wb.sheetnames[1]]
    template_headers = []
    for c in range(1, template_sheet.max_column + 1):
        template_headers.append(template_sheet.cell(row=2, column=c).value)

    print(f"模板表头: {template_headers}")

    # 产品大类
    category_map = {
        2: '消毒器械',
        3: '纺织产品',
        4: '塑料制品',
    }

    # 创建输出工作簿
    out_wb = openpyxl.Workbook()
    out_wb.remove(out_wb.active)

    # 复制 Sheet 1（黄金标准）原样
    src_s1 = wb[wb.sheetnames[1]]
    out_s1 = out_wb.create_sheet(title=wb.sheetnames[1])
    for r in range(1, src_s1.max_row + 1):
        for c in range(1, src_s1.max_column + 1):
            src_cell = src_s1.cell(row=r, column=c)
            dst_cell = out_s1.cell(row=r, column=c)
            dst_cell.value = src_cell.value
            if src_cell.has_style:
                cell_copy_style(src_cell, dst_cell)
    print(f"\nSheet 1 已复制（{src_s1.max_row} 行）")

    # 处理 Sheet 2-4
    for sheet_idx in [2, 3, 4]:
        src_sheet = wb[wb.sheetnames[sheet_idx]]
        sheet_title = wb.sheetnames[sheet_idx]
        category = category_map[sheet_idx]

        # 清洗数据
        cleaned_rows = process_sheet(src_sheet, category, template_headers)
        print(f"\nSheet {sheet_idx}「{sheet_title}」: {len(cleaned_rows)} 行数据")

        # 创建输出 Sheet
        out_sheet = out_wb.create_sheet(title=sheet_title)

        # Row 1: 分类说明（合并单元格风格）
        out_sheet.cell(row=1, column=1).value = f"{category}测试（未标注有资质的病毒项目均参考测试）"

        # Row 2: 表头
        for c, header in enumerate(template_headers, 1):
            out_sheet.cell(row=2, column=c).value = header

        # Row 3+: 数据
        for i, row_data in enumerate(cleaned_rows):
            out_r = 3 + i
            # Col 1: 序号
            out_sheet.cell(row=out_r, column=1).value = i + 1
            # Col 2-9: 数据
            for c in range(2, 10):
                val = row_data[c - 1]
                if val:
                    out_sheet.cell(row=out_r, column=c).value = val

        # 调整列宽
        col_widths = {
            1: 6, 2: 36, 3: 42, 4: 32, 5: 32,
            6: 10, 7: 18, 8: 22, 9: 14, 10: 8,
        }
        for col_num, width in col_widths.items():
            out_sheet.column_dimensions[get_column_letter(col_num)].width = width

    # 保存
    out_wb.save(OUTPUT_FILE)
    print(f"\n输出文件: {OUTPUT_FILE}")
    print(f"工作表: {out_wb.sheetnames}")


if __name__ == '__main__':
    main()
