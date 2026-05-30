"""
S1 入口解析 — 测试套件。

覆盖：
- 模板解析（全角/半角冒号、空值跳过、标题行跳过）
- 字段归一化（剂型缩写/产地归一化/客户类型/紧急程度）
- 6必采 Gate 校验
- 剂型二次校验（不在标准值域内）
- 空输入/无输入处理
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entry_merge import (
    main, parse_structured_text, normalize,
    REQUIRED, VALID_DOSAGE_FORMS, DOSAGE_NORMALIZE, ORIGIN_NORMALIZE,
)

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


class MockArgs:
    def __init__(self, structured_text):
        self.params = {"structured_text": structured_text}


def run(text: str) -> dict:
    return asyncio.run(main(MockArgs(text)))


# ═══════════════════════════════════════════════════════════════════
# 边界条件
# ═══════════════════════════════════════════════════════════════════

def test_edge_cases():
    print("\n── 边界条件 ──")

    r = run("")
    test("EDGE-01 空输入ready=False", r["ready"], False)
    test("EDGE-02 空输入有error", len(r["error_message"]) > 0, True)


# ═══════════════════════════════════════════════════════════════════
# 模板解析
# ═══════════════════════════════════════════════════════════════════

def test_parsing():
    print("\n── 模板解析 ──")

    text = (
        "产品名称：维达免洗洗手液\n"
        "剂型：凝胶\n"
        "核心成分：酒精（75%）、甘油、卡波姆\n"
        "宣称功效：消毒、抑菌\n"
        "产地：国产\n"
        "您的角色：品牌方\n"
        "使用场景：家庭\n"
        "已有检测报告：没有\n"
        "退单历史：没有\n"
        "紧急程度：普通"
    )
    fields = parse_structured_text(text)

    test("PAR-01 产品名称", fields.get("product_name"), "维达免洗洗手液")
    test("PAR-02 剂型", fields.get("dosage_form"), "凝胶")
    test("PAR-03 核心成分", fields.get("main_ingredients"), "酒精（75%）、甘油、卡波姆")
    test("PAR-04 宣称功效", fields.get("target_claims"), "消毒、抑菌")
    test("PAR-05 产地", fields.get("domestic_or_imported"), "国产")
    test("PAR-06 您的角色", fields.get("customer_type"), "品牌方")
    test("PAR-07 使用场景", fields.get("usage_scenarios"), "家庭")
    test("PAR-08 紧急程度", fields.get("urgency_level"), "普通")

    # 全角冒号 + 半角冒号混合
    text = "产品名称:测试产品\n剂型：液体"
    fields = parse_structured_text(text)
    test("PAR-09 半角冒号", fields.get("product_name"), "测试产品")
    test("PAR-10 全角冒号", fields.get("dosage_form"), "液体")


# ═══════════════════════════════════════════════════════════════════
# 空值/占位符跳过
# ═══════════════════════════════════════════════════════════════════

def test_empty_value_skip():
    print("\n── 空值跳过 ──")

    text = "产品名称：未提供\n剂型：液体"
    fields = parse_structured_text(text)
    test("SKIP-01 '未提供'视为空", "product_name" in fields, False)
    test("SKIP-02 有效字段仍解析", fields.get("dosage_form"), "液体")

    text = "产品名称：（用户未提供）\n剂型：凝胶"
    fields = parse_structured_text(text)
    test("SKIP-03 全角括号'（用户未提供）'视为空", "product_name" in fields, False)

    text = "产品名称：(用户未提供)\n剂型：凝胶"
    fields = parse_structured_text(text)
    test("SKIP-04 半角括号'(用户未提供)'视为空", "product_name" in fields, False)


# ═══════════════════════════════════════════════════════════════════
# 标题行跳过
# ═══════════════════════════════════════════════════════════════════

def test_title_skip():
    print("\n── 标题行跳过 ──")

    text = (
        "【基础信息】\n"
        "产品名称：测试产品\n"
        "# 可选信息\n"
        "剂型：液体"
    )
    fields = parse_structured_text(text)
    test("TITLE-01 【】标题行跳过", fields.get("product_name"), "测试产品")
    test("TITLE-02 #标题行跳过", fields.get("dosage_form"), "液体")


# ═══════════════════════════════════════════════════════════════════
# 剂型归一化
# ═══════════════════════════════════════════════════════════════════

def test_dosage_normalization():
    print("\n── 剂型归一化 ──")

    tests = [
        ("液", "液体"), ("水", "液体"), ("水剂", "液体"), ("液剂", "液体"),
        ("乳", "膏霜"), ("霜", "膏霜"), ("膏", "膏霜"), ("乳液", "膏霜"),
        ("气雾", "气雾"), ("压力罐", "气雾"), ("喷罐", "气雾"),
    ]
    for raw, expected in tests:
        out = normalize({"dosage_form": raw})
        test(f"DOS-归一化 {raw}→{expected}", out["dosage_form"], expected)

    # 标准剂型不变
    out = normalize({"dosage_form": "凝胶"})
    test("DOS-归一化 标准值不变", out["dosage_form"], "凝胶")


# ═══════════════════════════════════════════════════════════════════
# 产地归一化
# ═══════════════════════════════════════════════════════════════════

def test_origin_normalization():
    print("\n── 产地归一化 ──")

    for raw in ("国内", "中国", "本地"):
        out = normalize({"domestic_or_imported": raw})
        test(f"ORIGIN-归一化 {raw}→国产", out["domestic_or_imported"], "国产")

    for raw in ("海外", "国外", "美国", "日本", "韩国", "欧洲"):
        out = normalize({"domestic_or_imported": raw})
        test(f"ORIGIN-归一化 {raw}→进口", out["domestic_or_imported"], "进口")


# ═══════════════════════════════════════════════════════════════════
# 客户类型归一化
# ═══════════════════════════════════════════════════════════════════

def test_customer_normalization():
    print("\n── 客户类型归一化 ──")

    tests = [
        ("工厂", "代工厂"), ("代工", "代工厂"), ("生产商", "代工厂"),
        ("品牌", "品牌方"), ("品牌商", "品牌方"),
        ("贸易", "贸易商"), ("经销商", "贸易商"),
        ("个人", "其他"), ("创业者", "其他"),
    ]
    for raw, expected in tests:
        out = normalize({"customer_type": raw})
        test(f"CUST-归一化 {raw}→{expected}", out["customer_type"], expected)

    # 不在已知映射中的 → 其他
    out = normalize({"customer_type": "科学家"})
    test("CUST-不在映射→其他", out["customer_type"], "其他")


# ═══════════════════════════════════════════════════════════════════
# 紧急程度归一化
# ═══════════════════════════════════════════════════════════════════

def test_urgency_normalization():
    print("\n── 紧急程度归一化 ──")

    out = normalize({"urgency_level": ""})
    test("URG-01 空值→普通", out["urgency_level"], "普通")

    out = normalize({"urgency_level": "急"})
    test("URG-02 急→加急", out["urgency_level"], "加急")

    out = normalize({"urgency_level": "加急"})
    test("URG-03 加急→加急", out["urgency_level"], "加急")

    out = normalize({"urgency_level": "普通"})
    test("URG-04 普通→普通", out["urgency_level"], "普通")


# ═══════════════════════════════════════════════════════════════════
# 6必采 Gate 校验
# ═══════════════════════════════════════════════════════════════════

def test_required_gate():
    print("\n── 6必采 Gate ──")

    # 完整模板 → ready=True
    full = (
        "产品名称：测试产品\n"
        "剂型：液体\n"
        "核心成分：酒精\n"
        "宣称功效：消毒\n"
        "产地：国产\n"
        "您的角色：品牌方\n"
        "紧急程度：普通"
    )
    r = run(full)
    test("GATE-01 6字段全填→ready", r["ready"], True)
    test("GATE-02 error为空", r["error_message"], "")

    # 缺一个必采字段（产品名称）
    partial = (
        "剂型：液体\n"
        "核心成分：酒精\n"
        "宣称功效：消毒\n"
        "产地：国产\n"
        "您的角色：品牌方"
    )
    r = run(partial)
    test("GATE-03 缺产品名称→ready=False", r["ready"], False)
    test("GATE-04 error含'产品名称'", "产品名称" in r["error_message"], True)

    # 缺多个
    r2 = run("产品名称：测试")
    test("GATE-05 缺5字段→ready=False", r2["ready"], False)


# ═══════════════════════════════════════════════════════════════════
# 剂型二次校验（归一化后仍不在标准值域）
# ═══════════════════════════════════════════════════════════════════

def test_dosage_validation():
    print("\n── 剂型二次校验 ──")

    text = (
        "产品名称：测试产品\n"
        "剂型：胶囊\n"  # 不在 VALID_DOSAGE_FORMS 中
        "核心成分：酒精\n"
        "宣称功效：消毒\n"
        "产地：国产\n"
        "您的角色：品牌方"
    )
    r = run(text)
    test("DOSV-01 无效剂型→ready=False", r["ready"], False)
    test("DOSV-02 error含剂型名", "胶囊" in r["error_message"], True)
    test("DOSV-03 error含有效值提示", "标准列表" in r["error_message"], True)

    # 有效剂型（标准值）
    text = (
        "产品名称：测试产品\n"
        "剂型：液体\n"
        "核心成分：酒精\n"
        "宣称功效：消毒\n"
        "产地：国产\n"
        "您的角色：品牌方"
    )
    r = run(text)
    test("DOSV-04 有效剂型→ready", r["ready"], True)


# ═══════════════════════════════════════════════════════════════════
# 字段完整性
# ═══════════════════════════════════════════════════════════════════

def test_field_definitions():
    print("\n── 字段定义 ──")

    test("FLD-01 6必采字段", len(REQUIRED), 6)
    test("FLD-02 8标准剂型", len(VALID_DOSAGE_FORMS), 8)
    test("FLD-03 11剂型映射", len(DOSAGE_NORMALIZE) >= 10, True)


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — S1 入口解析 测试套件")
    print("覆盖: 模板解析 + 字段归一化 + 6必采Gate + 剂型二次校验")

    test_edge_cases()
    test_parsing()
    test_empty_value_skip()
    test_title_skip()
    test_dosage_normalization()
    test_origin_normalization()
    test_customer_normalization()
    test_urgency_normalization()
    test_required_gate()
    test_dosage_validation()
    test_field_definitions()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
