"""
F5 输出模板 — 模板校验器。

验证主模型输出是否符合固定模板结构。
与 F3 output_verifier 的差异：
  - F3 校验层: 安全检查（幻觉信号、引用缺失、安全词）
  - F5 校验器: 结构检查（标题完整、字段齐全、格式合规）

两者串联使用：先 F5 校验结构 → 再 F3 校验安全。
"""

from dataclasses import dataclass, field
from typing import Optional

from output_templates.template_definitions import get_template, TemplateSpec


@dataclass
class TemplateValidationResult:
    """模板校验结果"""
    passed: bool
    state: str = ""
    missing_sections: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    format_issues: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def validate_output(
    raw_output: str,
    current_state: str,
) -> TemplateValidationResult:
    """
    校验输出是否符合当前状态的模板结构。

    校验项（按严重程度排序）：
    1. 必含标题是否齐全（硬伤，缺了就 failed）
    2. 关键字段是否已填充（不是占位符空值）
    3. 格式是否正确（表头、分隔线等）
    """
    spec = get_template(current_state)
    issues: list[str] = []
    missing_sections: list[str] = []
    missing_fields: list[str] = []
    format_issues: list[str] = []

    # ── 1. 标题完整性 ──
    for section in spec.required_sections:
        # 支持中文书名号和方括号两种格式
        found = (
            f"【{section}】" in raw_output
            or f"一、{section}" in raw_output
            or f"二、{section}" in raw_output
            or f"三、{section}" in raw_output
            or f"四、{section}" in raw_output
            or f"五、{section}" in raw_output
            or section in raw_output
        )
        if not found:
            missing_sections.append(section)
            issues.append(f"模板缺失标题: 「{section}」")

    # ── 2. 关键字段非空 ──
    for field in spec.required_fields:
        # 检查占位符 {field} 是否已被替换
        placeholder = "{" + field + "}"
        if placeholder in raw_output:
            missing_fields.append(field)
            issues.append(f"字段未填充: {{{field}}}")

        # 检查是否有空值表头后面没内容
        if f"{field}：" in raw_output:
            after = raw_output.split(f"{field}：", 1)
            if len(after) > 1:
                content = after[1].split("\n")[0].strip()
                if not content or content in ("", "N/A", "null", "None"):
                    missing_fields.append(field)
                    issues.append(f"字段值为空: {field}")

    # ── 3. 格式检查 ──
    if current_state == "S5":
        if "参考标准" not in raw_output:
            format_issues.append("S5 检测方案缺少「参考标准」列")
    if current_state == "S6":
        if "¥" not in raw_output and "元" not in raw_output:
            format_issues.append("S6 报价缺少货币符号")
        if "税" not in raw_output:
            format_issues.append("S6 报价缺少税费标注")
    if current_state == "S7":
        if "声明" not in raw_output:
            format_issues.append("S7 预审报告缺少「声明」章节")

    issues.extend(format_issues)

    passed = len(missing_sections) == 0 and len(missing_fields) == 0

    return TemplateValidationResult(
        passed=passed,
        state=current_state,
        missing_sections=missing_sections,
        missing_fields=missing_fields,
        format_issues=format_issues,
        issues=issues,
    )


# ── 关键字段映射表：哪些字段在哪个状态必须出现 ──

STATE_REQUIRED_DISPLAY_FIELDS: dict[str, list[str]] = {
    "S2": ["product_name", "dosage_form", "category", "regulation_path"],
    "S3": [],  # 成分数量可变
    "S4": ["风险等级", "触发条件"],
    "S5": ["检测项目", "参考标准"],
    "S6": ["折后总计", "参考周期"],
    "S7": [
        "产品名称", "剂型", "品类判定", "风险等级",
        "检测方案", "费用预估", "声明",
    ],
}
