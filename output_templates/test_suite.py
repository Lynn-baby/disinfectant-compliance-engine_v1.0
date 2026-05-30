"""
F5 输出模板 — 测试套件。

覆盖：
- 各状态模板的必含标题校验
- 关键字段非空检查
- S3 成分表格构建函数
- S4 风险评级模板填充
- S5 检测方案表格构建
- S6 报价表格构建
- S7 预审摘要完整性
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from output_templates.template_definitions import (
    get_template,
    build_s3_ingredient_rows,
    build_s4_output,
    build_s5_testing_table,
    build_s6_pricing_table,
    S3_TEMPLATE,
    S4_TEMPLATE,
    S5_TEMPLATE,
    S6_TEMPLATE,
    S7_TEMPLATE,
    TEMPLATE_REGISTRY,
)
from output_templates.template_validator import validate_output

_passed = 0
_failed = 0


def test(name, actual, expected):
    global _passed, _failed
    ok = actual == expected
    if ok:
        _passed += 1
        print(f"  ✅ {name}")
    else:
        _failed += 1
        print(f"  ❌ {name}")
        print(f"     预期: {expected!r}")
        print(f"     实际: {actual!r}")


# ═══════════════════════════════════════════════════════════════════
# 模板注册表完整性
# ═══════════════════════════════════════════════════════════════════

def test_registry():
    print("\n── 模板注册表 ──")

    for state in ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]:
        spec = get_template(state)
        test(f"REG-{state} 存在", spec is not None, True)
        test(f"REG-{state} template 非空", bool(spec.template), True)
        test(f"REG-{state} required_sections 非空",
             len(spec.required_sections) > 0, True)


# ═══════════════════════════════════════════════════════════════════
# S3 成分表格构建
# ═══════════════════════════════════════════════════════════════════

def test_s3():
    print("\n── S3 成分合规模板 ──")

    results = [
        {"name": "酒精", "status": "allowed", "reference": "《消毒剂原料清单》"},
        {"name": "三氯生", "status": "prohibited", "reference": "《消毒剂原料清单》禁限用物质"},
        {"name": "纳米银", "status": "unknown", "reference": "", "note": "暂无收录"},
    ]
    output = build_s3_ingredient_rows(results)

    test("TMP-S3-01 包含允许", "✅" in output, True)
    test("TMP-S3-02 包含禁止", "❌" in output, True)
    test("TMP-S3-03 包含未收录", "⚠️" in output, True)
    test("TMP-S3-04 引用法规", "《消毒剂原料清单》" in output, True)

    # 空列表
    output = build_s3_ingredient_rows([])
    test("TMP-S3-05 空列表", output, "")


# ═══════════════════════════════════════════════════════════════════
# S4 风险评级模板
# ═══════════════════════════════════════════════════════════════════

def test_s4():
    print("\n── S4 风险评级模板 ──")

    # R1
    output = build_s4_output("R1", ["成分在允许清单中", "国产", "无退单历史"])
    test("TMP-S4-01 R1 等级标签", "R1 低风险" in output, True)
    test("TMP-S4-02 R1 触发条件", "成分在允许清单中" in output, True)
    test("TMP-S4-03 R1 无免责", "免责声明" not in output, True)

    # R2
    output = build_s4_output("R2", ["含未收录成分", "进口"],
                              uncertainty_reasons=["纳米银未收录", "进口路径差异"])
    test("TMP-S4-04 R2 等级标签", "R2 中风险" in output, True)
    test("TMP-S4-05 R2 有免责", "免责声明" in output, True)

    # R3
    output = build_s4_output("R3", ["含禁用成分三氯生", "历史退单"],
                              blocking_reasons=["三氯生在禁用清单中", "曾被其他机构退单"])
    test("TMP-S4-06 R3 等级标签", "R3 高风险" in output, True)
    test("TMP-S4-07 R3 禁止报价", "不输出检测方案和报价" in output, True)
    test("TMP-S4-08 R3 转人工", "转人工" in output, True)


# ═══════════════════════════════════════════════════════════════════
# S5 检测方案表格
# ═══════════════════════════════════════════════════════════════════

def test_s5():
    print("\n── S5 检测方案模板 ──")

    items = [
        {"name": "有效成分含量", "standard": "《消毒技术规范》", "sample_count": 3, "note": ""},
        {"name": "抑菌试验", "standard": "GB 15979", "sample_count": 5, "note": ""},
        {"name": "pH值", "standard": "GB 15979", "sample_count": 2, "note": ""},
    ]
    table = build_s5_testing_table(items)

    test("TMP-S5-01 表头完整", "参考标准" in table, True)
    test("TMP-S5-02 项目1", "有效成分含量" in table, True)
    test("TMP-S5-03 项目2", "抑菌试验" in table, True)
    test("TMP-S5-04 标准号", "GB 15979" in table, True)


# ═══════════════════════════════════════════════════════════════════
# S6 报价表格
# ═══════════════════════════════════════════════════════════════════

def test_s6():
    print("\n── S6 报价模板 ──")

    items = [
        {"name": "有效成分含量", "price": 600},
        {"name": "抑菌试验", "price": 2000},
    ]
    table = build_s6_pricing_table(items)

    test("TMP-S6-01 表头完整", "单价" in table, True)
    test("TMP-S6-02 项目1", "有效成分含量" in table, True)
    test("TMP-S6-03 金额", "600" in table, True)


# ═══════════════════════════════════════════════════════════════════
# S7 预审摘要模板
# ═══════════════════════════════════════════════════════════════════

def test_s7():
    print("\n── S7 预审摘要模板 ──")

    template = S7_TEMPLATE

    required_parts = [
        "消字号合规 · 意向预审报告",
        "产品信息",
        "合规预审结论",
        "推荐检测方案",
        "费用预估",
        "声明",
        "报告编号",
        "生成日期",
        "30 天",
    ]
    for part in required_parts:
        test(f"TMP-S7 含「{part}」", part in template, True)

    # 占位符检查
    placeholders = [
        "{report_id}", "{report_date}", "{product_name}",
        "{category}", "{risk_level_label}",
    ]
    for ph in placeholders:
        test(f"TMP-S7 占位符 {ph}", ph in template, True)


# ═══════════════════════════════════════════════════════════════════
# 模板校验器
# ═══════════════════════════════════════════════════════════════════

def test_validator():
    print("\n── 模板校验器 ──")

    # 完整的 S4 输出 → 通过
    output = build_s4_output("R1", ["成分在允许清单中", "国产"])
    result = validate_output(output, "S4")
    test("VAL-01 完整S4通过", result.passed, True)

    # 缺失标题
    result = validate_output("风险等级 R1", "S4")
    test("VAL-02 缺标题失败", result.passed, False)
    test("VAL-02 缺触发条件", "触发条件" in str(result.issues), True)

    # 字段未填充
    output = S4_TEMPLATE  # 仍含占位符
    result = validate_output(output, "S4")
    test("VAL-03 占位符未填", result.passed, False)

    # S5 格式检查
    result = validate_output("检测项目列表：xxx", "S5")
    test("VAL-04 S5缺参考标准", any("参考标准" in i for i in result.format_issues), True)

    # S6 格式检查
    result = validate_output("总价 1000", "S6")
    test("VAL-05 S6缺税", any("税" in i for i in result.format_issues), True)

    # S7 声明检查
    result = validate_output("预审报告内容...", "S7")
    test("VAL-06 S7缺声明", any("声明" in i for i in result.format_issues), True)


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — F5 输出模板 测试套件")
    print("覆盖: 模板注册表 + S3-S7模板 + 校验器")

    test_registry()
    test_s3()
    test_s4()
    test_s5()
    test_s6()
    test_s7()
    test_validator()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
