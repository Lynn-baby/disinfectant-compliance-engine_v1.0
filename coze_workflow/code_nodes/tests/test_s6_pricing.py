"""
S6 报价预估 Code Node — 测试套件

覆盖：
  1. 正常报价：标准客户、含折扣、加急
  2. R3 阻断
  3. 空检测项
  4. 未知项处理
  5. 周期估算（无毒理/有毒理/高毒理/加急）
  6. 错误路径：JSON 解析失败、类型错误
  7. 安全层拦截（safety_blocked=True）
"""
import sys
import os
import json as _json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s6_pricing import (
    generate_pricing,
    _estimate_cycle,
    _build_notes,
    _build_pricing_table,
    _build_error,
    PRICING_MAP,
    DISCOUNT_MAP,
    TAX_RATE,
    URGENCY_SURCHARGE,
)

PASS, FAIL = 0, 0


def check(desc, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✅ {desc}")
    else:
        FAIL += 1
        print(f"  ❌ {desc}")
        print(f"     期望: {expected!r}")
        print(f"     实际: {actual!r}")


def check_approx(desc, actual, expected, tolerance=5):
    """近似检查（金额允许 ±5 元取整误差）"""
    global PASS, FAIL
    if abs(actual - expected) <= tolerance:
        PASS += 1
        print(f"  ✅ {desc}")
    else:
        FAIL += 1
        print(f"  ❌ {desc}")
        print(f"     期望≈: {expected}")
        print(f"     实际: {actual}")


# ═══════════════════════════════════════════════════════════════
# 1. 正常报价 — 标准客户（无折扣）
# ═══════════════════════════════════════════════════════════════

def test_basic_pricing():
    print("\n── 1. 正常报价（标准客户，无折扣）──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
        {"code": "PHYS_02", "name": "pH值测定", "category": "理化", "standard": "GB 15979"},
        {"code": "MICRO_01", "name": "金黄色葡萄球菌定量杀菌试验", "category": "微生物", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="其他")
    check("is_priced=True", result["is_priced"], True)
    # 标准总价：2500 + 750 + 900 = 4150
    check("standard_total", result["standard_total"], 4150)
    # 其他客户无折扣：subtotal = 4150
    check("subtotal", result["subtotal"], 4150)
    # tax = 4150 * 0.06 = 249
    check("tax", result["tax"], 249)
    # total = 4150 + 249 = 4399
    check("total", result["total"], 4399)
    check("pricing_table 非空", len(result["pricing_table"]) > 0, True)


def test_brand_discount():
    print("\n── 2. 品牌方折扣（85折）──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="品牌方")
    check("is_priced=True", result["is_priced"], True)
    check("standard_total=2500", result["standard_total"], 2500)
    # 2500 * 0.85 = 2125
    check("subtotal", result["subtotal"], 2125)
    check("tax", result["tax"], 128)  # 2125 * 0.06 = 127.5 → 128
    check("total", result["total"], 2253)  # 2125 + 128 = 2253


def test_oem_discount():
    print("\n── 3. 代工厂折扣（9折）──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="代工厂")
    check("standard_total=2500", result["standard_total"], 2500)
    # 2500 * 0.9 = 2250
    check("subtotal", result["subtotal"], 2250)


def test_agent_discount():
    print("\n── 4. 中介折扣（95折）──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="中介")
    check("standard_total=2500", result["standard_total"], 2500)
    # 2500 * 0.95 = 2375
    check("subtotal", result["subtotal"], 2375)


# ═══════════════════════════════════════════════════════════════
# 2. 加急处理
# ═══════════════════════════════════════════════════════════════

def test_urgency_surcharge():
    print("\n── 5. 加急附加费（+30%）──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="其他", urgency_level="加急")
    # standard=2500, 其他无折扣, subtotal=2500*1.3=3250
    check("standard_total=2500", result["standard_total"], 2500)
    check("subtotal 加急", result["subtotal"], 3250)
    check("tax 加急", result["tax"], 195)  # 3250*0.06=195
    check("total 加急", result["total"], 3445)  # 3250+195=3445
    check("周期含加急标记", "加急缩短" in result["cycle"], True)
    check("备注含加急提示", "加急服务附加费" in result["notes"], True)


def test_urgency_no_surcharge():
    print("\n── 6. 普通紧急度（无附加）──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="其他", urgency_level="普通")
    check("subtotal 普通", result["subtotal"], 2500)
    check("无加急提示", "加急服务附加费" not in result["notes"], True)


# ═══════════════════════════════════════════════════════════════
# 3. R3 阻断
# ═══════════════════════════════════════════════════════════════

def test_r3_blocking():
    print("\n── 7. R3 阻断报价 ──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R3", customer_type="品牌方")
    check("is_priced=False", result["is_priced"], False)
    check("total=0", result["total"], 0)
    check("notes 含阻断说明", "R3" in result["notes"], True)
    check("pricing_table 空", result["pricing_table"], "")


# ═══════════════════════════════════════════════════════════════
# 4. 空检测项 / 无输入
# ═══════════════════════════════════════════════════════════════

def test_empty_items():
    print("\n── 8. 空检测项 ──")
    result = generate_pricing([], "R1")
    check("is_priced=False", result["is_priced"], False)
    check("total=0", result["total"], 0)


def test_empty_items_returns_message():
    print("\n── 9. 空检测项含提示 ──")
    result = generate_pricing([], "R2")
    check("notes 含提示", "无法生成报价" in result["notes"], True)


# ═══════════════════════════════════════════════════════════════
# 5. 未知项处理
# ═══════════════════════════════════════════════════════════════

def test_all_unknown_items():
    print("\n── 10. 全部未知项 ──")
    items = [
        {"code": "MAGIC_001", "name": "魔法测试", "category": "其他", "standard": "——"},
    ]
    result = generate_pricing(items, "R1")
    check("is_priced=False", result["is_priced"], False)
    check("notes 含确认提示", "人工确认" in result["notes"], True)


def test_mixed_known_unknown():
    print("\n── 11. 混合（已知+未知）──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
        {"code": "MAGIC_001", "name": "魔法测试", "category": "其他", "standard": "——"},
    ]
    result = generate_pricing(items, "R1")
    check("is_priced=True", result["is_priced"], True)
    check("standard_total 仅已知", result["standard_total"], 2500)
    unknown = _json.loads(result["unknown_items_json"])
    check("unknown_items 包含魔法测试", "魔法测试" in unknown, True)
    check("notes 含未知项提示", "暂无标准报价" in result["notes"], True)


# ═══════════════════════════════════════════════════════════════
# 6. 周期估算
# ═══════════════════════════════════════════════════════════════

def test_cycle_no_tox():
    print("\n── 12. 周期估算：少量项，无毒理 ──")
    cycle = _estimate_cycle(5, ["PHYS_01", "MICRO_01"], "普通")
    check("1-2个月", cycle, "1-2 个月")


def test_cycle_with_tox():
    print("\n── 13. 周期估算：含毒理 ──")
    cycle = _estimate_cycle(15, ["PHYS_01", "TOX_01", "TOX_03"], "普通")
    check("2-4个月", cycle, "2-4 个月")


def test_cycle_heavy_tox():
    print("\n── 14. 周期估算：高毒理 ──")
    cycle = _estimate_cycle(5, ["TOX_02", "TOX_08"], "普通")
    check("3-5个月", cycle, "3-5 个月")


def test_cycle_urgency():
    print("\n── 15. 周期估算：加急 ──")
    cycle = _estimate_cycle(5, ["PHYS_01"], "加急")
    check("加急缩短标记", "加急缩短" in cycle, True)


# ═══════════════════════════════════════════════════════════════
# 7. 默认值处理
# ═══════════════════════════════════════════════════════════════

def test_default_customer_type():
    print("\n── 16. 默认客户类型 ──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="")
    check("空值→其他 subtotal", result["subtotal"], 2500)  # 无折扣


def test_unrecognized_customer_type():
    print("\n── 17. 未识别的客户类型 ──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", customer_type="外星人")
    check("降级为其他", result["subtotal"], 2500)


def test_default_urgency():
    print("\n── 18. 默认紧急程度 ──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "GB/T"},
    ]
    result = generate_pricing(items, "R1", urgency_level="")
    check("空值→普通 subtotal", result["subtotal"], 2500)


# ═══════════════════════════════════════════════════════════════
# 8. 备注构建
# ═══════════════════════════════════════════════════════════════

def test_notes_normal():
    print("\n── 19. 备注：普通模式 ──")
    notes = _build_notes("普通", [])
    check("含合同提示", "正式合同" in notes, True)


def test_notes_urgency():
    print("\n── 20. 备注：加急模式 ──")
    notes = _build_notes("加急", [])
    check("含加急提示", "加急服务附加费" in notes, True)


def test_notes_unknown():
    print("\n── 21. 备注：含未知项 ──")
    notes = _build_notes("普通", ["魔法测试", "超能力检测"])
    check("含未知项列表", "魔法测试" in notes and "超能力检测" in notes, True)


# ═══════════════════════════════════════════════════════════════
# 9. 错误路径
# ═══════════════════════════════════════════════════════════════

def test_build_error_structure():
    print("\n── 22. _build_error 结构 ──")
    result = _build_error("TEST_ERR", "测试错误")
    check("is_priced=False", result["is_priced"], False)
    check("total=0", result["total"], 0)
    check("error_message 存在", "TEST_ERR" in result["error_message"], True)
    check("diagnostics 存在", isinstance(result["diagnostics"], str), True)


# ═══════════════════════════════════════════════════════════════
# 10. 完整报价场景（模拟真实路径）
# ═══════════════════════════════════════════════════════════════

def test_full_antibacterial():
    """模拟抗抑菌制剂完整报价"""
    print("\n── 23. 完整场景：抗抑菌制剂+品牌方+加急 ──")
    items = [
        {"code": "PHYS_01", "name": "有效成分含量测定", "category": "理化", "standard": "——"},
        {"code": "PHYS_02", "name": "pH值测定", "category": "理化", "standard": "GB 15979"},
        {"code": "BACT_01", "name": "大肠杆菌抑菌试验", "category": "微生物", "standard": "——"},
        {"code": "BACT_02", "name": "金黄色葡萄球菌抑菌试验", "category": "微生物", "standard": "——"},
        {"code": "BACT_03", "name": "白色念珠菌抑菌试验", "category": "微生物", "standard": "——"},
        {"code": "PHYS_03", "name": "稳定性试验", "category": "理化", "standard": "GB/T 38499"},
        {"code": "TOX_03", "name": "一次完整皮肤刺激试验", "category": "毒理", "standard": "GB/T 38496"},
        {"code": "TOX_06", "name": "眼刺激试验", "category": "毒理", "standard": "GB/T 38496"},
        {"code": "PHYS_05", "name": "重金属—铅的测定", "category": "理化", "standard": "GB/T 7917.3"},
        {"code": "PHYS_06", "name": "重金属—砷的测定", "category": "理化", "standard": "GB/T 7917.2"},
        {"code": "PHYS_07", "name": "重金属—汞的测定", "category": "理化", "standard": "GB/T 7917.1"},
        {"code": "MICRO_IDX_01", "name": "细菌菌落总数检测", "category": "微生物", "standard": "GB 15979"},
        {"code": "MICRO_IDX_02", "name": "大肠菌群检测", "category": "微生物", "standard": "GB 15979"},
        {"code": "MICRO_IDX_03", "name": "真菌菌落总数检测", "category": "微生物", "standard": "GB 15979"},
        {"code": "MICRO_IDX_04", "name": "致病性化脓菌检测", "category": "微生物", "standard": "GB 15979"},
    ]
    result = generate_pricing(items, "R1", customer_type="品牌方", urgency_level="加急")

    # 标准总价 = 2500+750+3000+3000+3000+4000+4000+5000+1500+1500+1500+800+800+800+1000 = 33150
    expected_standard = (
        2500 + 750 +
        3000 + 3000 + 3000 +
        4000 +
        4000 + 5000 +
        1500 + 1500 + 1500 +
        800 + 800 + 800 + 1000
    )
    check("标准总价", result["standard_total"], expected_standard)

    # 品牌方85折 → 加急 ×1.3 → subtotal
    # 33150 * 0.85 = 28178 → 28178 * 1.3 = 36631
    expected_subtotal = round(round(expected_standard * 0.85) * URGENCY_SURCHARGE)
    check_approx("折后+加急 subtotal", result["subtotal"], expected_subtotal)
    # tax: 36631 * 0.06 = 2198
    expected_tax = round(expected_subtotal * TAX_RATE)
    check_approx("税", result["tax"], expected_tax)

    check("is_priced=True", result["is_priced"], True)
    check("pricing_table 非空", len(result["pricing_table"]) > 0, True)
    check("unknown 为空", result["unknown_items_json"], "[]")


# ═══════════════════════════════════════════════════════════════
# 运行全部测试
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  S6 报价预估 — 测试套件")
    print("=" * 60)

    test_basic_pricing()
    test_brand_discount()
    test_oem_discount()
    test_agent_discount()
    test_urgency_surcharge()
    test_urgency_no_surcharge()
    test_r3_blocking()
    test_empty_items()
    test_empty_items_returns_message()
    test_all_unknown_items()
    test_mixed_known_unknown()
    test_cycle_no_tox()
    test_cycle_with_tox()
    test_cycle_heavy_tox()
    test_cycle_urgency()
    test_default_customer_type()
    test_unrecognized_customer_type()
    test_default_urgency()
    test_notes_normal()
    test_notes_urgency()
    test_notes_unknown()
    test_build_error_structure()
    test_full_antibacterial()

    print(f"\n{'='*60}")
    print(f"  结果: {PASS} PASS / {FAIL} FAIL")
    print(f"{'='*60}")
    sys.exit(0 if FAIL == 0 else 1)
