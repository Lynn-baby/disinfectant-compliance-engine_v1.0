"""
F7 风险分级 — 测试套件。

覆盖 PRD 10.2.3 的 12 条用例 + 扩展场景：
- R3: 禁成分/医疗暗示/退单/先上市/规避监管
- R2: 未收录/进口/灰色成分/KB过期
- R1: 全清
- 优先级: R3 > R2 > R1
- 引擎行为映射
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_grading.risk_engine import (
    assess_risk,
    is_blocking,
    requires_disclaimer,
    can_enter_s6,
    RiskAssessment,
    RiskLevel,
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


# ═══════════════════════════════════════════════════════════════════
# R3 触发条件
# ═══════════════════════════════════════════════════════════════════

def test_r3():
    print("\n── R3 高风险触发 ──")

    # 禁成分
    r = assess_risk(ingredient_results=[
        {"name": "三氯生", "status": "prohibited", "reference": ""},
    ])
    test("R3-01 禁成分", r.risk_level, "R3")
    test("R3-01 禁报价", r.can_quote, False)

    # 医疗暗示
    r = assess_risk(medical_keyword_hit=True)
    test("R3-02 医疗暗示", r.risk_level, "R3")

    # 退单历史
    r = assess_risk(historical_rejection=True)
    test("R3-03 退单历史", r.risk_level, "R3")

    # 先上市
    r = assess_risk(prior_market_flag=True)
    test("R3-04 先上市", r.risk_level, "R3")

    # 规避监管
    r = assess_risk(regulation_circumvention=True)
    test("R3-05 规避监管", r.risk_level, "R3")

    # 多条件叠加仍是 R3
    r = assess_risk(
        ingredient_results=[
            {"name": "三氯生", "status": "prohibited", "reference": ""},
        ],
        medical_keyword_hit=True,
        historical_rejection=True,
        domestic_or_imported="进口",
    )
    test("R3-06 多条件叠加→R3", r.risk_level, "R3")
    test("R3-06 多条触发", len(r.trigger_codes) >= 3, True)
    test("R3-06 转人工", r.human_review_required, True)
    test("R3-06 需免责", r.disclaimer_required, True)


# ═══════════════════════════════════════════════════════════════════
# R2 触发条件
# ═══════════════════════════════════════════════════════════════════

def test_r2():
    print("\n── R2 中风险触发 ──")

    # 含未收录成分
    r = assess_risk(ingredient_results=[
        {"name": "纳米银", "status": "unknown", "reference": ""},
    ])
    test("R2-01 未收录成分", r.risk_level, "R2")
    test("R2-01 可报价", r.can_quote, True)
    test("R2-01 需免责", r.disclaimer_required, True)

    # 进口
    r = assess_risk(domestic_or_imported="进口")
    test("R2-02 进口产品", r.risk_level, "R2")

    # 灰色成分
    r = assess_risk(has_grey_area_ingredients=True)
    test("R2-03 灰色成分", r.risk_level, "R2")

    # KB过期
    r = assess_risk(kb_table_expired=True)
    test("R2-04 KB过期", r.risk_level, "R2")

    # 多 R2 叠加仍是 R2
    r = assess_risk(
        ingredient_results=[
            {"name": "纳米银", "status": "unknown", "reference": ""},
        ],
        domestic_or_imported="进口",
        has_grey_area_ingredients=True,
    )
    test("R2-05 多R2叠加→R2", r.risk_level, "R2")
    test("R2-05 多条触发", len(r.trigger_codes) >= 3, True)
    test("R2-05 不转人工", r.human_review_required, False)


# ═══════════════════════════════════════════════════════════════════
# R1 正常
# ═══════════════════════════════════════════════════════════════════

def test_r1():
    print("\n── R1 低风险 ──")

    r = assess_risk(
        ingredient_results=[
            {"name": "酒精", "status": "allowed", "reference": ""},
            {"name": "甘油", "status": "allowed", "reference": ""},
        ],
        domestic_or_imported="国产",
    )
    test("R1-01 全清", r.risk_level, "R1")
    test("R1-01 可报价", r.can_quote, True)
    test("R1-01 不需免责", r.disclaimer_required, False)
    test("R1-01 不转人工", r.human_review_required, False)
    test("R1-01 全清代码", r.trigger_codes, ["all_clear"])

    # 空输入 → R1
    r = assess_risk()
    test("R1-02 空输入→R1", r.risk_level, "R1")


# ═══════════════════════════════════════════════════════════════════
# 优先级验证
# ═══════════════════════════════════════════════════════════════════

def test_priority():
    print("\n── 优先级 R3 > R2 > R1 ──")

    # R3 + R2 → R3
    r = assess_risk(
        ingredient_results=[
            {"name": "三氯生", "status": "prohibited", "reference": ""},
            {"name": "纳米银", "status": "unknown", "reference": ""},
        ],
        domestic_or_imported="进口",
    )
    test("PRI-01 R3+R2→R3", r.risk_level, "R3")
    test("PRI-01 仅含R3触发码", "ingredient_unknown" not in r.trigger_codes, True)

    # R2 + R1 → R2
    r = assess_risk(
        ingredient_results=[
            {"name": "酒精", "status": "allowed", "reference": ""},
        ],
        domestic_or_imported="进口",
    )
    test("PRI-02 R2+R1→R2", r.risk_level, "R2")


# ═══════════════════════════════════════════════════════════════════
# 引擎行为映射
# ═══════════════════════════════════════════════════════════════════

def test_actions():
    print("\n── 引擎行为映射 ──")

    test("ACT-01 R3阻塞", is_blocking("R3"), True)
    test("ACT-02 R2不阻塞", is_blocking("R2"), False)
    test("ACT-03 R1不阻塞", is_blocking("R1"), False)
    test("ACT-04 R3需免责", requires_disclaimer("R3"), True)
    test("ACT-05 R2需免责", requires_disclaimer("R2"), True)
    test("ACT-06 R1不需免责", requires_disclaimer("R1"), False)
    test("ACT-07 R3禁入S6", can_enter_s6("R3"), False)
    test("ACT-08 R2可入S6", can_enter_s6("R2"), True)
    test("ACT-09 R1可入S6", can_enter_s6("R1"), True)


# ═══════════════════════════════════════════════════════════════════
# 成分汇总
# ═══════════════════════════════════════════════════════════════════

def test_summary():
    print("\n── 成分汇总 ──")

    r = assess_risk(ingredient_results=[
        {"name": "酒精", "status": "allowed", "reference": ""},
        {"name": "甘油", "status": "allowed", "reference": ""},
        {"name": "纳米银", "status": "unknown", "reference": ""},
    ])
    s = r.ingredient_results_summary
    test("SUM-01 allowed", s["allowed"], 2)
    test("SUM-02 unknown", s["unknown"], 1)
    test("SUM-03 prohibited", s["prohibited"], 0)

    r = assess_risk(ingredient_results=[
        {"name": "酒精", "status": "allowed", "reference": ""},
        {"name": "三氯生", "status": "prohibited", "reference": ""},
    ])
    s = r.ingredient_results_summary
    test("SUM-04 mixed", s["prohibited"], 1)


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — F7 风险分级 测试套件")
    print("覆盖: R3/R2/R1触发 + 优先级 + 引擎行为")

    test_r3()
    test_r2()
    test_r1()
    test_priority()
    test_actions()
    test_summary()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
