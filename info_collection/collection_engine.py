"""
F2 信息采集 — 多轮采集编排引擎。

职责：
1. 接收用户输入 + 当前会话状态
2. 调用 NLU 抽取实体（生产环境走小模型，测试环境用模拟）
3. 合并新抽取字段到会话变量
4. Gate 检查 → 不完整则生成追问（最多 2 个字段）
5. 完整则返回 ready 信号，驱动状态机迁移 S1→S2

设计原则：
- 每轮最多追问 2 个字段（避免信息过载）
- 按优先级追问（先问产品名/剂型，最后问角色/紧急程度）
- 剂型做值域校验，不合法时提示有效值
- 追问话术为固定模板，不进 LLM
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from typing import Optional

from anti_hallucination.gate_check import check_gate, REQUIRED_FIELDS as GATE_REQUIRED
from info_collection.field_definitions import (
    FIELD_DEFINITIONS,
    COLLECTION_ORDER,
    REQUIRED_FIELDS,
    OPTIONAL_FIELDS,
    FieldDef,
    validate_dosage_form,
)


@dataclass
class CollectionState:
    """当前采集状态"""
    filled: dict = field(default_factory=dict)        # {field: value}
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    ask_counts: dict = field(default_factory=dict)     # {field: 已追问次数}
    total_asks: int = 0                                 # 本轮追问次数
    ready: bool = False                                 # 6 必采字段全部填充
    conflicts: list[dict] = field(default_factory=list)
    validation_errors: dict = field(default_factory=dict)  # {field: error_msg}


@dataclass
class CollectionTurn:
    """单轮采集结果"""
    state: CollectionState
    next_message: str           # 发给用户的消息（确认 + 追问）
    ready_to_advance: bool      # 是否可以进入 S2
    session_vars: dict          # 更新后的会话变量


def init_collection(
    session_vars: Optional[dict] = None,
) -> CollectionState:
    """初始化采集状态"""
    filled = dict(session_vars) if session_vars else {}
    missing_required = [f for f in REQUIRED_FIELDS if not _has_value(filled.get(f))]
    missing_optional = [f for f in OPTIONAL_FIELDS if not _has_value(filled.get(f))]
    return CollectionState(
        filled=filled,
        missing_required=missing_required,
        missing_optional=missing_optional,
        ask_counts={f: 0 for f in REQUIRED_FIELDS + OPTIONAL_FIELDS},
        ready=len(missing_required) == 0,
    )


def process_turn(
    user_input: str,
    state: CollectionState,
    newly_extracted: Optional[dict] = None,
) -> CollectionTurn:
    """
    处理一轮信息采集。

    Args:
        user_input: 用户本轮输入
        state: 当前采集状态
        newly_extracted: NLU 抽取的结构化字段（生产环境由小模型产出）

    Returns:
        CollectionTurn: 包含更新后状态和应发给用户的消息
    """
    extracted = newly_extracted or {}

    # ── 1. 合并新字段 ──
    for field, value in extracted.items():
        if value is not None and (not isinstance(value, str) or value.strip()):
            if isinstance(value, list):
                value = ", ".join(value)
            state.filled[field] = value

    # ── 2. 值域校验 ──
    _validate_filled_fields(state)

    # ── 3. 更新缺失列表 ──
    state.missing_required = [f for f in REQUIRED_FIELDS
                              if not _has_value(state.filled.get(f))]
    state.missing_optional = [f for f in OPTIONAL_FIELDS
                              if not _has_value(state.filled.get(f))]

    # ── 4. 冲突检测 ──
    # Gate check 会处理冲突

    # ── 5. 生成下一轮消息 ──
    if state.missing_required:
        # 选最多 2 个最高优先级的缺失字段追问
        targets = _pick_follow_up_targets(state.missing_required, state.ask_counts, max_ask=2)
        for t in targets:
            state.ask_counts[t] = state.ask_counts.get(t, 0) + 1
        state.total_asks = len(targets)

        # 构建消息：先确认已有的 → 再追问缺失的
        confirmed = _build_confirmed_summary(state.filled)
        follow_up = _build_follow_up_questions(targets, state.ask_counts)

        if confirmed:
            next_msg = f"【已确认】\n{confirmed}\n\n{follow_up}"
        else:
            greeting = "您好！我是消字号合规预审助手。在为您分析之前，需要先了解产品的基本信息。"
            next_msg = f"{greeting}\n\n{follow_up}"

        return CollectionTurn(
            state=state,
            next_message=next_msg,
            ready_to_advance=False,
            session_vars=state.filled,
        )

    # ── 6. 必采字段齐全 → ready ──
    state.ready = True
    confirmed = _build_confirmed_summary(state.filled)
    next_msg = (
        f"【信息采集完成】\n{confirmed}\n\n"
        f"信息已齐全，接下来为您进行品类判定。"
    )

    return CollectionTurn(
        state=state,
        next_message=next_msg,
        ready_to_advance=True,
        session_vars=state.filled,
    )


def _has_value(val) -> bool:
    """判断字段是否有有效值"""
    if val is None:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    if isinstance(val, list) and len(val) == 0:
        return False
    return True


def _validate_filled_fields(state: CollectionState):
    """对已填充的字段做值域校验"""
    state.validation_errors = {}

    # 剂型校验
    dosage = state.filled.get("dosage_form")
    if _has_value(dosage):
        valid, err = validate_dosage_form(str(dosage))
        if not valid:
            state.validation_errors["dosage_form"] = err

    # 产地校验
    origin = state.filled.get("domestic_or_imported")
    if _has_value(origin) and str(origin).strip() not in ("国产", "进口"):
        state.validation_errors["domestic_or_imported"] = (
            f"产地只能为「国产」或「进口」，当前输入为「{origin}」"
        )


def _pick_follow_up_targets(
    missing: list[str],
    ask_counts: dict[str, int],
    max_ask: int = 2,
) -> list[str]:
    """从缺失字段中选最多 max_ask 个追问目标，按优先级排序"""
    sorted_missing = sorted(missing, key=lambda f: FIELD_DEFINITIONS[f].priority)
    return sorted_missing[:max_ask]


def _build_confirmed_summary(filled: dict) -> str:
    """构建已确认信息的摘要文本"""
    lines: list[str] = []
    for field in COLLECTION_ORDER:
        val = filled.get(field)
        if _has_value(val):
            label = FIELD_DEFINITIONS[field].label
            lines.append(f"  · {label}：{val}")
    return "\n".join(lines) if lines else ""


def _build_follow_up_questions(
    targets: list[str],
    ask_counts: dict[str, int],
) -> str:
    """为追问目标构建追问话术"""
    if not targets:
        return ""

    if len(targets) == 1:
        field = targets[0]
        fdef = FIELD_DEFINITIONS[field]
        count = ask_counts.get(field, 1)
        if count <= 1:
            return fdef.prompt
        else:
            # 已问过一轮，用简短版本 + 补充引导
            hint_text = f"（{fdef.hint}，如：{' / '.join(fdef.examples[:3])}）"
            return f"{fdef.prompt_short} {hint_text}"

    # 2 个字段
    lines = ["还需要确认以下信息："]
    for field in targets:
        fdef = FIELD_DEFINITIONS[field]
        count = ask_counts.get(field, 1)
        if count <= 1:
            lines.append(f"\n{fdef.prompt}")
        else:
            hint_text = f"（{fdef.hint}，如：{' / '.join(fdef.examples[:2])}）"
            lines.append(f"\n关于{fdef.label}：{fdef.prompt_short} {hint_text}")

    return "\n".join(lines)
