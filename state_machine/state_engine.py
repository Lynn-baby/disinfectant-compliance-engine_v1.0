"""
F6 状态机 — 状态引擎。

管理 8 状态线性流转 + 回退 + 级联 stale + 安全阀。
这是全引擎的编排核心，把所有模块串起来。

请求处理流程：
  1. 安全扫描 (F3 safety_keywords)
  2. 拒答决策 (F4 refusal_engine)
  3. NLU 抽取 (F3 nlu_prompt_template — 生产环境走小模型)
  4. Gate 检查 (F3 gate_check)
  5. 状态机迁移决策
  6. 执行当前状态逻辑
  7. 输出校验 (F3 output_verifier + F5 template_validator)

安全阀（PRD 4.2.1 C 节）：
  - 同字段修改 ≥ 3 次 → 转人工
  - 回退导致 R1/R2 → R3 → 转人工
  - 成分从允许变禁用 → 中断
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from typing import Optional, Callable

from state_machine.state_definitions import (
    State,
    StateSpec,
    STATE_TABLE,
    get_rollback_target,
    get_stale_states,
    FIELD_STATE_DEPENDENCY,
)


# ── 安全阀常量 ──
MAX_FIELD_MODIFICATIONS = 3


@dataclass
class SessionContext:
    """会话上下文——状态机操作的全部数据"""
    current_state: State = State.S0
    session_vars: dict = field(default_factory=dict)
    state_results: dict = field(default_factory=dict)  # {State: 该状态产出结果}
    stale_states: set[State] = field(default_factory=set)
    field_modification_counts: dict = field(default_factory=dict)  # {field: 修改次数}
    transfer_to_human: bool = False
    transfer_reason: str = ""
    safety_blocked: bool = False
    safety_reason: str = ""


@dataclass
class TransitionResult:
    """状态迁移结果"""
    allowed: bool
    from_state: State
    to_state: State
    reason: str = ""                # 拒绝原因（allowed=False时）
    rollback_triggered: bool = False
    stale_states: set[State] = field(default_factory=set)
    rollback_target: Optional[State] = None
    safety_triggered: bool = False
    safety_message: str = ""


class StateEngine:
    """
    状态机引擎。

    使用方法：
        engine = StateEngine()
        ctx = engine.init_session()

        # 每轮对话
        result = engine.transition(ctx, target_state)
        if result.allowed:
            # 执行目标状态的逻辑
            pass
    """

    def init_session(self, initial_vars: Optional[dict] = None) -> SessionContext:
        """创建新会话，初始状态 S0"""
        return SessionContext(
            current_state=State.S0,
            session_vars=initial_vars or {},
        )

    def can_transition_to(self, ctx: SessionContext, target: State) -> TransitionResult:
        """
        检查是否可以从当前状态迁移到目标状态。

        不执行迁移，仅做合法性检查。
        """
        current_spec = STATE_TABLE.get(ctx.current_state)
        if not current_spec:
            return TransitionResult(
                allowed=False,
                from_state=ctx.current_state,
                to_state=target,
                reason=f"无效的当前状态: {ctx.current_state}",
            )

        # 正向迁移：target 必须在 forward 列表中
        if target in current_spec.forward:
            return TransitionResult(
                allowed=True,
                from_state=ctx.current_state,
                to_state=target,
            )

        # 回退迁移：target 必须在 backward 列表中
        if target in current_spec.backward:
            return TransitionResult(
                allowed=True,
                from_state=ctx.current_state,
                to_state=target,
            )

        # S4→S7: R3 跳转，合法
        if ctx.current_state == State.S4 and target == State.S7:
            return TransitionResult(
                allowed=True,
                from_state=ctx.current_state,
                to_state=target,
            )

        return TransitionResult(
            allowed=False,
            from_state=ctx.current_state,
            to_state=target,
            reason=f"不允许从 {ctx.current_state} 迁移到 {target}",
        )

    def transition(
        self,
        ctx: SessionContext,
        target: State,
    ) -> TransitionResult:
        """
        执行状态迁移。

        检查合法性后更新 ctx.current_state。
        如果是回退，级联标记 stale states。
        """
        result = self.can_transition_to(ctx, target)
        if not result.allowed:
            return result

        # ── 回退检测：target 在 backward 列表中 → 是回退 ──
        current_spec = STATE_TABLE.get(ctx.current_state)
        is_rollback = (
            current_spec is not None
            and target in current_spec.backward
        )

        if is_rollback:
            result.rollback_triggered = True
            # 计算哪些下游状态需要 stale
            # 取从 target 到 current_state 之间的所有状态
            stale = self._compute_downstream_states(target, ctx.current_state)
            result.stale_states = stale
            ctx.stale_states.update(stale)

        # ── 更新状态 ──
        old_state = ctx.current_state
        ctx.current_state = target

        # ── 清除新目标状态之后的状态结果（如果有）──
        target_num = int(target.value[1])
        for state_key in list(ctx.state_results.keys()):
            if isinstance(state_key, State):
                state_num = int(state_key.value[1])
                if state_num > target_num:
                    del ctx.state_results[state_key]

        return result

    def advance(
        self,
        ctx: SessionContext,
    ) -> TransitionResult:
        """
        自动推进到下一个状态。

        根据当前状态和风险等级选择正确的下一状态。
        S4 时根据 risk_level 决定去 S5 还是 S7。
        """
        current = ctx.current_state

        # S4 → 根据风险等级分流
        if current == State.S4:
            risk_level = ctx.state_results.get(State.S4, {}).get("risk_level", "R1")
            if risk_level == "R3":
                return self.transition(ctx, State.S7)  # R3 → 跳至摘要后转人工
            return self.transition(ctx, State.S5)

        # S7 → 结束
        if current == State.S7:
            return TransitionResult(
                allowed=True,
                from_state=State.S7,
                to_state=State.S7,
                reason="已到达终态",
            )

        # 常规：取 forward 列表第一个
        spec = STATE_TABLE.get(current)
        if spec and spec.forward:
            return self.transition(ctx, spec.forward[0])

        return TransitionResult(
            allowed=False,
            from_state=current,
            to_state=current,
            reason="无可用下一状态",
        )

    def handle_field_change(
        self,
        ctx: SessionContext,
        changed_fields: list[str],
    ) -> TransitionResult:
        """
        处理变量变更导致的回退。

        执行 PRD 4.2.1 的完整回退流程：
        1. 更新修改计数
        2. 检查安全阀（≥3次 → 转人工）
        3. 计算回退目标
        4. 级联标 stale
        5. 执行回退迁移
        """
        # ── 更新修改计数 ──
        for field in changed_fields:
            ctx.field_modification_counts[field] = (
                ctx.field_modification_counts.get(field, 0) + 1
            )

        # ── 安全阀 1: 同字段修改 ≥ 3 次 ──
        for field in changed_fields:
            if ctx.field_modification_counts.get(field, 0) >= MAX_FIELD_MODIFICATIONS:
                ctx.transfer_to_human = True
                ctx.transfer_reason = (
                    f"字段「{field}」被修改 {ctx.field_modification_counts[field]} 次，"
                    f"超出自动处理范围"
                )
                return TransitionResult(
                    allowed=False,
                    from_state=ctx.current_state,
                    to_state=ctx.current_state,
                    reason=ctx.transfer_reason,
                )

        # ── 计算回退目标 ──
        rollback_target = get_rollback_target(changed_fields)
        stale = get_stale_states(changed_fields)

        # ── 执行回退 ──
        result = self.transition(ctx, rollback_target)
        result.rollback_triggered = True
        result.stale_states = stale
        result.rollback_target = rollback_target

        # ── 清除 stale 状态的结果 ──
        for s in stale:
            ctx.state_results.pop(s, None)

        ctx.stale_states.update(stale)

        return result

    def set_state_result(
        self,
        ctx: SessionContext,
        state: State,
        result_data: dict,
    ):
        """保存某个状态的产出结果"""
        ctx.state_results[state] = result_data
        # 如果有 stale 标记，清除它（重新产出了结果）
        ctx.stale_states.discard(state)

    def get_state_result(
        self,
        ctx: SessionContext,
        state: State,
    ) -> Optional[dict]:
        """获取某个状态的产出结果（stale 状态返回 None）"""
        if state in ctx.stale_states:
            return None
        return ctx.state_results.get(state)

    def _compute_downstream_states(
        self,
        from_state: State,
        to_state: State,
    ) -> set[State]:
        """计算 from_state 到 to_state 之间的所有下游状态"""
        from_num = int(from_state.value[1])
        to_num = int(to_state.value[1])
        if from_num >= to_num:
            return set()
        return {
            State(f"S{i}")
            for i in range(from_num + 1, to_num + 1)
            if f"S{i}" in State.__members__
        }
