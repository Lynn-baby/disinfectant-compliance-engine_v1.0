"""
Coze Code Node — S7 预审摘要生成（summary_generator.py）

架构位置：终端节点，S0-S6 全链路数据的聚合装配
前置节点：S0 安全扫描 + S1 入口解析 + S2 分类判定 + S3 成分合规 + S4 风险分级 + S5 检测方案 + S6 报价预估
角色：纯数据聚合——不做合规判定，只将上游结构化结果装配为可读报告。

输出：
  - markdown_report: 完整 Markdown 预审报告（可直接展示或供 LLM 渲染）
  - summary_json: 结构化 JSON（供程序化消费）
  - next_steps: 下一步建议（基于风险等级）
  - disclaimer: 免责声明文本

法规依据：PRD 4.4 风险分级 + PRD 3.4.2 输出模板

Coze 兼容性：
  - Python 3.11.3（Coze 运行时版本）
  - 仅用标准库（json + re）
  - 单函数入口 main()
"""

import json as _json

# ═══════════════════════════════════════════════════════════════
# 诊断信息收集
# ═══════════════════════════════════════════════════════════════

_diagnostics: list[str] = []


def _warn(msg: str) -> None:
    _diagnostics.append(msg)


def _get(args, key, default=None):
    if hasattr(args, 'params') and hasattr(args.params, 'get'):
        return args.params.get(key, default)
    if hasattr(args, 'get'):
        return args.get(key, default)
    raise AttributeError(f"args 类型异常: {type(args).__name__}，无 params 属性也无 get 方法")


def _build_error(code: str, message: str) -> dict:
    return {
        "markdown_report": f"# 预审报告生成失败\n\n**错误码**: {code}\n\n**详情**: {message}\n\n请检查上游节点输出或联系技术支持。",
        "summary_json": _json.dumps({"error": code, "message": message}, ensure_ascii=False),
        "next_steps": "系统内部错误，建议转人工处理。",
        "disclaimer": "",
        "report_ready": False,
        "diagnostics": _json.dumps(_diagnostics, ensure_ascii=False),
    }


# ═══════════════════════════════════════════════════════════════
# 下一步建议（基于风险等级）
# ═══════════════════════════════════════════════════════════════

NEXT_STEPS = {
    "R1": (
        "您的产品已完成合规预审，各项指标在标准范围内。"
        "建议联系检测机构销售顾问获取详细报价，准备启动消字号备案流程。"
    ),
    "R2": (
        "您的产品已完成合规预审，但存在部分需要关注的风险点。"
        "建议在正式启动备案前进行人工复核，确认风险可控后再进入检测报价环节。"
    ),
    "R3": (
        "您的产品存在高风险因素，系统已自动阻断后续报价流程。"
        "强烈建议转接人工专家进行深入评估，不要自行启动备案程序。"
    ),
}

DISCLAIMERS = {
    "R1": "",
    "R2": (
        "⚠️ **风险提示**：本预审结果基于当前提供的产品信息和系统知识库判定，"
        "存在部分不确定因素。建议人工复核后进入正式流程。"
        "本报告不作为最终备案依据。"
    ),
    "R3": (
        "🚫 **高风险警示**：本产品存在严重合规风险，系统已禁止生成报价。"
        "本报告仅供内部参考，不作为任何备案或上市依据。"
        "请务必转人工专家评估。"
    ),
}


# ═══════════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════════

def _safe_parse_json(raw, default=None):
    """安全解析 JSON 字符串，失败时返回 default 并记录诊断。"""
    if default is None:
        default = []
    if isinstance(raw, (list, dict)):
        return raw
    if not raw or not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError, ValueError) as e:
        _warn(f"JSON 解析失败: {e}")
        return default


def _build_product_section(product_name: str, dosage_form: str,
                           domestic_or_imported: str, target_claims: str) -> str:
    """构建「一、产品信息」章节。"""
    lines = ["## 一、产品信息"]
    if product_name:
        lines.append(f"- **产品名称**：{product_name}")
    if dosage_form:
        lines.append(f"- **剂型**：{dosage_form}")
    origin = domestic_or_imported if domestic_or_imported else "未提供"
    lines.append(f"- **产地**：{origin}")
    if target_claims:
        lines.append(f"- **功效宣称**：{target_claims}")
    return "\n".join(lines)


def _build_classification_section(product_category: str, sub_type: str) -> str:
    """构建「二、合规预审结论 — 分类判定」章节。"""
    lines = ["## 二、合规预审结论", "", "### 2.1 分类判定"]
    if not product_category or product_category == "未分类":
        lines.append("\n产品暂未完成分类判定，请联系技术支持。\n")
        return "\n".join(lines)

    cat_map = {"第一类": "第一类消毒产品", "第二类": "第二类消毒产品", "第三类": "第三类消毒产品"}
    cat_display = cat_map.get(product_category, product_category)
    lines.append(f"\n**判定结果**：{cat_display}")
    if sub_type:
        lines.append(f"\n**子类型**：{sub_type}")

    guidance = {
        "第一类": "产品具有较高风险，需进行严格的安全性评价，包括全套毒理学试验。",
        "第二类": "产品具有中等风险，需按《消毒产品卫生安全评价规定》完成相应检测项目。",
        "第三类": "产品风险较低，需符合相关卫生标准和微生物指标要求。",
    }
    if product_category in guidance:
        lines.append(f"\n**法规路径**：{guidance[product_category]}")

    return "\n".join(lines)


def _build_compliance_section(ingredient_results: list) -> str:
    """构建「2.2 成分合规状态」章节。"""
    lines = ["### 2.2 成分合规状态", ""]

    if not ingredient_results:
        lines.append("无成分数据。")
        return "\n".join(lines)

    # 按状态分组
    allowed = []
    restricted = []
    unknown = []
    for ing in ingredient_results:
        name = ing.get("ingredient", ing.get("name", "未知成分"))
        status = ing.get("status", "unknown")
        entry = (name, status)
        if status in ("allowed_active", "allowed_inert", "water_base", "allowed"):
            allowed.append(entry)
        elif status == "restricted":
            restricted.append(entry)
        else:
            unknown.append(entry)

    # 允许成分（绿色标记）
    if allowed:
        names = "、".join(n for n, _ in allowed)
        lines.append(f"✅ **允许使用**（{len(allowed)} 项）：{names}")
        lines.append("")

    # 限用成分（黄色标记）
    if restricted:
        names = "、".join(n for n, _ in restricted)
        lines.append(f"⚠️ **限制使用**（{len(restricted)} 项）：{names}")
        lines.append("  > 上述成分在 GB 38850-2020 第 6 条限用物质清单中，需符合浓度限量要求。")
        lines.append("")

    # 未收录成分（红色/灰色标记）
    if unknown:
        names = "、".join(n for n, _ in unknown)
        lines.append(f"❓ **未收录**（{len(unknown)} 项）：{names}")
        lines.append("  > 上述成分未在 GB 38850-2020 活性/惰性清单中检索到，可能属于新消毒产品原料，需进一步确认。")
        lines.append("")

    if not unknown and not restricted:
        lines.append("\n所有成分均在 GB 38850-2020《消毒剂原料清单》允许使用范围内。")

    return "\n".join(lines)


def _build_risk_section(risk_level: str, risk_label: str,
                        trigger_labels: list, trigger_details: list) -> str:
    """构建「2.3 风险分级」章节。"""
    lines = ["### 2.3 风险分级", ""]

    if not risk_level:
        lines.append("风险分级数据缺失。")
        return "\n".join(lines)

    emoji = {"R1": "🟢", "R2": "🟡", "R3": "🔴"}
    level_emoji = emoji.get(risk_level, "⚪")

    lines.append(f"**风险等级**：{level_emoji} {risk_label}")

    # 触发条件说明
    if trigger_labels:
        lines.append(f"\n**判定依据**：")
        for i, label in enumerate(trigger_labels):
            detail = trigger_details[i] if i < len(trigger_details) else ""
            lines.append(f"- {label}：{detail}")

    # 行为说明
    actions = {
        "R1": "\n✅ 可以正常进入检测报价流程。",
        "R2": "\n⚠️ 可以进入检测方案环节，建议人工复核后报价。",
        "R3": "\n🚫 禁止生成报价，强制建议转人工专家处理。",
    }
    if risk_level in actions:
        lines.append(actions[risk_level])

    return "\n".join(lines)


def _build_testplan_section(test_total_count: int, test_summary: str,
                            safety_blocked: bool, safety_detail: str,
                            non_standard: str) -> str:
    """构建「三、检测方案」章节。"""
    lines = ["## 三、检测方案", ""]

    if test_total_count == 0:
        if safety_blocked:
            lines.append("⚠️ **安全层拦截**：检测方案未生成。")
            if safety_detail:
                lines.append(f"\n{safety_detail}")
        else:
            lines.append("暂未生成检测方案，请确认上游分类和风险判定已完成。")
        return "\n".join(lines)

    if test_summary:
        lines.append(test_summary)

    if safety_blocked:
        lines.append(f"\n⚠️ **安全提醒**：{safety_detail}" if safety_detail else "\n⚠️ **安全提醒**：部分宣称触发了安全拦截规则。")

    if non_standard.strip():
        lines.append(f"\n📋 **非标准宣称**：{non_standard}")
        lines.append("  > 上述宣称未在标准检测映射表中，建议人工确认是否需要额外的针对性检测。")

    return "\n".join(lines)


def _build_pricing_section(pricing_total: int, pricing_cycle: str,
                           is_priced: bool, pricing_notes: str) -> str:
    """构建「四、费用预估」章节。"""
    lines = ["## 四、费用预估", ""]

    if not is_priced or pricing_total == 0:
        lines.append("暂未生成费用预估。")
        if pricing_notes:
            lines.append(f"\n{pricing_notes}")
        return "\n".join(lines)

    lines.append(f"**预估总价**：¥{pricing_total:,}（含税）")
    if pricing_cycle:
        lines.append(f"\n**参考周期**：{pricing_cycle}")
    if pricing_notes:
        lines.append(f"\n{pricing_notes}")
    lines.append("\n> 以上为系统自动估算，实际费用以正式合同为准。报价有效期 30 天。")

    return "\n".join(lines)


def _build_next_steps(risk_level: str, is_classified: bool) -> str:
    """构建「五、下一步建议」章节。"""
    lines = ["## 五、下一步建议", ""]

    if not is_classified:
        lines.append("产品尚未完成分类判定，建议先补充产品类型和剂型信息。")
        return "\n".join(lines)

    steps = NEXT_STEPS.get(risk_level, NEXT_STEPS["R3"])
    lines.append(steps)

    # 通用建议
    lines.append("")
    lines.append("### 后续流程")
    lines.append("1. 联系检测机构销售顾问，提供本预审报告")
    lines.append("2. 确认检测项目清单和周期")
    lines.append("3. 准备产品样品送检")
    lines.append("4. 检测完成后进行网上备案")

    if risk_level == "R3":
        lines.clear()
        lines.append("## 四、下一步建议")
        lines.append("")
        lines.append(steps)

    return "\n".join(lines)


def _sanitize_text(value) -> str:
    """安全获取字符串值。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    return value.strip()


def generate_summary(
    product_name: str = "",
    dosage_form: str = "",
    domestic_or_imported: str = "",
    target_claims: str = "",
    product_category: str = "",
    sub_type: str = "",
    ingredient_results: list | None = None,
    risk_level: str = "",
    risk_label: str = "",
    trigger_labels: list | None = None,
    trigger_details: list | None = None,
    test_total_count: int = 0,
    test_summary: str = "",
    safety_blocked: bool = False,
    safety_detail: str = "",
    non_standard: str = "",
    pricing_total: int = 0,
    pricing_cycle: str = "",
    is_priced: bool = False,
    pricing_notes: str = "",
) -> dict:
    """汇总 S0-S6 全链路判定结果，生成预审摘要。

    返回:
        markdown_report: 完整 Markdown 预审报告
        summary_json: 结构化 JSON
        next_steps: 下一步建议纯文本
        disclaimer: 免责声明（如有）
        report_ready: 报告是否成功生成
    """
    if ingredient_results is None:
        ingredient_results = []
    if trigger_labels is None:
        trigger_labels = []
    if trigger_details is None:
        trigger_details = []

    # 前置检查：是否已分类
    is_classified = bool(product_category and product_category != "未分类")

    # ── 构建各章节 ──
    sections = []
    sections.append("# 消字号合规 · 意向预审报告")
    sections.append("")
    sections.append("> 本报告由合规预审引擎自动生成，基于当前提供的产品信息进行判定。")
    sections.append("> 报告结果仅供参考，最终以检测机构正式审核为准。")
    sections.append("")

    # 一、产品信息
    sections.append(_build_product_section(product_name, dosage_form,
                                           domestic_or_imported, target_claims))
    sections.append("")

    # 二、合规预审结论
    sections.append(_build_classification_section(product_category, sub_type))
    sections.append("")

    if is_classified:
        # 2.2 成分合规
        sections.append(_build_compliance_section(ingredient_results))
        sections.append("")

        # 2.3 风险分级
        sections.append(_build_risk_section(risk_level, risk_label,
                                            trigger_labels, trigger_details))
        sections.append("")

    # 三、检测方案
    sections.append(_build_testplan_section(test_total_count, test_summary,
                                            safety_blocked, safety_detail,
                                            non_standard))
    sections.append("")

    # 四、费用预估
    sections.append(_build_pricing_section(pricing_total, pricing_cycle,
                                           is_priced, pricing_notes))
    sections.append("")

    # 五、下一步建议
    sections.append(_build_next_steps(risk_level, is_classified))
    sections.append("")

    # 免责声明
    disclaimer = DISCLAIMERS.get(risk_level, "")
    if disclaimer:
        sections.append("---")
        sections.append("")
        sections.append(disclaimer)
        sections.append("")

    markdown_report = "\n".join(sections)

    # ── 结构化 JSON ──
    structured = {
        "product": {
            "name": product_name,
            "dosage_form": dosage_form,
            "origin": domestic_or_imported,
            "target_claims": target_claims,
        },
        "classification": {
            "category": product_category,
            "sub_type": sub_type,
            "is_classified": is_classified,
        },
        "compliance": {
            "ingredients": [
                {
                    "name": ing.get("ingredient", ing.get("name", "")),
                    "status": ing.get("status", "unknown"),
                }
                for ing in ingredient_results
            ],
        },
        "risk": {
            "level": risk_level,
            "label": risk_label,
            "triggers": trigger_labels,
            "trigger_details": trigger_details,
        },
        "test_plan": {
            "total_count": test_total_count,
            "summary": test_summary,
            "safety_blocked": safety_blocked,
            "non_standard": non_standard,
        },
        "pricing": {
            "total": pricing_total,
            "cycle": pricing_cycle,
            "is_priced": is_priced,
            "notes": pricing_notes,
        },
        "next_steps": NEXT_STEPS.get(risk_level, NEXT_STEPS["R3"]),
        "disclaimer": disclaimer,
    }

    return {
        "markdown_report": markdown_report,
        "summary_json": _json.dumps(structured, ensure_ascii=False),
        "next_steps": NEXT_STEPS.get(risk_level, NEXT_STEPS["R3"]),
        "disclaimer": disclaimer,
        "report_ready": True,
    }


# ═══════════════════════════════════════════════════════════════
# Coze Code Node 入口
# ═══════════════════════════════════════════════════════════════

async def main(args) -> dict:
    """Coze Code Node 入口（Python 3.11.3）。

    Coze 输入变量（来自 S0-S6 全链路）:
        # S1 输出
        product_name:           string  — 产品名称
        dosage_form:            string  — 剂型
        domestic_or_imported:   string  — 国产/进口
        target_claims:          string  — 功效宣称

        # S2 输出
        product_category:       string  — 第一类/第二类/第三类/未分类
        sub_type:               string  — 消毒剂/抗抑菌制剂/消毒器械/卫生用品

        # S3 输出
        results_json:           string  — 逐成分结果 JSON 数组

        # S4 输出
        risk_level:             string  — R1/R2/R3
        risk_label:             string  — 中文风险标签
        trigger_labels_json:    string  — 触发条件标签 JSON 数组
        trigger_details_json:   string  — 触发条件详情 JSON 数组

        # S5 输出
        test_total_count:       int     — 检测项总数
        test_summary:           string  — 检测方案概要
        safety_blocked:         bool    — 是否安全层拦截
        safety_detail:          string  — 安全拦截详情
        non_standard:           string  — 非标准宣称

        # S6 输出
        pricing_total:          int     — 折后总计含税
        pricing_cycle:          string  — 参考周期
        is_priced:              bool    — 报价是否成功生成
        pricing_notes:          string  — 报价备注

    Coze 输出变量:
        markdown_report:        string  — 完整 Markdown 预审报告
        summary_json:           string  — 结构化 JSON
        next_steps:             string  — 下一步建议
        disclaimer:             string  — 免责声明
        report_ready:           bool    — 报告是否生成成功
    """
    global _diagnostics
    _diagnostics = []

    # ── 解析输入 ──
    try:
        product_name = _sanitize_text(_get(args, "product_name", ""))
        dosage_form = _sanitize_text(_get(args, "dosage_form", ""))
        domestic_or_imported = _sanitize_text(_get(args, "domestic_or_imported", ""))
        target_claims = _sanitize_text(_get(args, "target_claims", ""))
        product_category = _sanitize_text(_get(args, "product_category", ""))
        sub_type = _sanitize_text(_get(args, "sub_type", ""))
        results_json = _get(args, "results_json", "[]")
        risk_level = _sanitize_text(_get(args, "risk_level", ""))
        risk_label = _sanitize_text(_get(args, "risk_label", ""))
        trigger_labels_json = _get(args, "trigger_labels_json", "[]")
        trigger_details_json = _get(args, "trigger_details_json", "[]")
        test_total_count_raw = _get(args, "test_total_count", 0)
        test_summary = _sanitize_text(_get(args, "test_summary", ""))
        safety_blocked = _get(args, "safety_blocked", False)
        safety_detail = _sanitize_text(_get(args, "safety_detail", ""))
        non_standard = _sanitize_text(_get(args, "non_standard", ""))
        pricing_total_raw = _get(args, "pricing_total", 0)
        pricing_cycle = _sanitize_text(_get(args, "pricing_cycle", ""))
        is_priced = _get(args, "is_priced", False)
        pricing_notes = _sanitize_text(_get(args, "pricing_notes", ""))
    except AttributeError as e:
        _warn(f"args 结构异常: {e}")
        return _build_error("S7_ARGS_STRUCTURE_ERROR", str(e))
    except Exception as e:
        _warn(f"输入解析未预期的异常: {type(e).__name__}: {e}")
        return _build_error("S7_INPUT_PARSE_ERROR", str(e))

    # ── 类型转换 ──
    ingredient_results = _safe_parse_json(results_json, [])
    trigger_labels = _safe_parse_json(trigger_labels_json, [])
    trigger_details = _safe_parse_json(trigger_details_json, [])

    if isinstance(trigger_labels, dict):
        trigger_labels = []
        _warn("trigger_labels_json 为对象而非数组，已重置为空列表")
    if isinstance(trigger_details, dict):
        trigger_details = []
        _warn("trigger_details_json 为对象而非数组，已重置为空列表")

    try:
        test_total_count = int(test_total_count_raw) if test_total_count_raw else 0
    except (ValueError, TypeError):
        test_total_count = 0

    if isinstance(safety_blocked, str):
        safety_blocked = safety_blocked.strip().lower() in ("true", "1", "yes")
    elif not isinstance(safety_blocked, bool):
        safety_blocked = bool(safety_blocked)

    try:
        pricing_total = int(pricing_total_raw) if pricing_total_raw else 0
    except (ValueError, TypeError):
        pricing_total = 0
        _warn(f"pricing_total 类型转换失败: {pricing_total_raw!r}")

    if isinstance(is_priced, str):
        is_priced = is_priced.strip().lower() in ("true", "1", "yes")
    elif not isinstance(is_priced, bool):
        is_priced = bool(is_priced)

    # ── 生成摘要 ──
    result = generate_summary(
        product_name=product_name,
        dosage_form=dosage_form,
        domestic_or_imported=domestic_or_imported,
        target_claims=target_claims,
        product_category=product_category,
        sub_type=sub_type,
        ingredient_results=ingredient_results,
        risk_level=risk_level,
        risk_label=risk_label,
        trigger_labels=trigger_labels,
        trigger_details=trigger_details,
        test_total_count=test_total_count,
        test_summary=test_summary,
        safety_blocked=safety_blocked,
        safety_detail=safety_detail,
        non_standard=non_standard,
        pricing_total=pricing_total,
        pricing_cycle=pricing_cycle,
        is_priced=is_priced,
        pricing_notes=pricing_notes,
    )

    if _diagnostics:
        result["diagnostics"] = _json.dumps(_diagnostics, ensure_ascii=False)

    return result
