"""
S5 检测方案生成 — 单元测试
运行: python3 test_test_plan_generator.py
"""

import json
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(__file__))
from test_plan_generator import generate_test_plan, _build_error, _coerce_bool

PASS = 0
FAIL = 0


def test(name, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")
        print(f"     expected: {expected}")
        print(f"     actual:   {actual}")


def test_contains(name, items, expected_codes):
    """检查检测项列表是否包含所有期望的code（不检查多余项）。"""
    global PASS, FAIL
    actual_codes = {item["code"] for item in items}
    expected_set = set(expected_codes)
    missing = expected_set - actual_codes
    if not missing:
        PASS += 1
        print(f"  ✅ {name} ({len(items)}项)")
    else:
        FAIL += 1
        print(f"  ❌ {name}")
        print(f"     缺失: {missing}")


def test_item_count(name, total, expected_min, expected_max=None):
    """检查检测项总数是否在预期范围内。"""
    global PASS, FAIL
    if expected_max is None:
        expected_max = expected_min
    if expected_min <= total <= expected_max:
        PASS += 1
        print(f"  ✅ {name} ({total}项)")
    else:
        FAIL += 1
        print(f"  ❌ {name}: {total}项, 预期 {expected_min}-{expected_max}")


# ═══════════════════════════════════════════════════════════════
# 基础检测包测试 — 对应 PRD 10.2.5
# ═══════════════════════════════════════════════════════════════

print("── 基础检测包（品类×剂型）──")

# ID-TESTPLAN-01: 第二类（抗抑菌制剂）+ 液体 → 7项核心检测
plan = generate_test_plan("第二类", "抗抑菌制剂", "液体", "")
test("TP-01 抗抑菌+液体→已分类", plan["is_classified"], True)
test_item_count("TP-01 项数", plan["total_count"], 13, 16)
expected_01 = {"PHYS_01", "PHYS_02", "PHYS_03", "PHYS_05", "PHYS_06", "PHYS_07",
               "BACT_01", "BACT_02", "BACT_03",
               "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
               "TOX_03", "TOX_06"}
test_contains("TP-01 核心项", plan["test_items"], expected_01)

# ID-TESTPLAN-02: 第二类（消毒剂）+ 液体 → 含杀菌试验(非抑菌)
plan = generate_test_plan("第二类", "消毒剂", "液体", "")
test("TP-02 消毒剂+液体→已分类", plan["is_classified"], True)
expected_02 = {"PHYS_01", "PHYS_02", "PHYS_03", "PHYS_05", "PHYS_06", "PHYS_07",
               "MICRO_01", "MICRO_02", "MICRO_03",
               "MICRO_IDX_01", "MICRO_IDX_02"}
test_contains("TP-02 核心项（杀菌非抑菌）", plan["test_items"], expected_02)

# ID-TESTPLAN-03: 第二类（抗抑菌制剂）+ 湿巾 → 基础+载体
plan = generate_test_plan("第二类", "抗抑菌制剂", "湿巾", "")
test("TP-03 抗抑菌+湿巾→已分类", plan["is_classified"], True)
test_contains("TP-03 含载体项", plan["test_items"], {"OTHER_01", "OTHER_02"})

# ID-TESTPLAN-04: 第二类（消毒剂）+ 气雾 → 基础+压力容器
plan = generate_test_plan("第二类", "消毒剂", "气雾", "")
test("TP-04 消毒剂+气雾→已分类", plan["is_classified"], True)
test_contains("TP-04 含压力容器项", plan["test_items"], {"OTHER_03", "OTHER_04"})

# ID-TESTPLAN-05: 第一类 + 液体
plan = generate_test_plan("第一类", "", "液体", "")
test("TP-05 第一类+液体→已分类", plan["is_classified"], True)
test_contains("TP-05 含毒理/模拟现场", plan["test_items"],
              {"TOX_01", "TOX_03", "TOX_08", "MICRO_10"})

# ID-TESTPLAN-06: 第三类 + 湿巾 → 仅微生物指标
plan = generate_test_plan("第三类", "卫生用品", "湿巾", "")
test("TP-06 第三类+湿巾→已分类", plan["is_classified"], True)
test_contains("TP-06 微生物指标", plan["test_items"],
              {"MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04"})

# ID-TESTPLAN-07: 未分类 → 返回错误
plan = generate_test_plan("未分类", "", "", "")
test("TP-07 未分类→无法生成", plan["is_classified"], False)
test("TP-07 错误信息非空", bool(plan["error_message"]), True)

# ID-TESTPLAN-08: 剂型不在表中 → 兜底匹配
plan = generate_test_plan("第二类", "消毒剂", "泡沫", "")
test("TP-08 泡沫剂型→兜底", plan["is_classified"], True)


# ═══════════════════════════════════════════════════════════════
# 宣称增量测试 — 对应 PRD 10.2.6
# ═══════════════════════════════════════════════════════════════

print("\n── 宣称增量检测 ──")

# ID-CLAIM-01: "抑菌"
plan = generate_test_plan("第二类", "抗抑菌制剂", "液体", "抑菌")
bact_codes = {"BACT_01", "BACT_02", "BACT_03", "BACT_04"}
test_contains("CLAIM-01 抑菌→增量抑菌试验", plan["test_items"], bact_codes)

# ID-CLAIM-02: "抗菌"
plan = generate_test_plan("第二类", "抗抑菌制剂", "液体", "抗菌")
test_contains("CLAIM-02 抗菌→增量抑菌试验", plan["test_items"], bact_codes)

# ID-CLAIM-03: "长效抑菌"
plan = generate_test_plan("第二类", "抗抑菌制剂", "液体", "长效抑菌")
test_contains("CLAIM-03 长效抑菌→持效性", plan["test_items"], {"BACT_05"})

# ID-CLAIM-04: "母婴适用"
plan = generate_test_plan("第二类", "消毒剂", "液体", "母婴适用")
test_contains("CLAIM-04 母婴→毒理增量", plan["test_items"], {"TOX_03", "TOX_01"})

# ID-CLAIM-05: "免洗"
plan = generate_test_plan("第二类", "消毒剂", "液体", "免洗")
test_contains("CLAIM-05 免洗→残留量检测", plan["test_items"], {"PHYS_09"})

# ID-CLAIM-06: "食品工业"
plan = generate_test_plan("第二类", "消毒剂", "液体", "适用于食品工业")
test_contains("CLAIM-06 食品→GB 14930", plan["test_items"], {"OTHER_06"})

# ID-CLAIM-07: "清洁" — 不增加
plan_clean = generate_test_plan("第二类", "消毒剂", "液体", "清洁")
plan_base = generate_test_plan("第二类", "消毒剂", "液体", "")
test("CLAIM-07 清洁无增量", plan_clean["total_count"], plan_base["total_count"])

# ID-CLAIM-08: "消毒" — 增量杀菌试验（消毒剂基础包已含，去重后不增加）
plan = generate_test_plan("第二类", "消毒剂", "液体", "消毒")
# 基础包已含MICRO_01-03，宣称消毒不应重复增加
test("CLAIM-08 消毒→去重", plan["total_count"], plan_base["total_count"])

# ID-CLAIM-09: "可杀灭XX病毒" → 触发安全层 R3
plan = generate_test_plan("第二类", "消毒剂", "液体", "可杀灭新冠病毒")
test("CLAIM-09 病毒宣称→安全拦截", plan["safety_blocked"], True)
test_in_detail = bool(plan["safety_detail"])
test("CLAIM-09 拦截详情非空", test_in_detail, True)

# ID-CLAIM-10: 多个宣称叠加 → 取并集+去重
plan = generate_test_plan("第二类", "抗抑菌制剂", "液体", "抑菌、母婴适用、免洗")
test_contains("CLAIM-10 多宣称并集",
              plan["test_items"],
              {"BACT_01", "BACT_02", "BACT_03", "BACT_04",
               "TOX_03", "TOX_01", "PHYS_09"})

# ID-CLAIM-11: 非标准宣称 → non_standard 列表
plan = generate_test_plan("第二类", "消毒剂", "液体", "除螨、除甲醛")
test("CLAIM-11 非标宣称", len(plan["non_standard"]), 2)

# ═══════════════════════════════════════════════════════════════
# 综合场景
# ═══════════════════════════════════════════════════════════════

print("\n── 综合场景 ──")

# Golden Path: 抑菌洗手液
plan = generate_test_plan("第二类", "抗抑菌制剂", "液体", "抑菌、清洁")
test("E2E-01 抑菌洗手液", plan["is_classified"], True)
test_item_count("E2E-01 项数（基础13+抑菌增量）", plan["total_count"], 13, 17)
print(f"    summary: {plan['summary']}")

# 消毒液
plan = generate_test_plan("第二类", "消毒剂", "液体", "消毒")
test("E2E-02 消毒液", plan["is_classified"], True)
print(f"    summary: {plan['summary']}")

# 含病毒宣称（R3触发）
plan = generate_test_plan("第二类", "消毒剂", "液体", "消毒、抗病毒")
test("E2E-03 病毒→仍生成基础方案", plan["is_classified"], True)
test("E2E-03 安全拦截", plan["safety_blocked"], True)

# 第一类皮肤黏膜消毒剂
plan = generate_test_plan("第一类", "", "液体", "皮肤消毒、黏膜消毒")
test("E2E-04 第一类皮肤黏膜", plan["is_classified"], True)
test_item_count("E2E-04 项数（含毒理全套）", plan["total_count"], 12, 30)


# ═══════════════════════════════════════════════════════════════
# 排序验证
# ═══════════════════════════════════════════════════════════════

print("\n── 排序验证 ──")

plan = generate_test_plan("第二类", "抗抑菌制剂", "液体", "抑菌、母婴适用")
cats = [item["category"] for item in plan["test_items"]]
cat_order = {"理化": 1, "微生物": 2, "毒理": 3, "其他": 4}
cat_nums = [cat_order.get(c, 99) for c in cats]
is_sorted = all(cat_nums[i] <= cat_nums[i + 1] for i in range(len(cat_nums) - 1))
test("SORT-01 按理化→微生物→毒理→其他排序", is_sorted, True)
if not is_sorted:
    print(f"     实际顺序: {cats}")


# ═══════════════════════════════════════════════════════════════
# Coze main() 集成测试
# ═══════════════════════════════════════════════════════════════

class MockArgs:
    """模拟 Coze 运行时的 args 对象。"""
    def __init__(self, params: dict):
        self.params = self._Params(params)

    class _Params:
        def __init__(self, d: dict):
            self._d = d
        def get(self, key, default=None):
            return self._d.get(key, default)


async def _call_main(params: dict) -> dict:
    """调用 main() 并返回结果。"""
    from test_plan_generator import main
    args = MockArgs(params)
    return await main(args)


async def test_main():
    print("\n── Coze main() 集成 ──")

    # 正常路径：抗抑菌制剂+液体
    r = await _call_main({
        "product_category": "第二类",
        "sub_type": "抗抑菌制剂",
        "dosage_form": "液体",
        "target_claims": "抑菌",
    })
    test("MAIN-01 正常路径→已分类", r["is_classified"], True)
    test("MAIN-01 有检测项", r["test_total_count"] > 0, True)
    test("MAIN-01 test_items_json非空", len(r["test_items_json"]) > 2, True)

    # 消毒剂+液体（无宣称）
    r = await _call_main({
        "product_category": "第二类",
        "sub_type": "消毒剂",
        "dosage_form": "液体",
        "target_claims": "",
    })
    test("MAIN-02 消毒剂→已分类", r["is_classified"], True)
    test("MAIN-02 无宣称增量", r["incremental_count"], 0)

    # 未分类 → 错误
    r = await _call_main({
        "product_category": "",
        "sub_type": "",
        "dosage_form": "",
        "target_claims": "",
    })
    test("MAIN-03 空分类→is_classified=False", r["is_classified"], False)
    test("MAIN-03 有错误信息", bool(r["error_message"]), True)

    # R3 风险阻断
    r = await _call_main({
        "product_category": "第二类",
        "sub_type": "消毒剂",
        "dosage_form": "液体",
        "target_claims": "消毒",
        "risk_level": "R3",
    })
    test("MAIN-04 R3→safety_blocked", r["safety_blocked"], True)
    test("MAIN-04 R3→禁生成", r["is_classified"], False)
    test("MAIN-04 R3→无检测项", r["test_total_count"], 0)

    # risk_level=R2（应正常生成）
    r = await _call_main({
        "product_category": "第二类",
        "sub_type": "消毒剂",
        "dosage_form": "液体",
        "target_claims": "",
        "risk_level": "R2",
    })
    test("MAIN-05 R2→正常生成", r["is_classified"], True)


async def test_main_errors():
    print("\n── Coze main() 错误路径 ──")

    # args 无 params 也无 get（dict 接口正常）
    r = await _call_main({
        "product_category": "第二类",
        "sub_type": "消毒剂",
        "dosage_form": "液体",
    })
    test("ERR-01 缺target_claims→仍正常", r["is_classified"], True)

    # 所有字段为空
    r = await _call_main({})
    test("ERR-02 全空→is_classified=False", r["is_classified"], False)

    # risk_level=R3 优先级高于正常输入
    r = await _call_main({
        "product_category": "第二类",
        "sub_type": "消毒剂",
        "dosage_form": "液体",
        "target_claims": "消毒",
        "risk_level": "R3",
    })
    test("ERR-03 R3阻断→有safety_detail", bool(r["safety_detail"]), True)


def test_build_error():
    print("\n── 错误构建 ──")

    r = _build_error("TEST_CODE", "测试错误消息")
    test("ERRBLD-01 is_classified=False", r["is_classified"], False)
    test("ERRBLD-02 空检测项", r["test_items_json"], "[]")
    test("ERRBLD-03 total_count=0", r["test_total_count"], 0)
    test("ERRBLD-04 diagnostics存在", "diagnostics" in r, True)
    test("ERRBLD-05 错误信息含code", "TEST_CODE" in r["error_message"], True)


# ═══════════════════════════════════════════════════════════════
# Boolean 强制转换
# ═══════════════════════════════════════════════════════════════

def test_boolean_coercion():
    print("\n── Boolean 强制转换 ──")

    test("BOOL-01 True→True", _coerce_bool(True), True)
    test("BOOL-02 False→False", _coerce_bool(False), False)
    test("BOOL-03 'true'→True", _coerce_bool("true"), True)
    test("BOOL-04 'false'→False", _coerce_bool("false"), False)
    test("BOOL-05 'FALSE'→False", _coerce_bool("FALSE"), False)
    test("BOOL-06 None→False", _coerce_bool(None), False)
    test("BOOL-07 ''→False", _coerce_bool(""), False)
    test("BOOL-08 1→True", _coerce_bool(1), True)
    test("BOOL-09 0→False", _coerce_bool(0), False)


# ═══════════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — S5 检测方案生成 测试套件")
    print("覆盖: 基础检测包 / 宣称增量 / 综合场景 / 排序 / main()集成 / 错误路径")
    print()

    # 同步测试（原有 36 条）
    # 基础检测包 + 宣称增量 + 综合场景 + 排序 已在上面运行

    # 异步测试（新增）
    asyncio.run(test_main())
    asyncio.run(test_main_errors())
    test_build_error()
    test_boolean_coercion()

    print(f"\n{'='*50}")
    total = PASS + FAIL
    print(f"通过: {PASS}/{total}")
    if FAIL > 0:
        print(f"失败: {FAIL}/{total}")
        sys.exit(1)
    else:
        print("全部通过！")
        sys.exit(0)
