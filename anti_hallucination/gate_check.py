"""
Layer 1 硬阻断 — Gate 变量完整性检查（Code Node，不进 LLM）。

在 NLU 抽取完成后执行。检查当前状态的必采变量是否全部非空。
不全 → 返回追问模板，loop 回阶段 2（NLU 抽取）。
完整 → 放行至主模型 + 判定引擎。

同时负责变量冲突检测（Step 3b）：
- 检测到同一字段新旧值不一致 → 标记 conflict，进入"修正确认"子流程
- 不直接静默覆盖，让用户明确感知修改已被识别
"""

from dataclasses import dataclass, field
from typing import Optional


# ── 必采字段定义 ─────────────────────────────────────────────────
# PRD 4.3: S1 阶段必须采集 6 个字段，缺一不可

REQUIRED_FIELDS: list[str] = [
    "product_name",         # 产品名称
    "dosage_form",          # 剂型（液体/凝胶/喷雾/湿巾/片剂/其他）
    "main_ingredients",     # 核心成分列表（INCI 名称或 CAS 号）
    "target_claims",        # 宣称功效（消毒/抗菌/抑菌/清洁/其他）
    "domestic_or_imported", # 国产/进口
    "customer_type",        # 品牌方/代工厂/中介/其他
]

# ── 选采字段（不影响流程推进）────────────────────────────────────

OPTIONAL_FIELDS: list[str] = [
    "usage_scenarios",       # 使用场景
    "existing_reports",      # 是否已有检测报告
    "historical_rejection",  # 是否有被退单历史
    "urgency_level",         # 紧急程度（普通/加急）
]

# ── 字段中文名映射 ───────────────────────────────────────────────

FIELD_LABELS: dict[str, str] = {
    "product_name": "产品名称",
    "dosage_form": "剂型",
    "main_ingredients": "核心成分",
    "target_claims": "宣称功效",
    "domestic_or_imported": "产地（国产/进口）",
    "customer_type": "您的角色（品牌方/代工厂/中介/其他）",
    "usage_scenarios": "使用场景",
    "existing_reports": "已有检测报告",
    "historical_rejection": "退单历史",
    "urgency_level": "紧急程度",
}

# ── 剂型有效值 ───────────────────────────────────────────────────

VALID_DOSAGE_FORMS: set[str] = {
    "液体", "凝胶", "喷雾", "湿巾", "片剂", "粉剂", "膏霜", "气雾", "其他"
}


@dataclass
class GateResult:
    """Gate 检查结果"""
    passed: bool
    missing_fields: list[str] = field(default_factory=list)
    conflict_fields: list[dict] = field(default_factory=list)
    invalid_fields: list[dict] = field(default_factory=list)
    follow_up_message: str = ""


def check_gate(
    session_vars: dict,
    newly_extracted: Optional[dict] = None,
) -> GateResult:
    """
    执行 Gate 检查。

    Step 3a: 变量完整性 — 6 个必采字段是否全部非空？
    Step 3b: 变量冲突检测 — 新提取的值与已有值是否冲突？

    Args:
        session_vars: 当前会话已累积的变量 {field_name: value}
        newly_extracted: 本轮 NLU 新提取的变量（可能为 None）

    Returns:
        GateResult: passed=True 表示所有检查通过，可放行至主模型
    """
    missing: list[str] = []
    conflicts: list[dict] = []
    invalids: list[dict] = []

    # ── Step 3a: 变量完整性检查 ──
    for field in REQUIRED_FIELDS:
        current_value = session_vars.get(field)
        if current_value is None or (isinstance(current_value, str) and not current_value.strip()):
            missing.append(field)

    # ── 值域校验（仅对已填充的字段做基本校验）──
    dosage = session_vars.get("dosage_form")
    if dosage and isinstance(dosage, str) and dosage.strip():
        if dosage.strip() not in VALID_DOSAGE_FORMS:
            invalids.append({
                "field": "dosage_form",
                "value": dosage,
                "hint": f"有效值：{' / '.join(sorted(VALID_DOSAGE_FORMS))}",
            })

    # ── Step 3b: 变量冲突检测 ──
    if newly_extracted:
        for field, new_value in newly_extracted.items():
            if new_value is None or (isinstance(new_value, str) and not new_value.strip()):
                continue
            old_value = session_vars.get(field)
            if old_value is not None and str(old_value).strip():
                if str(old_value).strip() != str(new_value).strip():
                    conflicts.append({
                        "field": field,
                        "label": FIELD_LABELS.get(field, field),
                        "old_value": str(old_value).strip(),
                        "new_value": str(new_value).strip(),
                    })

    # ── 构建结果 ──
    if missing or invalids:
        return GateResult(
            passed=False,
            missing_fields=missing,
            invalid_fields=invalids,
            follow_up_message=_build_follow_up(missing, invalids, conflicts),
        )

    if conflicts:
        return GateResult(
            passed=False,  # 有冲突时也暂停，等用户确认
            conflict_fields=conflicts,
            follow_up_message=_build_conflict_message(conflicts),
        )

    return GateResult(passed=True)


def _build_follow_up(
    missing: list[str],
    invalids: list[dict],
    conflicts: list[dict],
) -> str:
    """构建追问模板（固定话术，不进 LLM）"""
    lines: list[str] = []

    if missing:
        labels = [FIELD_LABELS.get(f, f) for f in missing]
        if len(labels) == 1:
            lines.append(f"在为您分析之前，我还需要确认一个信息：您的{labels[0]}是什么？")
        elif len(labels) <= 3:
            joined = "、".join(labels)
            lines.append(f"在为您分析之前，还需要确认以下信息：{joined}。")
        else:
            joined = "、".join(labels)
            lines.append(f"在为您分析之前，还需要确认以下信息：{joined}。")
            lines.append("这些是合规预审的基础信息，缺少任何一项都无法给出准确判定。")

    if invalids:
        for inv in invalids:
            label = FIELD_LABELS.get(inv["field"], inv["field"])
            lines.append(f"您提供的「{label}」值为「{inv['value']}」，{inv['hint']}。")
            lines.append(f"请重新提供「{label}」。")

    return "\n".join(lines)


def _build_conflict_message(conflicts: list[dict]) -> str:
    """构建变量冲突确认消息"""
    lines = ["我注意到您之前提供的信息有变化："]
    for c in conflicts:
        lines.append(f"  · {c['label']}：{c['old_value']} → {c['new_value']}")
    lines.append("")
    lines.append("这个修改会影响后续的分析结果。我已为您标记，确认修改后会自动更新相关结论。")
    lines.append("请问还有其他需要调整的信息吗？")
    return "\n".join(lines)


# ── 变量→状态依赖图（级联作废规则）──────────────────────────────
# PRD 4.2.1 B 节：每个必采字段变更后，哪些下游状态会失效

FIELD_DEPENDENCY_MAP: dict[str, tuple[str, ...]] = {
    "product_name":           (),                    # 仅元数据，不触发回退
    "dosage_form":            ("S2", "S5", "S6"),    # 剂型影响品类分类和检测基础包
    "main_ingredients":       ("S3", "S4", "S5", "S6"),  # 成分是合规/风险/检测的核心
    "target_claims":          ("S4", "S5", "S6"),    # 宣称影响风险分级和检测增量
    "domestic_or_imported":   ("S2", "S3", "S4", "S5", "S6"),  # 进口全链路受影响
    "customer_type":          ("S6",),                # 仅影响协议价匹配
    "urgency_level":          ("S6",),                # 仅影响加急系数和周期
    "historical_rejection":   ("S4", "S5", "S6"),    # 退单历史直通 R3
}

# 冲突字段允许的最大修改次数（防试探）
MAX_FIELD_MODIFICATIONS = 3


def get_rollback_state(conflict_fields: list[str]) -> str:
    """
    根据冲突字段计算应该回退到哪个状态。

    取所有冲突字段在依赖链上的最上游触发状态。
    例如：改了 main_ingredients → 回退到 S3
          同时改了 main_ingredients 和 dosage_form → 回退到 S2（最上游）

    Returns:
        状态编号，如 "S2"、"S3" 等；无需回退返回空字符串
    """
    all_affected: set[str] = set()
    for field in conflict_fields:
        deps = FIELD_DEPENDENCY_MAP.get(field, ())
        all_affected.update(deps)

    if not all_affected:
        return ""

    # S 编号越小越上游，取最小的
    state_nums = sorted(int(s[1]) for s in all_affected)
    return f"S{state_nums[0]}"


def get_stale_states(conflict_fields: list[str]) -> set[str]:
    """获取需要标记为 stale 的所有下游状态"""
    stale: set[str] = set()
    for field in conflict_fields:
        deps = FIELD_DEPENDENCY_MAP.get(field, ())
        stale.update(deps)
    return stale
