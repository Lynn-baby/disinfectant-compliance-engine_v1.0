"""
F4 拒答策略 — 测试套件。

覆盖：
- 医疗关键词检测（L1 中断 + L2 警告）
- 7 大边界场景各至少 1 条
- 统一决策引擎集成
- 决策优先级验证
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refusal_strategy.medical_keywords import detect_medical_keywords
from refusal_strategy.edge_case_detector import (
    detect_grey_area_ingredients,
    detect_import_undeclared,
    detect_rejection_history,
    detect_bundle_product,
    detect_prior_market,
    detect_vague_ingredients,
    detect_all_edge_cases,
    EdgeCase,
    EdgeAction,
)
from refusal_strategy.refusal_engine import evaluate, Decision

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
# 医疗关键词检测
# ═══════════════════════════════════════════════════════════════════

def test_medical_keywords():
    print("\n── 医疗关键词检测 ──")

    # L1 强暗示 → 中断
    r = detect_medical_keywords("这个洗手液可以治疗湿疹吗")
    test("MED-01 L1 治疗湿疹", r.detected, True)
    test("MED-01 L1 level", r.level, "L1")
    test("MED-01 L1 中断", r.should_interrupt, True)

    r = detect_medical_keywords("能抗新冠病毒吗")
    test("MED-02 L1 新冠", r.detected, True)
    test("MED-02 L1 中断", r.should_interrupt, True)

    r = detect_medical_keywords("抑制幽门螺杆菌的产品")
    test("MED-03 L1 幽门螺杆", r.detected, True)

    # L2 边界用语 → 警告但不中断
    r = detect_medical_keywords("这个洗手液可以消炎止痒")
    test("MED-04 L2 消炎", r.detected, True)
    test("MED-04 L2 level", r.level, "L2")
    test("MED-04 L2 不中断", r.should_interrupt, False)

    r = detect_medical_keywords("提高免疫力的消毒产品")
    test("MED-05 L2 免疫力", r.detected, True)

    # 正常输入
    r = detect_medical_keywords("洗手液能备案吗")
    test("MED-06 正常输入", r.detected, False)


# ═══════════════════════════════════════════════════════════════════
# 边界场景检测 — 各场景至少 1 条
# ═══════════════════════════════════════════════════════════════════

def test_edge_cases():
    print("\n── 7 大边界场景检测 ──")

    # 5.1.1 成分灰色地带
    r = detect_grey_area_ingredients(["纳米银", "酒精"])
    test("EDGE-01 灰色成分 纳米银", r.triggered, True)
    test("EDGE-01 action=WARN", r.action, EdgeAction.WARN)

    r = detect_grey_area_ingredients(["酒精", "甘油"])
    test("EDGE-02 常规成分不触发", r.triggered, False)

    r = detect_grey_area_ingredients(
        ["植物提取物"],
        kb_hit_statuses=["no_hit"],
    )
    test("EDGE-03 no_hit 触发", r.triggered, True)

    # 5.1.3 进口未声明
    r = detect_import_undeclared("日本进口的消毒喷雾", None)
    test("EDGE-04 进口未声明", r.triggered, True)

    r = detect_import_undeclared("日本进口", "进口")
    test("EDGE-05 已声明不触发", r.triggered, False)

    # 5.1.4 退单隐瞒
    r = detect_rejection_history("之前在别的机构备案没过", None, 0)
    test("EDGE-06 退单信号", r.triggered, True)
    test("EDGE-06 action=PROMPT", r.action, EdgeAction.PROMPT)

    r = detect_rejection_history("退单原因是什么", "declined_to_answer", 2)
    test("EDGE-07 2次回避", r.triggered, True)

    # 5.1.5 套装
    r = detect_bundle_product("我们是一套产品，洗手液加喷雾")
    test("EDGE-08 套装产品", r.triggered, True)
    test("EDGE-08 action=INTERRUPT", r.action, EdgeAction.INTERRUPT)

    r = detect_bundle_product("单个洗手液产品")
    test("EDGE-09 单产品不触发", r.triggered, False)

    # 5.1.6 先上市
    r = detect_prior_market("产品已经在卖了，被举报了才来问")
    test("EDGE-10 先售后补", r.triggered, True)
    test("EDGE-10 action=FAST_TRACK", r.action, EdgeAction.FAST_TRACK)

    r = detect_prior_market("新产品想备案")
    test("EDGE-11 新产品不触发", r.triggered, False)

    # 5.1.7 成分模糊
    r = detect_vague_ingredients(["植物提取物", "酒精"], 0)
    test("EDGE-12 模糊成分", r.triggered, True)
    test("EDGE-12 action=PROMPT", r.action, EdgeAction.PROMPT)

    r = detect_vague_ingredients(["活性成分"], 2)
    test("EDGE-13 2次追问后 BLOCK", r.action, EdgeAction.BLOCK)

    r = detect_vague_ingredients(["酒精", "甘油"], 0)
    test("EDGE-14 具体成分不触发", r.triggered, False)

    # 综合检测
    results = detect_all_edge_cases(
        "纳米银消毒喷雾，已经在卖了",
        ingredients=["纳米银"],
        domestic_or_imported=None,
    )
    test("EDGE-15 多场景同时触发", len(results) >= 2, True)


# ═══════════════════════════════════════════════════════════════════
# 统一决策引擎
# ═══════════════════════════════════════════════════════════════════

def test_refusal_engine():
    print("\n── 统一决策引擎 ──")

    # 安全词 → BLOCK
    d = evaluate("怎么绕备案")
    test("ENG-01 安全词→BLOCK", d.decision, Decision.BLOCK)

    # 医疗 L1 → INTERRUPT
    d = evaluate("能治疗湿疹吗")
    test("ENG-02 医疗L1→INTERRUPT", d.decision, Decision.INTERRUPT)

    # 先上市 → FAST_TRACK
    d = evaluate("产品已经在卖了，被查了")
    test("ENG-03 先上市→FAST_TRACK", d.decision, Decision.FAST_TRACK)
    test("ENG-03 目标 S4", d.fast_track_target, "S4")

    # 套装 → INTERRUPT
    d = evaluate("一套产品，洗手液加喷雾")
    test("ENG-04 套装→INTERRUPT", d.decision, Decision.INTERRUPT)

    # 正常输入 → PASS
    d = evaluate(
        "免洗洗手液，75%酒精，国产，品牌方",
        session_vars={
            "product_name": "洗手液",
            "dosage_form": "液体",
            "main_ingredients": ["酒精"],
            "target_claims": ["抑菌"],
            "domestic_or_imported": "国产",
            "customer_type": "品牌方",
        },
    )
    test("ENG-05 正常输入→PASS", d.decision, Decision.PASS)

    # Gate 不完整 → PROMPT
    d = evaluate(
        "帮我看看这个产品",
        session_vars={"product_name": "洗手液"},
    )
    test("ENG-06 Gate不全→PROMPT", d.decision, Decision.PROMPT)

    # 优先级：安全词 > 医疗 > 边界场景
    d = evaluate("怎么绕备案，我这个产品还能治疗湿疹")
    test("ENG-07 安全词优先级最高", d.decision, Decision.BLOCK)

    d = evaluate("治疗湿疹的产品，已经上市被查了")
    test("ENG-08 医疗>先上市", d.decision, Decision.INTERRUPT)


# ═══════════════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — F4 拒答策略 测试套件")
    print("覆盖: 医疗关键词 + 7边界场景 + 决策引擎")

    test_medical_keywords()
    test_edge_cases()
    test_refusal_engine()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
