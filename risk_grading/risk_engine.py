"""
F7 风险分级 — R1/R2/R3 三级风险判定引擎。

纯 Code Node 查表逻辑，不进 LLM。
综合成分合规状态、功效宣称、产地、退单历史、先上市标志等维度，
按固定规则输出风险等级和触发条件。

对应 PRD 4.4 和 PRD 3.4.1 assess_risk 伪代码。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# 风险等级定义
# ═══════════════════════════════════════════════════════════════════

class RiskLevel:
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


RISK_LABELS = {
    "R1": "R1 低风险",
    "R2": "R2 中风险",
    "R3": "R3 高风险",
}

RISK_ENGINE_ACTIONS = {
    "R1": {
        "can_quote": True,
        "can_generate_pdf": True,
        "disclaimer_required": False,
        "human_review_required": False,
        "description": "正常输出检测方案和报价预估",
    },
    "R2": {
        "can_quote": True,
        "can_generate_pdf": True,
        "disclaimer_required": True,
        "human_review_required": False,
        "description": "输出检测方案和报价，追加风险免责声明，建议人工复核",
    },
    "R3": {
        "can_quote": False,
        "can_generate_pdf": False,
        "disclaimer_required": True,
        "human_review_required": True,
        "description": "禁止报价，说明风险原因，强制建议转人工专家",
    },
}


# ═══════════════════════════════════════════════════════════════════
# 触发条件定义
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TriggerCondition:
    code: str                        # 条件编号
    level: str                       # 触发的风险等级
    label: str                       # 中文描述
    description: str                 # 详细说明


TRIGGER_CONDITIONS: dict[str, TriggerCondition] = {
    # ── R3 触发条件 ──
    "ingredient_prohibited": TriggerCondition(
        code="R3-01",
        level="R3",
        label="含禁用成分",
        description="成分在《消毒剂原料清单》禁用列表中",
    ),
    "medical_claim": TriggerCondition(
        code="R3-02",
        level="R3",
        label="功效含医疗暗示",
        description="宣称功效涉及疾病治疗、抗病毒等医疗用途表述",
    ),
    "historical_rejection": TriggerCondition(
        code="R3-03",
        level="R3",
        label="有退单历史",
        description="产品此前在消字号备案或检测中被退回或拒绝",
    ),
    "prior_market": TriggerCondition(
        code="R3-04",
        level="R3",
        label="先上市后补备案",
        description="产品已在市场流通，因举报/抽检/平台要求才来咨询",
    ),
    "regulation_circumvention": TriggerCondition(
        code="R3-05",
        level="R3",
        label="试图规避监管",
        description="用户要求规避备案流程或监管审查",
    ),
    # ── R2 触发条件 ──
    "ingredient_unknown": TriggerCondition(
        code="R2-01",
        level="R2",
        label="含未收录成分",
        description="成分不在允许清单也不在禁用清单，法规状态不明确",
    ),
    "imported_product": TriggerCondition(
        code="R2-02",
        level="R2",
        label="进口产品",
        description="进口产品走不同法规路径，需额外材料，风险自动提一级",
    ),
    "grey_area_ingredient": TriggerCondition(
        code="R2-03",
        level="R2",
        label="含灰色地带成分",
        description="含植物提取物、纳米材料、生物酶等法规不明确的成分",
    ),
    "vague_claims": TriggerCondition(
        code="R2-04",
        level="R2",
        label="功效描述模糊",
        description="宣称功效表述边界模糊，可能触及合规边界",
    ),
    "kb_table_expired": TriggerCondition(
        code="R2-05",
        level="R2",
        label="知识库表过期",
        description="判定依据的知识库映射表已超过复核周期",
    ),
    # ── R1 触发条件 ──
    "all_clear": TriggerCondition(
        code="R1-01",
        level="R1",
        label="常规合规产品",
        description="成分在允许清单中，功效合规，国产，无退单历史",
    ),
}


# ═══════════════════════════════════════════════════════════════════
# 风险判定主函数
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RiskAssessment:
    """风险判定结果"""
    risk_level: str                  # "R1" | "R2" | "R3"
    risk_label: str                  # 中文标签
    trigger_codes: list[str]         # 命中的触发条件编号
    trigger_labels: list[str]        # 命中的触发条件中文
    trigger_details: list[str]       # 命中的触发条件详细说明
    can_quote: bool                  # 是否可以进入报价
    disclaimer_required: bool        # 是否需要免责声明
    human_review_required: bool      # 是否需要转人工
    engine_action: str               # 引擎行为描述
    ingredient_results_summary: dict = field(default_factory=dict)
    # {allowed: n, prohibited: n, unknown: n}


def assess_risk(
    ingredient_results: Optional[list[dict]] = None,
    domestic_or_imported: str = "国产",
    historical_rejection: bool = False,
    medical_keyword_hit: bool = False,
    prior_market_flag: bool = False,
    regulation_circumvention: bool = False,
    kb_table_expired: bool = False,
    has_grey_area_ingredients: bool = False,
    vague_claims: bool = False,
) -> RiskAssessment:
    """
    综合多维度判定风险等级。

    R3 触发条件（满足任一 → R3，最高优先级）：
      - 含禁用成分
      - 医疗暗示关键词命中
      - 有退单历史
      - 先上市后补备案
      - 试图规避监管

    R2 触发条件（满足任一且无 R3 触发 → R2）：
      - 含未收录成分
      - 进口产品
      - 含灰色地带成分
      - 功效描述模糊
      - KB 映射表过期 + 有无命中成分

    其他 → R1

    返回 RiskAssessment，包含等级、触发条件列表、引擎行为。
    """
    trigger_codes: list[str] = []

    # ── 成分汇总 ──
    ingredient_summary = {"allowed": 0, "prohibited": 0, "unknown": 0}
    if ingredient_results:
        for ing in ingredient_results:
            status = ing.get("status", "unknown")
            if status in ingredient_summary:
                ingredient_summary[status] += 1

    has_prohibited = ingredient_summary["prohibited"] > 0
    has_unknown = ingredient_summary["unknown"] > 0
    is_imported = domestic_or_imported == "进口"

    # ── R3 判定（最先检查，一个命中就够）──
    if has_prohibited:
        trigger_codes.append("ingredient_prohibited")
    if medical_keyword_hit:
        trigger_codes.append("medical_claim")
    if historical_rejection:
        trigger_codes.append("historical_rejection")
    if prior_market_flag:
        trigger_codes.append("prior_market")
    if regulation_circumvention:
        trigger_codes.append("regulation_circumvention")

    if trigger_codes:
        # R3 直接返回，不继续检查
        return _build_result("R3", trigger_codes, ingredient_summary)

    # ── R2 判定 ──
    if has_unknown:
        trigger_codes.append("ingredient_unknown")
    if is_imported:
        trigger_codes.append("imported_product")
    if has_grey_area_ingredients:
        trigger_codes.append("grey_area_ingredient")
    if vague_claims:
        trigger_codes.append("vague_claims")
    if kb_table_expired and has_unknown:
        trigger_codes.append("kb_table_expired")

    if trigger_codes:
        return _build_result("R2", trigger_codes, ingredient_summary)

    # ── R1 ──
    trigger_codes.append("all_clear")
    return _build_result("R1", trigger_codes, ingredient_summary)


def _build_result(
    level: str,
    trigger_codes: list[str],
    ingredient_summary: dict,
) -> RiskAssessment:
    """构建 RiskAssessment 对象"""
    labels: list[str] = []
    details: list[str] = []
    for code in trigger_codes:
        tc = TRIGGER_CONDITIONS.get(code)
        if tc:
            labels.append(tc.label)
            details.append(tc.description)
        else:
            labels.append(code)
            details.append("")

    action = RISK_ENGINE_ACTIONS.get(level, RISK_ENGINE_ACTIONS["R1"])

    return RiskAssessment(
        risk_level=level,
        risk_label=RISK_LABELS.get(level, level),
        trigger_codes=trigger_codes,
        trigger_labels=labels,
        trigger_details=details,
        can_quote=action["can_quote"],
        disclaimer_required=action["disclaimer_required"],
        human_review_required=action["human_review_required"],
        engine_action=action["description"],
        ingredient_results_summary=ingredient_summary,
    )


# ═══════════════════════════════════════════════════════════════════
# 快捷查询
# ═══════════════════════════════════════════════════════════════════

def is_blocking(risk_level: str) -> bool:
    """R3 是否阻塞后续流程"""
    return risk_level == "R3"


def requires_disclaimer(risk_level: str) -> bool:
    """是否需要追加免责声明"""
    return risk_level in ("R2", "R3")


def can_enter_s6(risk_level: str) -> bool:
    """是否可以进入 S6 报价阶段"""
    return risk_level in ("R1", "R2")
