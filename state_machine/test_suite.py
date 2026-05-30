"""
F6 状态机 — 测试套件。

覆盖：
- 8 状态正向线性流转 S0→S7
- 各状态可迁移目标验证
- 无效迁移拒绝
- S4 R3 跳转 S7
- 回退触发 + 级联 stale
- 字段修改安全阀（≥3次转人工）
- 回退目标计算
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state_machine.state_definitions import (
    State,
    STATE_TABLE,
    get_rollback_target,
    get_stale_states,
)
from state_machine.state_engine import (
    StateEngine,
    SessionContext,
    TransitionResult,
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
# 状态定义完整性
# ═══════════════════════════════════════════════════════════════════

def test_state_defs():
    print("\n── 状态定义 ──")

    test("DEF-01 8个状态", len(STATE_TABLE), 8)
    for s in State:
        spec = STATE_TABLE.get(s)
        test(f"DEF-02 {s} 存在", spec is not None, True)
        test(f"DEF-02 {s} forward非空", len(spec.forward) > 0 or s == State.S7, True)


# ═══════════════════════════════════════════════════════════════════
# 正向迁移
# ═══════════════════════════════════════════════════════════════════

def test_forward_transitions():
    print("\n── 正向迁移 S0→S7 ──")

    engine = StateEngine()
    ctx = engine.init_session()

    test("FWD-00 初始S0", ctx.current_state, State.S0)

    # S0 → S1
    r = engine.transition(ctx, State.S1)
    test("FWD-01 S0→S1", r.allowed, True)
    test("FWD-01 状态已更新", ctx.current_state, State.S1)

    # S1 → S2
    r = engine.transition(ctx, State.S2)
    test("FWD-02 S1→S2", r.allowed, True)

    # S2 → S3
    r = engine.transition(ctx, State.S3)
    test("FWD-03 S2→S3", r.allowed, True)

    # S3 → S4
    r = engine.transition(ctx, State.S4)
    test("FWD-04 S3→S4", r.allowed, True)

    # S4 → S5 (正常 R1/R2)
    r = engine.transition(ctx, State.S5)
    test("FWD-05 S4→S5", r.allowed, True)

    # S5 → S6
    r = engine.transition(ctx, State.S6)
    test("FWD-06 S5→S6", r.allowed, True)

    # S6 → S7
    r = engine.transition(ctx, State.S7)
    test("FWD-07 S6→S7", r.allowed, True)


# ═══════════════════════════════════════════════════════════════════
# 无效迁移拒绝
# ═══════════════════════════════════════════════════════════════════

def test_invalid_transitions():
    print("\n── 无效迁移拒绝 ──")

    engine = StateEngine()
    ctx = engine.init_session()

    # S0 不能直接跳到 S5
    r = engine.transition(ctx, State.S5)
    test("INV-01 S0→S5 拒绝", r.allowed, False)

    # S1 不能跳到 S4
    ctx.current_state = State.S1
    r = engine.transition(ctx, State.S4)
    test("INV-02 S1→S4 拒绝", r.allowed, False)

    # S6 不能回 S2
    ctx.current_state = State.S6
    r = engine.transition(ctx, State.S2)
    test("INV-03 S6→S2 拒绝（不在backward列表）", r.allowed, False)


# ═══════════════════════════════════════════════════════════════════
# S4 R3 跳转 S7
# ═══════════════════════════════════════════════════════════════════

def test_r3_shortcut():
    print("\n── S4 R3 跳转 S7 ──")

    engine = StateEngine()
    ctx = engine.init_session()
    ctx.current_state = State.S4
    ctx.state_results[State.S4] = {"risk_level": "R3"}

    # R3 → skip S5/S6, go to S7
    r = engine.transition(ctx, State.S7)
    test("R3S-01 S4→S7 允许", r.allowed, True)

    # 验证 advance 在 R3 时去 S7
    ctx2 = engine.init_session()
    ctx2.current_state = State.S4
    ctx2.state_results[State.S4] = {"risk_level": "R3"}
    r = engine.advance(ctx2)
    test("R3S-02 advance R3→S7", r.to_state, State.S7)

    # R1 正常去 S5
    ctx3 = engine.init_session()
    ctx3.current_state = State.S4
    ctx3.state_results[State.S4] = {"risk_level": "R1"}
    r = engine.advance(ctx3)
    test("R3S-03 advance R1→S5", r.to_state, State.S5)


# ═══════════════════════════════════════════════════════════════════
# 回退机制
# ═══════════════════════════════════════════════════════════════════

def test_rollback():
    print("\n── 回退机制 ──")

    engine = StateEngine()
    ctx = engine.init_session()

    # 先跑到 S4
    for s in [State.S1, State.S2, State.S3, State.S4]:
        engine.transition(ctx, s)

    test("RB-01 在S4", ctx.current_state, State.S4)

    # S3→S1 回退（allowed）
    ctx.current_state = State.S3
    r = engine.transition(ctx, State.S1)
    test("RB-02 S3→S1 允许", r.allowed, True)
    test("RB-02 触发回退标记", r.rollback_triggered, True)
    test("RB-02 有stale", len(r.stale_states) > 0, True)

    # S2→S1 回退
    ctx.current_state = State.S2
    r = engine.transition(ctx, State.S1)
    test("RB-03 S2→S1 允许", r.allowed, True)


# ═══════════════════════════════════════════════════════════════════
# 字段变更触发级联 stale
# ═══════════════════════════════════════════════════════════════════

def test_field_change_rollback():
    print("\n── 字段变更回退 ──")

    engine = StateEngine()
    ctx = engine.init_session()

    # 跑到 S4
    for s in [State.S1, State.S2, State.S3, State.S4]:
        engine.transition(ctx, s)
    ctx.state_results[State.S2] = {"category": "抗抑菌剂"}
    ctx.state_results[State.S3] = {"status": "allowed"}
    ctx.state_results[State.S4] = {"risk_level": "R1"}

    # 用户改 main_ingredients → 回退到 S3
    r = engine.handle_field_change(ctx, ["main_ingredients"])
    test("FC-01 成分变→回退S3", r.rollback_target or ctx.current_state, State.S3)
    test("FC-02 S4被stale", State.S4 in ctx.stale_states, True)
    test("FC-03 S3被stale", State.S3 in ctx.stale_states, True)
    test("FC-04 S2未被stale", State.S2 not in ctx.stale_states, True)

    # S4 结果已清除
    test("FC-05 S4结果None", engine.get_state_result(ctx, State.S4), None)


# ═══════════════════════════════════════════════════════════════════
# 安全阀
# ═══════════════════════════════════════════════════════════════════

def test_safety_valves():
    print("\n── 安全阀 ──")

    engine = StateEngine()
    ctx = engine.init_session()

    # 同字段改 3 次 → 转人工
    for i in range(3):
        r = engine.handle_field_change(ctx, ["main_ingredients"])
    test("SV-01 3次修改转人工", ctx.transfer_to_human, True)
    test("SV-02 有转人工原因", len(ctx.transfer_reason) > 0, True)

    # 新会话，改 2 次不触发
    ctx2 = engine.init_session()
    engine.handle_field_change(ctx2, ["dosage_form"])
    r = engine.handle_field_change(ctx2, ["dosage_form"])
    test("SV-03 2次修改不触发", ctx2.transfer_to_human, False)
    test("SV-04 计数正确", ctx2.field_modification_counts["dosage_form"], 2)


# ═══════════════════════════════════════════════════════════════════
# 回退目标计算
# ═══════════════════════════════════════════════════════════════════

def test_rollback_target():
    print("\n── 回退目标计算 ──")

    test("RBT-01 成分→S3", get_rollback_target(["main_ingredients"]), State.S3)
    test("RBT-02 剂型→S2", get_rollback_target(["dosage_form"]), State.S2)
    test("RBT-03 产地→S2",
         get_rollback_target(["domestic_or_imported"]), State.S2)
    test("RBT-04 客户类型→S6",
         get_rollback_target(["customer_type"]), State.S6)
    test("RBT-05 产品名→S1",
         get_rollback_target(["product_name"]), State.S1)
    test("RBT-06 多字段→最上游",
         get_rollback_target(["main_ingredients", "dosage_form"]), State.S2)

    # stale 计算
    stale = get_stale_states(["main_ingredients"])
    test("RBT-07 成分stale含S3", State.S3 in stale, True)
    test("RBT-08 成分stale含S4", State.S4 in stale, True)
    test("RBT-09 成分stale含S5", State.S5 in stale, True)
    test("RBT-10 成分stale含S6", State.S6 in stale, True)
    test("RBT-11 成分stale不含S2", State.S2 not in stale, True)


# ═══════════════════════════════════════════════════════════════════
# set/get state results
# ═══════════════════════════════════════════════════════════════════

def test_state_results():
    print("\n── 状态结果存取 ──")

    engine = StateEngine()
    ctx = engine.init_session()

    engine.set_state_result(ctx, State.S2, {"category": "抗抑菌剂"})
    r = engine.get_state_result(ctx, State.S2)
    test("SR-01 正常获取", r["category"], "抗抑菌剂")

    # mark stale
    ctx.stale_states.add(State.S2)
    r = engine.get_state_result(ctx, State.S2)
    test("SR-02 stale返回None", r, None)

    # 重新 set 清除 stale
    engine.set_state_result(ctx, State.S2, {"category": "普通消毒剂"})
    test("SR-03 stale已清除", State.S2 not in ctx.stale_states, True)


# ═══════════════════════════════════════════════════════════════════
# advance 自动推进
# ═══════════════════════════════════════════════════════════════════

def test_auto_advance():
    print("\n── 自动推进 ──")

    engine = StateEngine()
    ctx = engine.init_session()

    # S0 advance → S1
    r = engine.advance(ctx)
    test("ADV-01 S0→S1", r.to_state, State.S1)

    # S1 advance → S2
    ctx.current_state = State.S1
    r = engine.advance(ctx)
    test("ADV-02 S1→S2", r.to_state, State.S2)

    # S7 advance → 终态
    ctx.current_state = State.S7
    r = engine.advance(ctx)
    test("ADV-03 S7 终态", r.allowed, True)
    test("ADV-03 不变", r.to_state, State.S7)


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — F6 状态机 测试套件")
    print("覆盖: 正向迁移 + 无效拒绝 + R3跳转 + 回退 + 安全阀")

    test_state_defs()
    test_forward_transitions()
    test_invalid_transitions()
    test_r3_shortcut()
    test_rollback()
    test_field_change_rollback()
    test_safety_valves()
    test_rollback_target()
    test_state_results()
    test_auto_advance()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
