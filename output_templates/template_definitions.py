"""
F5 输出模板 — 各状态的固定输出模板定义。

每个状态有唯一的结构化模板，主模型负责填充占位符，不负责决定输出结构。
模板中的 {占位符} 由 Code Node 或主模型替换为实际值。

模板层级：
  S1: 信息确认 + 追问（半结构化）
  S2: 品类判定（结构化表格）
  S3: 成分合规状态（逐项列表 + 法规引用）
  S4: 风险评级（等级 + 触发条件列表）
  S5: 检测方案（项目表格）
  S6: 报价预估（费用表格）
  S7: 预审摘要（全链路聚合，对应 PDF 报告结构）
"""

from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════════
# S1 信息采集 — 确认 + 追问
# ═══════════════════════════════════════════════════════════════════

S1_TEMPLATE = """【已确认信息】
{confirmed_fields}

【还需确认】
{missing_fields_prompt}"""

S1_CONFIRMED_FIELD_LINE = "· {label}: {value}"

# ═══════════════════════════════════════════════════════════════════
# S2 品类判定
# ═══════════════════════════════════════════════════════════════════

S2_TEMPLATE = """【品类判定】
产品名称：{product_name}
剂型：{dosage_form}
判定结果：{category}
适用法规路径：{regulation_path}

【判定依据】
{determination_basis}

{import_note}

【下一步】成分合规检查
接下来将逐项核查以下成分在法规目录中的状态：
{ingredients_preview}"""

S2_IMPORT_NOTE = (
    "注：进口产品无需《消毒产品生产企业卫生许可证》，"
    "但需提供原产国自由销售证明和进口备案申请表。"
)

# ═══════════════════════════════════════════════════════════════════
# S3 成分合规状态
# ═══════════════════════════════════════════════════════════════════

S3_TEMPLATE = """【成分合规状态】

{ingredient_table}

{summary_note}"""

S3_INGREDIENT_ROW_ALLOWED = "✅ {name} — 允许使用（依据: {reference}）"
S3_INGREDIENT_ROW_PROHIBITED = "❌ {name} — 禁止使用（依据: {reference}）"
S3_INGREDIENT_ROW_UNKNOWN = "⚠️ {name} — 未收录（{note}）"

S3_SUMMARY_ALL_CLEAR = "以上成分均在允许使用范围内，无禁用或未收录成分。"
S3_SUMMARY_HAS_ISSUES = (
    "存在{prohibited_count}项禁用成分、{unknown_count}项未收录成分，"
    "详见上方标注。"
)


def build_s3_ingredient_rows(
    results: list[dict],
) -> str:
    """根据成分查表结果构建 S3 的逐项列表"""
    rows: list[str] = []
    for ing in results:
        name = ing.get("name", "未知")
        status = ing.get("status", "unknown")
        ref = ing.get("reference", "")

        if status == "allowed":
            rows.append(S3_INGREDIENT_ROW_ALLOWED.format(name=name, reference=ref))
        elif status == "prohibited":
            rows.append(S3_INGREDIENT_ROW_PROHIBITED.format(name=name, reference=ref))
        else:
            note = ing.get("note", "现行消字号法规目录中暂无明确收录")
            rows.append(S3_INGREDIENT_ROW_UNKNOWN.format(name=name, note=note))

    return "\n".join(rows)


# ═══════════════════════════════════════════════════════════════════
# S4 风险评级
# ═══════════════════════════════════════════════════════════════════

S4_TEMPLATE = """【风险评级】

风险等级：{risk_level_label}
{risk_description}

【触发条件】
{trigger_conditions}

【引擎行为】
{engine_action}

{disclaimer}"""

RISK_LABELS = {
    "R1": "R1 低风险",
    "R2": "R2 中风险",
    "R3": "R3 高风险",
}

RISK_DESCRIPTIONS = {
    "R1": "产品成分均在允许清单中，功效宣称合规，国产路径清晰。可以正常推进检测和备案。",
    "R2": (
        "存在以下不确定性因素，建议在推进前安排技术专家复核：\n"
        "{uncertainty_reasons}"
    ),
    "R3": (
        "产品存在以下严重合规障碍，不建议在当前状态下推进备案：\n"
        "{blocking_reasons}"
    ),
}

RISK_ACTIONS = {
    "R1": "正常输出检测方案和报价预估。",
    "R2": "输出检测方案和报价，同时标注不确定性，建议人工复核。",
    "R3": "不输出检测方案和报价。建议转人工专家进一步评估。",
}

RISK_DISCLAIMERS = {
    "R1": "",
    "R2": (
        "\n⚠️ 免责声明：本风险评级基于当前提供的信息和现行法规。"
        "中风险不意味着不能备案，但建议在正式申报前由技术负责人确认。"
    ),
    "R3": (
        "\n⚠️ 本产品存在严重合规障碍。以上判定基于现行消字号法规，"
        "如产品配方或宣称调整后可重新评估。"
    ),
}


def build_s4_output(
    risk_level: str,
    trigger_conditions: list[str],
    uncertainty_reasons: Optional[list[str]] = None,
    blocking_reasons: Optional[list[str]] = None,
) -> str:
    """构建 S4 风险评级输出"""
    label = RISK_LABELS.get(risk_level, risk_level)

    if risk_level == "R1":
        desc = RISK_DESCRIPTIONS["R1"]
    elif risk_level == "R2":
        reasons_str = "\n".join(f"  · {r}" for r in (uncertainty_reasons or []))
        desc = RISK_DESCRIPTIONS["R2"].format(uncertainty_reasons=reasons_str)
    else:
        reasons_str = "\n".join(f"  · {r}" for r in (blocking_reasons or []))
        desc = RISK_DESCRIPTIONS["R3"].format(blocking_reasons=reasons_str)

    triggers = "\n".join(f"  · {t}" for t in trigger_conditions) if trigger_conditions else "  无特定触发条件"

    action = RISK_ACTIONS.get(risk_level, "")
    disclaimer = RISK_DISCLAIMERS.get(risk_level, "")

    return S4_TEMPLATE.format(
        risk_level_label=label,
        risk_description=desc,
        trigger_conditions=triggers,
        engine_action=action,
        disclaimer=disclaimer,
    )


# ═══════════════════════════════════════════════════════════════════
# S5 检测方案
# ═══════════════════════════════════════════════════════════════════

S5_TEMPLATE = """【推荐检测方案】

产品品类：{category}
剂型：{dosage_form}
适用标准体系：{standard_system}

{testing_table}

【方案说明】
{notes}

【总计】
检测项目：{total_items} 项
预计样品数量：约 {sample_count} 份"""

S5_TESTING_TABLE_HEADER = (
    "序号 | 检测项目             | 参考标准           | 样品数 | 说明\n"
    "-----+---------------------+-------------------+--------+------------------"
)

S5_TESTING_ROW = "{index:4} | {name:20} | {standard:18} | {samples:6} | {note}"

S5_NONSTANDARD_NOTE = (
    "\n⚠️ 以下为非标准宣称对应的检测项目，置信度为{confidence}，建议人工确认：\n"
    "{nonstandard_items}"
)


def build_s5_testing_table(
    items: list[dict],
    include_nonstandard: bool = False,
) -> str:
    """构建 S5 检测方案表格"""
    lines = [S5_TESTING_TABLE_HEADER]
    for i, item in enumerate(items, 1):
        lines.append(S5_TESTING_ROW.format(
            index=i,
            name=item.get("name", ""),
            standard=item.get("standard", ""),
            samples=str(item.get("sample_count", "-")),
            note=item.get("note", ""),
        ))
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# S6 报价预估
# ═══════════════════════════════════════════════════════════════════

S6_TEMPLATE = """【费用预估】

{pricing_table}

────────────────────────────
折后小计               ¥{subtotal:,.0f}
税（6%）               ¥{tax:,.0f}
────────────────────────────
折后总计（含税）        ¥{total:,.0f}

参考周期：{cycle}
报价有效期：30 天

{notes}"""

S6_PRICING_TABLE_HEADER = (
    "检测项目               | 单价\n"
    "-----------------------+----------"
)

S6_PRICING_ROW = "{name:22} | ¥{price:>8,.0f}"

S6_UNKNOWN_ITEMS_NOTE = (
    "⚠️ 以下检测项目暂无标准报价，需人工确认：\n"
    "{unknown_list}\n"
    "已知项目报价如上，请联系销售顾问获取完整报价。"
)

S6_URGENCY_NOTE = "加急服务附加费已计入，周期为加急周期。"


def build_s6_pricing_table(items: list[dict]) -> str:
    """构建 S6 报价明细表"""
    lines = [S6_PRICING_TABLE_HEADER]
    for item in items:
        lines.append(S6_PRICING_ROW.format(
            name=item.get("name", ""),
            price=item.get("price", 0),
        ))
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# S7 预审摘要（全链路聚合，对应 PDF 报告结构）
# ═══════════════════════════════════════════════════════════════════

S7_TEMPLATE = """═══════════════════════════════════════
      消字号合规 · 意向预审报告
═══════════════════════════════════════

报告编号：{report_id}
生成日期：{report_date}
报告有效期：30 天
───────────────────────────────────────

一、产品信息
  产品名称：{product_name}
  剂型：{dosage_form}
  产地：{domestic_or_imported}
  核心成分：{ingredients_summary}
  宣称功效：{claims_summary}
  客户类型：{customer_type}

二、合规预审结论
  品类判定：{category}
  适用法规路径：{regulation_path}
  风险等级：{risk_level_label}

  成分合规状态：
{ingredient_summary_table}

三、推荐检测方案
{testing_summary}

四、费用预估
{pricing_summary}

五、声明
  · 本报告为基于当前提供信息的意向预审，不构成最终合规结论
  · 正式备案以实际送检和卫健委审核结果为准
  · 费用以正式合同为准
  · 成分信息由客户提供，引擎未做实验验证

───────────────────────────────────────
  联系人：{contact_name}
  电话：{contact_phone}
  邮箱：{contact_email}

  XX检测机构 · 消字号合规预审引擎 v1.0
═══════════════════════════════════════"""


# ═══════════════════════════════════════════════════════════════════
# 模板注册表 — 状态 → 模板 + 必含标题
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TemplateSpec:
    state: str
    template: str
    required_sections: list[str]
    required_fields: list[str]
    description: str


TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {
    "S1": TemplateSpec(
        state="S1",
        template=S1_TEMPLATE,
        required_sections=["已确认信息", "还需确认"],
        required_fields=[],
        description="信息采集阶段，确认已有信息 + 追问缺失字段",
    ),
    "S2": TemplateSpec(
        state="S2",
        template=S2_TEMPLATE,
        required_sections=["品类判定", "判定依据", "下一步"],
        required_fields=["category", "regulation_path", "determination_basis"],
        description="品类判定结果",
    ),
    "S3": TemplateSpec(
        state="S3",
        template=S3_TEMPLATE,
        required_sections=["成分合规状态"],
        required_fields=[],
        description="成分合规状态逐项列表",
    ),
    "S4": TemplateSpec(
        state="S4",
        template=S4_TEMPLATE,
        required_sections=["风险评级", "触发条件", "引擎行为"],
        required_fields=["risk_level_label", "trigger_conditions"],
        description="风险评级结果",
    ),
    "S5": TemplateSpec(
        state="S5",
        template=S5_TEMPLATE,
        required_sections=["推荐检测方案", "总计"],
        required_fields=[],
        description="检测方案推荐",
    ),
    "S6": TemplateSpec(
        state="S6",
        template=S6_TEMPLATE,
        required_sections=["费用预估"],
        required_fields=[],
        description="费用预估明细",
    ),
    "S7": TemplateSpec(
        state="S7",
        template=S7_TEMPLATE,
        required_sections=[
            "产品信息", "合规预审结论", "推荐检测方案",
            "费用预估", "声明",
        ],
        required_fields=[
            "report_id", "report_date", "product_name",
            "category", "risk_level_label",
        ],
        description="全链路预审摘要报告",
    ),
}


def get_template(state: str) -> TemplateSpec:
    """获取指定状态的输出模板"""
    return TEMPLATE_REGISTRY.get(state, TEMPLATE_REGISTRY["S1"])
