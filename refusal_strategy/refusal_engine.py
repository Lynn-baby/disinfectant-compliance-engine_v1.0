"""
F4 拒答策略 — 统一决策引擎。

整合：
- F3 安全关键词扫描
- 医疗暗示关键词检测
- 7 大业务边界场景检测
- Gate 变量完整性检查

优先级（从高到低）：
  BLOCK > INTERRUPT > FAST_TRACK > PROMPT > WARN > FLAG > PASS
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from anti_hallucination.safety_keywords import scan_safety_keywords
from anti_hallucination.gate_check import check_gate, REQUIRED_FIELDS
from refusal_strategy.medical_keywords import detect_medical_keywords
from refusal_strategy.edge_case_detector import (
    detect_all_edge_cases,
    EdgeCase,
    EdgeAction,
    EdgeCaseResult,
)
from refusal_strategy.refusal_templates import (
    REFUSAL_SAFETY_HARD_BLOCK,
    MEDICAL_INTERRUPT_L1,
    MEDICAL_WARNING_L2,
    EDGE_CASE_TEMPLATES,
    GATE_INCOMPLETE_TEMPLATES,
)


class Decision(str, Enum):
    """最终决策"""
    BLOCK = "block"              # 硬拒绝，终止流程
    INTERRUPT = "interrupt"      # 中断，等待用户确认
    FAST_TRACK = "fast_track"    # 加速到目标状态
    PROMPT = "prompt"            # 追问，等待用户回复
    WARN = "warn"                # 继续但追加警告
    PASS = "pass"                # 放行，无异常


# 决策优先级：数值越小优先级越高
DECISION_PRIORITY = {
    Decision.BLOCK: 0,
    Decision.INTERRUPT: 1,
    Decision.FAST_TRACK: 2,
    Decision.PROMPT: 3,
    Decision.WARN: 4,
    Decision.PASS: 5,
}


@dataclass
class RefusalDecision:
    """统一拒答决策"""
    decision: Decision
    message: str = ""
    block_reason: str = ""       # BLOCK 时的原因分类
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # FAST_TRACK 时指定目标状态
    fast_track_target: str = ""

    def should_proceed(self) -> bool:
        """是否可以继续后续流程"""
        return self.decision not in (Decision.BLOCK, Decision.INTERRUPT)


def evaluate(
    user_input: str,
    session_vars: Optional[dict] = None,
    newly_extracted: Optional[dict] = None,
    kb_hit_statuses: Optional[list[str]] = None,
    rejection_ask_count: int = 0,
    vague_ask_count: int = 0,
    current_state: str = "S1",
) -> RefusalDecision:
    """
    统一拒答决策入口。

    按优先级依次检查各层，返回优先级最高的决策。

    Args:
        user_input: 用户原始输入
        session_vars: 当前会话累积变量
        newly_extracted: 本轮 NLU 新提取的字段
        kb_hit_statuses: KB 检索命中状态列表
        rejection_ask_count: 退单历史的追问次数
        vague_ask_count: 模糊成分的追问次数
        current_state: 当前状态机状态

    Returns:
        RefusalDecision: 最终决策
    """
    if session_vars is None:
        session_vars = {}

    # 收集所有子决策
    sub_decisions: list[tuple[int, Decision, str, dict]] = []

    # ── 第 0 层：安全关键词扫描（最高优先级）──
    safety_result = scan_safety_keywords(user_input)
    if safety_result.blocked:
        return RefusalDecision(
            decision=Decision.BLOCK,
            message=REFUSAL_SAFETY_HARD_BLOCK.get(
                safety_result.block_reason,
                "抱歉，无法处理这个请求。",
            ),
            block_reason=safety_result.block_reason or "",
            metadata={"matched_keyword": safety_result.matched_keyword},
        )

    # ── 第 1 层：医疗暗示检测 ──
    medical = detect_medical_keywords(user_input)
    if medical.detected and medical.should_interrupt:
        keywords_str = "、".join(medical.matched_keywords[:3])
        return RefusalDecision(
            decision=Decision.INTERRUPT,
            message=MEDICAL_INTERRUPT_L1.replace("{keywords}", keywords_str),
            block_reason="medical_claim_l1",
            metadata={"medical_keywords": medical.matched_keywords, "level": "L1"},
        )
    if medical.detected:
        keywords_str = "、".join(medical.matched_keywords[:3])
        sub_decisions.append((
            DECISION_PRIORITY[Decision.WARN],
            Decision.WARN,
            MEDICAL_WARNING_L2.replace("{keywords}", keywords_str),
            {"medical_keywords": medical.matched_keywords, "level": "L2"},
        ))

    # ── 第 2 层：业务边界场景 ──
    ingredients = session_vars.get("main_ingredients", [])
    if isinstance(ingredients, str):
        ingredients = [ingredients]

    edge_results = detect_all_edge_cases(
        user_input=user_input,
        ingredients=ingredients,
        kb_hit_statuses=kb_hit_statuses,
        domestic_or_imported=session_vars.get("domestic_or_imported"),
        historical_rejection=session_vars.get("historical_rejection"),
        rejection_ask_count=rejection_ask_count,
        vague_ask_count=vague_ask_count,
        dosage_form=session_vars.get("dosage_form"),
    )

    for edge_r in edge_results:
        action = edge_r.action
        template_map = EDGE_CASE_TEMPLATES.get(edge_r.case, {})

        # 根据场景选择具体话术
        if edge_r.case == EdgeCase.REJECTION_HISTORY:
            if rejection_ask_count == 0:
                msg = template_map.get("prompt_first", edge_r.message)
            elif rejection_ask_count == 1:
                msg = template_map.get("prompt_second", edge_r.message)
            else:
                msg = template_map.get("flag_declined", edge_r.message)
        elif edge_r.case == EdgeCase.VAGUE_INGREDIENT:
            if vague_ask_count == 0:
                tpl = template_map.get("prompt_first", edge_r.message)
                vague_str = "、".join(edge_r.metadata.get("vague_terms", []))
                msg = tpl.replace("{vague_terms}", vague_str)
            elif vague_ask_count == 1:
                tpl = template_map.get("prompt_second", edge_r.message)
                vague_str = "、".join(edge_r.metadata.get("vague_terms", []))
                msg = tpl.replace("{vague_terms}", vague_str)
            else:
                msg = template_map.get("block", edge_r.message)

            if vague_ask_count >= 2:
                # 超过两次追问 → 升级为 BLOCK
                return RefusalDecision(
                    decision=Decision.BLOCK,
                    message=msg,
                    block_reason="vague_ingredient_exceeded",
                    metadata=edge_r.metadata,
                )
        else:
            msg = template_map.get(action.value, edge_r.message)

        # 优先市场 → FAST_TRACK
        if edge_r.case == EdgeCase.PRIOR_MARKET:
            return RefusalDecision(
                decision=Decision.FAST_TRACK,
                message=msg,
                fast_track_target="S4",
                metadata=edge_r.metadata,
            )

        # 套装 → INTERRUPT
        if edge_r.case == EdgeCase.BUNDLE_PRODUCT:
            return RefusalDecision(
                decision=Decision.INTERRUPT,
                message=msg,
                metadata=edge_r.metadata,
            )

        decision_map = {
            EdgeAction.BLOCK: Decision.BLOCK,
            EdgeAction.INTERRUPT: Decision.INTERRUPT,
            EdgeAction.PROMPT: Decision.PROMPT,
            EdgeAction.WARN: Decision.WARN,
            EdgeAction.FLAG: Decision.PASS,
        }
        d = decision_map.get(action, Decision.PASS)

        sub_decisions.append((
            DECISION_PRIORITY[d],
            d,
            msg,
            edge_r.metadata,
        ))

    # ── 第 3 层：Gate 完整性检查 ──
    if current_state == "S1":
        gate_result = check_gate(session_vars, newly_extracted)
        if not gate_result.passed:
            if gate_result.conflict_fields:
                return RefusalDecision(
                    decision=Decision.INTERRUPT,
                    message=gate_result.follow_up_message,
                    metadata={"conflict_fields": gate_result.conflict_fields},
                )
            if gate_result.missing_fields:
                return RefusalDecision(
                    decision=Decision.PROMPT,
                    message=gate_result.follow_up_message,
                    metadata={"missing_fields": gate_result.missing_fields},
                )

    # ── 合并子决策，返回最高优先级 ──
    if sub_decisions:
        sub_decisions.sort(key=lambda x: x[0])
        priority, decision, msg, meta = sub_decisions[0]
        return RefusalDecision(
            decision=decision,
            message=msg,
            warnings=[msg] if decision == Decision.WARN else [],
            metadata=meta,
        )

    return RefusalDecision(decision=Decision.PASS)
