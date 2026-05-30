"""
Layer 3 校验层 — 输出侧后置拦截（Code Node，不进 LLM）。

前两层都失效时，最后一层在输出侧拦截。
- 结构匹配：输出是否包含固定模板的所有标题？
- 引用检查：合规结论是否附带知识库引用标志？
- 安全词二次扫描：输出文本是否出现幻觉信号？

对应 PRD 3.4.3。
"""

from dataclasses import dataclass, field
from typing import Optional


# ── 幻觉信号关键词 ───────────────────────────────────────────────
# 模型输出中出现以下模式时，说明可能在编造

HALLUCINATION_SIGNALS: list[str] = [
    # 确定性语言 + 无引用支撑
    "绝对没问题",
    "肯定能过",
    "保证通过",
    "百分之百",
    "完全合规",
    "包过",
    # 编造法规
    "根据相关规定",
    "依据国家法律法规",
    "根据行业惯例",
    "一般来讲",
    "通常来说",
    # 超出消字号范围
    "药品注册",
    "医疗器械注册",
    "保健品备案",
    "化妆品备案",
]

# ── 各状态的输出模板标题要求 ─────────────────────────────────────

STATE_REQUIRED_STRUCTURE: dict[str, list[str]] = {
    "S1": [],  # S1 是追问，无固定模板
    "S2": ["品类判定", "判定依据"],
    "S3": ["成分合规状态"],
    "S4": ["风险等级", "触发条件"],
    "S5": ["检测项目", "参考标准"],
    "S6": ["费用预估", "参考周期"],
    "S7": ["预审摘要", "注意事项"],
}

# ── 引用标志模式 ─────────────────────────────────────────────────
# 合规结论中应包含以下至少一种引用标志

CITATION_PATTERNS: list[str] = [
    "《", "》",           # 法规名称引用，如《消毒技术规范》
    "GB ", "GB/T ",       # 国家标准
    "WS ",                # 卫生行业标准
    "卫健委",             # 卫健委通知引用
    "第.*条",             # 法规条款
]


@dataclass
class VerificationResult:
    """校验结果"""
    passed: bool
    structure_ok: bool = True
    citation_ok: bool = True
    safety_ok: bool = True
    issues: list[str] = field(default_factory=list)
    corrected_output: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


def verify_output(
    raw_output: str,
    current_state: str,
    contains_compliance_judgment: bool = False,
) -> VerificationResult:
    """
    对主模型输出做三层校验。

    Args:
        raw_output: 主模型生成的原始输出文本
        current_state: 当前状态（S0-S7），用于判断结构要求
        contains_compliance_judgment: 输出是否包含合规判定内容

    Returns:
        VerificationResult: passed=True 表示校验通过，可直接输出
    """
    import re

    issues: list[str] = []
    warnings: list[str] = []
    corrected = raw_output

    # ── 1. 结构匹配 ──
    required_sections = STATE_REQUIRED_STRUCTURE.get(current_state, [])
    for section in required_sections:
        if section not in raw_output:
            issues.append(f"缺失模板标题: 「{section}」")
            corrected = _append_structure_warning(corrected, section)

    structure_ok = len([i for i in issues if "缺失模板标题" in i]) == 0

    # ── 2. 引用检查 ──
    citation_ok = True  # 非合规内容默认不需要引用
    if contains_compliance_judgment:
        has_citation = any(
            re.search(p, raw_output) for p in CITATION_PATTERNS
        )
        if not has_citation:
            issues.append("合规结论未附带知识库引用")
            citation_ok = False
            corrected = _append_citation_warning(corrected)

    # ── 3. 安全词二次扫描 ──
    for signal in HALLUCINATION_SIGNALS:
        if signal in raw_output:
            warnings.append(f"检测到幻觉信号: 「{signal}」")

    safety_ok = len(warnings) == 0

    # ── 4. 最终判定 ──
    # 结构缺失是硬伤，引用缺失是降级，幻觉信号是降级
    critical_issues = [i for i in issues if "缺失模板标题" in i]

    if critical_issues:
        return VerificationResult(
            passed=False,
            structure_ok=False,
            citation_ok=citation_ok,
            safety_ok=safety_ok,
            issues=issues,
            warnings=warnings,
            corrected_output=corrected,
        )

    return VerificationResult(
        passed=True,
        structure_ok=structure_ok,
        citation_ok=citation_ok,
        safety_ok=safety_ok,
        issues=issues,
        warnings=warnings,
        corrected_output=corrected if (issues or warnings) else None,
    )


def _append_citation_warning(text: str) -> str:
    """追加引用缺失标注"""
    return (
        text
        + "\n\n---\n"
        + "⚠️ 本结论由模型生成，未经知识库充分验证。如需确认，请联系技术专家复核。"
    )


def _append_structure_warning(text: str, missing_section: str) -> str:
    """追加结构缺失标注"""
    return (
        text
        + f"\n\n---\n"
        + f"⚠️ 输出内容缺少「{missing_section}」部分，预审报告可能不完整。"
    )


# ── 降级模板（校验严重失败时使用）────────────────────────────────

FALLBACK_TEMPLATE = """很抱歉，当前无法生成完整的预审报告。

已采集的信息已妥善保存。建议您：
1. 稍后重试，或
2. 联系技术专家进行人工预审

对您造成的不便深表歉意。"""


def fallback_on_critical_failure(
    session_vars: dict,
    failure_reason: str,
) -> str:
    """
    校验严重失败时的降级输出。
    不透露内部错误细节，引导用户转人工。
    """
    # 至少告诉用户已采集了什么
    from anti_hallucination.gate_check import FIELD_LABELS

    filled = {FIELD_LABELS.get(k, k): v for k, v in session_vars.items() if v}
    if filled:
        saved_info = "\n".join(f"  · {k}: {v}" for k, v in filled.items())
        return (
            f"很抱歉，当前无法生成完整的预审报告。\n\n"
            f"已为您保存以下信息：\n{saved_info}\n\n"
            f"建议联系技术专家继续处理。"
        )
    return FALLBACK_TEMPLATE
