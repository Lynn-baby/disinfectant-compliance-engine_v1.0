"""
F2 信息采集 — 测试套件。

覆盖：
- 字段定义完整性
- 剂型值域校验
- 初始化采集状态
- 单轮提取+合并
- 多轮完整采集流程（模拟 S1 对话）
- 追问目标选择（最多2个，按优先级）
- 确认摘要构建
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from info_collection.field_definitions import (
    FIELD_DEFINITIONS,
    REQUIRED_FIELDS,
    OPTIONAL_FIELDS,
    validate_dosage_form,
    FieldDef,
)
from info_collection.collection_engine import (
    init_collection,
    process_turn,
    CollectionState,
    CollectionTurn,
    _pick_follow_up_targets,
    _build_confirmed_summary,
    _has_value,
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
# 字段定义
# ═══════════════════════════════════════════════════════════════════

def test_field_defs():
    print("\n── 字段定义 ──")

    test("FLD-01 6必采", len(REQUIRED_FIELDS), 6)
    test("FLD-02 4选采", len(OPTIONAL_FIELDS), 4)
    test("FLD-03 共10字段", len(FIELD_DEFINITIONS), 10)

    for f in REQUIRED_FIELDS:
        fdef = FIELD_DEFINITIONS[f]
        test(f"FLD-04 {f}.required", fdef.required, True)

    for f in OPTIONAL_FIELDS:
        fdef = FIELD_DEFINITIONS[f]
        test(f"FLD-05 {f}.required", fdef.required, False)

    # 优先级：必采在前
    req_priorities = [FIELD_DEFINITIONS[f].priority for f in REQUIRED_FIELDS]
    opt_priorities = [FIELD_DEFINITIONS[f].priority for f in OPTIONAL_FIELDS]
    test("FLD-06 必采优先级<选采", max(req_priorities) < min(opt_priorities), True)


# ═══════════════════════════════════════════════════════════════════
# 剂型校验
# ═══════════════════════════════════════════════════════════════════

def test_dosage_validation():
    print("\n── 剂型校验 ──")

    valid, err = validate_dosage_form("液体")
    test("DOS-01 液体合法", valid, True)

    valid, err = validate_dosage_form("湿巾")
    test("DOS-02 湿巾合法", valid, True)

    valid, err = validate_dosage_form("胶囊")
    test("DOS-03 胶囊不合法", valid, False)

    valid, err = validate_dosage_form("")
    test("DOS-04 空值不合法", valid, False)

    valid, err = validate_dosage_form("液")
    test("DOS-05 简称接受", valid, True)


# ═══════════════════════════════════════════════════════════════════
# 初始化
# ═══════════════════════════════════════════════════════════════════

def test_init():
    print("\n── 初始化采集状态 ──")

    state = init_collection()
    test("INIT-01 ready=False", state.ready, False)
    test("INIT-02 缺6字段", len(state.missing_required), 6)

    # 带已有变量的初始化
    state = init_collection({"product_name": "洗手液", "dosage_form": "液体"})
    test("INIT-03 2已填", len(state.filled), 2)
    test("INIT-04 缺4", len(state.missing_required), 4)


# ═══════════════════════════════════════════════════════════════════
# 单轮处理
# ═══════════════════════════════════════════════════════════════════

def test_single_turn():
    print("\n── 单轮采集 ──")

    # 第1轮：用户提供产品名+剂型
    state = init_collection()
    turn = process_turn(
        "免洗洗手液，液体剂型",
        state,
        newly_extracted={"product_name": "免洗洗手液", "dosage_form": "液体"},
    )
    test("TURN-01 未就绪", turn.ready_to_advance, False)
    test("TURN-02 2字段已填", "产品名称" in turn.next_message, True)
    test("TURN-03 追问消息非空", len(turn.next_message) > 0, True)

    # 第2轮：用户提供成分
    turn = process_turn(
        "75%酒精、甘油",
        state,
        newly_extracted={"main_ingredients": ["酒精（75%）", "甘油"]},
    )
    test("TURN-04 仍缺3字段", state.ready, False)

    # 第3轮：提供功效+产地
    turn = process_turn(
        "抑菌，国产的",
        state,
        newly_extracted={"target_claims": ["抑菌"], "domestic_or_imported": "国产"},
    )
    test("TURN-05 仍缺1字段", state.ready, False)

    # 第4轮：提供最后字段
    turn = process_turn(
        "我是品牌方",
        state,
        newly_extracted={"customer_type": "品牌方"},
    )
    test("TURN-06 就绪", turn.ready_to_advance, True)
    test("TURN-07 含确认摘要", "信息采集完成" in turn.next_message, True)
    test("TURN-08 6字段全填", len(state.filled), 6)


# ═══════════════════════════════════════════════════════════════════
# 追问目标选择
# ═══════════════════════════════════════════════════════════════════

def test_target_selection():
    print("\n── 追问目标选择 ──")

    ask_counts = {f: 0 for f in REQUIRED_FIELDS}

    # 全缺 → 选前2个（product_name + dosage_form，优先级1和2）
    targets = _pick_follow_up_targets(REQUIRED_FIELDS, ask_counts, max_ask=2)
    test("TGT-01 缺6选2", len(targets), 2)
    test("TGT-02 第1个是product_name", targets[0], "product_name")
    test("TGT-03 第2个是dosage_form", targets[1], "dosage_form")

    # 缺3 → 全选但max=2 → 选2
    missing = ["main_ingredients", "target_claims", "customer_type"]
    targets = _pick_follow_up_targets(missing, ask_counts, max_ask=2)
    test("TGT-04 缺3选2", len(targets), 2)
    test("TGT-05 按优先级", targets[0], "main_ingredients")

    # 缺1 → 选1
    missing = ["customer_type"]
    targets = _pick_follow_up_targets(missing, ask_counts, max_ask=2)
    test("TGT-06 缺1选1", len(targets), 1)


# ═══════════════════════════════════════════════════════════════════
# 确认摘要
# ═══════════════════════════════════════════════════════════════════

def test_summary():
    print("\n── 确认摘要 ──")

    filled = {
        "product_name": "免洗洗手液",
        "dosage_form": "液体",
        "main_ingredients": "酒精（75%）、甘油",
        "target_claims": "抑菌",
        "domestic_or_imported": "国产",
        "customer_type": "品牌方",
    }
    summary = _build_confirmed_summary(filled)
    test("SUM-01 含产品名称", "产品名称" in summary, True)
    test("SUM-02 含剂型", "剂型" in summary, True)
    test("SUM-03 含成分", "核心成分" in summary, True)
    test("SUM-04 含产地", "产地" in summary, True)

    # 空字段不显示
    summary = _build_confirmed_summary({"product_name": "洗手液"})
    test("SUM-05 仅显已填", "剂型" not in summary, True)


# ═══════════════════════════════════════════════════════════════════
# 值域校验
# ═══════════════════════════════════════════════════════════════════

def test_validation():
    print("\n── 值域校验 ──")

    state = init_collection({
        "product_name": "测试", "dosage_form": "胶囊",
        "domestic_or_imported": "日本",
    })
    process_turn("补充", state, newly_extracted={})

    test("VAL-01 剂型校验错", "dosage_form" in state.validation_errors, True)
    test("VAL-02 产地校验错", "domestic_or_imported" in state.validation_errors, True)

    # 修正后错误消失
    state.filled["dosage_form"] = "液体"
    state.filled["domestic_or_imported"] = "进口"
    process_turn("补充", state, newly_extracted={})
    test("VAL-03 修正后无错", len(state.validation_errors), 0)


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — F2 信息采集 测试套件")
    print("覆盖: 字段定义 + 剂型校验 + 多轮采集 + 追问选择")

    test_field_defs()
    test_dosage_validation()
    test_init()
    test_single_turn()
    test_target_selection()
    test_summary()
    test_validation()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
