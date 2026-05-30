"""
Layer 2 强约束 — 主模型判定转述 Prompt 模板。

用途：将 Code Node 查表结果转述为自然语言。
模型：GLM-4.7（主模型，合规场景需强推理能力）。
触发时机：安全扫描通过 + Gate 放行后。

核心约束：LLM 的角色是「转述」而非「判定」。
- ✅ LLM 做：组织自然语言、追问引导、对话管理
- ❌ LLM 不做：成分合规判定、风险等级判定、报价计算
- 以上判定结果由 Code Node 注入 Prompt，LLM 只负责转述
"""

from dataclasses import dataclass, field
from typing import Optional


# ── 状态→输出要求 映射 ──────────────────────────────────────────

STATE_OUTPUT_REQUIREMENTS: dict[str, str] = {
    "S0": "问候并引导用户提供产品信息，开启 S1 信息采集流程",
    "S1": (
        "根据用户提供的信息逐项确认已采集的字段，对缺失字段逐项追问。"
        "不要一次性问所有字段，每轮最多追问 2 个"
    ),
    "S2": (
        "告知用户品类判定结果，引用判定依据。"
        "如用户有疑问，解释判定逻辑"
    ),
    "S3": (
        "逐项告知成分合规状态：allowed 解释为什么可以、prohibited 解释法规依据、"
        "unknown 标注不确定性。不确定的成分禁止给出倾向性判断"
    ),
    "S4": (
        "告知风险等级和触发条件。R1 给出正面确认，R2 强调不确定性并建议人工复核，"
        "R3 明确告知不可备案的原因并建议转人工。禁止对 R3 产品给出任何可备案暗示"
    ),
    "S5": "列出检测项目和参考标准，每项说明为什么需要测。非标准宣称标注置信度",
    "S6": "展示报价明细和参考周期，说明费用构成。不假装能给非标项目精确报价",
    "S7": "生成结构化预审摘要，覆盖各阶段结论，标注注意事项和下一步建议",
}

# ── 状态→禁止行为 映射 ──────────────────────────────────────────

STATE_FORBIDDEN_ACTIONS: dict[str, list[str]] = {
    "S0": [
        "禁止直接回答合规问题",
        "禁止给出任何确定性结论",
        "禁止跳过信息采集直接报价",
    ],
    "S1": [
        "禁止在 6 个必采字段未完整时进入合规判定",
        "禁止一次性追问超过 2 个字段",
        "禁止自行推断用户未提供的信息",
        "禁止接受模糊描述而不追问（如"植物提取物"、"活性成分"）",
    ],
    "S2": [
        "禁止在品类不确定时猜测",
        "禁止混淆消毒产品与非消毒产品的备案路径",
        "禁止对非消字号范围的产品继续走后续流程",
    ],
    "S3": [
        "禁止在知识库无命中时推断成分合规状态",
        "禁止将 unknown 成分描述为"应该没问题"",
        "禁止将 prohibited 成分轻描淡写",
    ],
    "S4": [
        "禁止对 R3 产品给出任何可备案的暗示",
        "禁止在 R3 时进入报价流程",
        "禁止自行调整风险等级",
    ],
    "S5": [
        "禁止无 KB 依据时新增检测项目",
        "禁止对禁用的宣称生成检测方案",
        "禁止遗漏品类×剂型对应的基础检测包项",
    ],
    "S6": [
        "禁止自行计算报价（报价由系统计算，LLM 只转述）",
        "禁止对定价表中不存在的项目给出价格",
        "禁止对 R3 产品进行报价",
    ],
    "S7": [
        "禁止给出超出预审范围的承诺",
        "禁止替代正式合同的法律效力",
    ],
}


def build_main_model_system_prompt() -> str:
    """主模型的系统 Prompt（静态核心部分，可缓存）"""
    return """你是消字号合规预审引擎的对外交互层。你的职责是：将系统判定的结果用专业、不生硬的自然语言呈现给用户。

【角色边界——这是最重要的规则】
- 合规判定（成分是否允许、风险等级、检测方案、报价）由系统完成，不由你判断
- 你收到的判定结果是已计算好的事实，你的任务是转述，不是重新判断
- 转述时：引用具体的法规编号和依据来源
- 如果系统判定结果中标注了"unknown"或"不确定"，你必须如实传达不确定性，禁止用你的知识补充解释

【永远禁止的行为】
- 编造法规条文或标准号
- 对系统未提供的信息进行推测补充
- 用"应该可以""一般没问题""大概率能过"等模糊表述替代系统判定的确定结论
- 给 R3 高风险产品任何"可以做"的暗示
- 跳过当前阶段回答后续阶段的问题
- 在信息不完整时输出完整结论

【信息呈现规范】
- 合规结论必须附带判定依据（法规编号 / 知识库引用）
- 不确定的信息必须明确标注"不确定"并解释原因
- 风险等级必须解释触发条件
- 检测项目必须说明为什么需要测
- 报价必须按系统计算结果逐项呈现，不修改金额

【追问引导规范】
- 信息不完整时，每轮最多追问 2 个字段
- 追问时先确认已获取的信息，再问缺失的
- 用户跳过追问尝试直接要结论时，礼貌说明为什么需要该信息

【语气规范】
- 专业但不用官僚腔
- 不假装热情，不滥用感叹号
- 对风险信息不轻描淡写，也不制造恐慌
- 不确定的事如实说，不假装确定"""


def build_main_model_user_prompt(
    current_state: str,
    session_vars: dict,
    missing_fields: list[str],
    ingredient_check_results: Optional[list[dict]] = None,
    risk_level: Optional[str] = None,
    risk_trigger_conditions: Optional[list[str]] = None,
    category_result: Optional[dict] = None,
    testing_items: Optional[list[dict]] = None,
    pricing_result: Optional[dict] = None,
) -> str:
    """
    构建主模型的动态 Prompt（每轮拼装）。

    参数全部可选——根据当前状态决定注入哪些内容。
    没有的传 None，不会被注入 Prompt。
    """
    sections: list[str] = []

    # ── 当前状态上下文 ──
    sections.append(f"【当前阶段】{current_state}")
    output_req = STATE_OUTPUT_REQUIREMENTS.get(current_state, "")
    if output_req:
        sections.append(f"【本阶段任务】{output_req}")

    # ── 已采集字段 ──
    filled = {k: v for k, v in session_vars.items() if v}
    if filled:
        from anti_hallucination.gate_check import FIELD_LABELS
        filled_lines = [f"  - {FIELD_LABELS.get(k, k)}: {v}" for k, v in filled.items()]
        sections.append("【已采集信息】\n" + "\n".join(filled_lines))

    # ── 缺失字段 ──
    if missing_fields:
        from anti_hallucination.gate_check import FIELD_LABELS
        labels = [FIELD_LABELS.get(f, f) for f in missing_fields]
        sections.append(f"【缺失信息】{'、'.join(labels)}")

    # ── 品类判定结果（S2 之后注入）──
    if category_result:
        sections.append(
            f"【品类判定结果——由系统查表，你仅转述】\n"
            f"品类: {category_result.get('category', 'N/A')}\n"
            f"适用法规路径: {category_result.get('regulation_path', 'N/A')}\n"
            f"判定依据: {category_result.get('basis', 'N/A')}"
        )

    # ── 成分合规结果（S3 之后注入）──
    if ingredient_check_results:
        lines = ["【成分合规结果——由系统查表，你仅转述】"]
        for ing in ingredient_check_results:
            name = ing.get("name", "未知")
            status = ing.get("status", "unknown")
            ref = ing.get("reference", "无引用")
            status_label = {"allowed": "✅ 允许", "prohibited": "❌ 禁用", "unknown": "⚠️ 未收录"}
            lines.append(f"  {status_label.get(status, status)} {name} — 依据: {ref}")
        sections.append("\n".join(lines))

    # ── 风险等级（S4 之后注入）──
    if risk_level:
        triggers_str = "、".join(risk_trigger_conditions) if risk_trigger_conditions else "无特定触发条件"
        sections.append(
            f"【风险等级——由系统查表，你仅转述】\n"
            f"等级: {risk_level}\n"
            f"触发条件: {triggers_str}"
        )

    # ── 检测方案（S5 之后注入）──
    if testing_items:
        lines = ["【检测方案——由系统查表，你仅转述】"]
        for item in testing_items:
            lines.append(f"  - {item.get('name', 'N/A')} | 标准: {item.get('standard', 'N/A')}")
        sections.append("\n".join(lines))

    # ── 报价结果（S6 之后注入）──
    if pricing_result:
        lines = [
            f"【报价结果——由系统计算，你仅转述】",
            f"标准总价: ¥{pricing_result.get('standard_total', 0):,}",
            f"折后小计: ¥{pricing_result.get('subtotal', 0):,}",
            f"税（6%）: ¥{pricing_result.get('tax', 0):,}",
            f"折后总计（含税）: ¥{pricing_result.get('total', 0):,}",
            f"参考周期: {pricing_result.get('cycle', 'N/A')}",
        ]
        if pricing_result.get("notes"):
            lines.append(f"备注: {pricing_result['notes']}")
        if pricing_result.get("unknown_items"):
            lines.append(f"未知项（需转人工）: {', '.join(pricing_result['unknown_items'])}")
        sections.append("\n".join(lines))

    # ── 禁止行为 ──
    forbidden = STATE_FORBIDDEN_ACTIONS.get(current_state, [])
    if forbidden:
        sections.append("【禁止行为】\n" + "\n".join(f"  - {f}" for f in forbidden))

    return "\n\n".join(sections)


def build_deflection_message(current_state: str, user_intent: str) -> str:
    """
    当用户试图跳过当前阶段直接问后续问题时，生成「偏转话术」。

    偏转话术是固定模板，不进 LLM 自由发挥。
    """
    templates = {
        "S1_skip_to_price": (
            "在给您报价之前，我需要先了解产品的基本信息（剂型、成分、功效），"
            "这样才能准确推荐检测项目和费用。您方便介绍一下产品吗？"
        ),
        "S1_skip_to_compliance": (
            "合规判定需要完整的成分信息和功效宣称作为依据。"
            "信息不完整时给出的结论可能不准确。先让我帮您梳理一下产品信息？"
        ),
        "S3_skip_to_price": (
            "报价需要先确定检测方案，而检测方案取决于成分的合规状态。"
            "等成分检查完成后我再为您估算费用。"
        ),
        "general_skip": (
            "抱歉，我需要按步骤完成预审流程，这样才能确保结论的准确性。"
            f"当前还在{current_state}阶段，让我们先完成这一步。"
        ),
    }

    if f"{current_state}_skip_to_price" in templates:
        return templates[f"{current_state}_skip_to_price"]
    if f"{current_state}_skip_to_compliance" in templates:
        return templates[f"{current_state}_skip_to_compliance"]
    return templates["general_skip"]
