"""
F4 拒答策略 — 医疗暗示关键词检测。

PRD 5.1.2：消字号产品禁止医疗用途宣传。检测到医疗暗示时：
1. 立即中断当前分析
2. 告知用户边界
3. 询问是否在消字号合规范围内继续

与 F3 safety_keywords 的差异：
- safety_keywords: 恶意行为（规避监管、造假）→ 直接拒绝，不继续
- medical_keywords: 可能无意中用词 → 中断+确认，用户确认后恢复
"""

from dataclasses import dataclass, field
from typing import Optional


# ── 医疗暗示关键词 ───────────────────────────────────────────────
# 按严重程度分两级：
#   Level 1 (强医疗暗示): 明确疾病/病毒名称 → 中断，标记 risk
#   Level 2 (边界用语): 模糊的医疗化表述 → 提示，不强制中断

MEDICAL_KEYWORDS_L1: list[str] = [
    # 疾病名称
    "治疗湿疹", "治疗皮炎", "治疗脚气", "治疗痤疮", "治疗银屑病",
    "治疗炎症", "治疗感染", "治疗过敏", "治疗烧伤", "治疗烫伤",
    "治湿疹", "治脚气", "治痤疮",
    # 病毒/病原体
    "抗病毒", "杀病毒", "灭活病毒", "抗新冠病毒", "杀灭新冠",
    "新型冠状病毒", "新冠病毒", "SARS", "MERS",
    "抑制幽门螺杆菌", "杀灭幽门螺杆菌", "幽门螺旋杆菌",
    "抗HIV", "杀灭HIV", "抗艾滋",
    "杀灭流感病毒", "抗流感病毒",
    "杀灭结核", "抗结核",
    "杀灭HPV", "抗HPV",
    # 癌症相关
    "抗癌", "抗肿瘤", "杀癌细胞",
    # 明确药物/医疗器械暗示
    "药物治疗", "临床治疗", "药用", "药品级",
]

MEDICAL_KEYWORDS_L2: list[str] = [
    # 模糊的医疗化表述
    "消炎", "消肿", "止痛", "止痒", "止血",
    "促进愈合", "加速愈合", "伤口愈合",
    "提高免疫力", "增强免疫", "调节免疫",
    "抗过敏", "防过敏",
    "改善湿疹", "缓解皮炎",
    "修复皮肤", "修复受损",
    "深层杀菌", "彻底灭菌",
    # 专业医疗场景
    "术前消毒", "术后消毒", "手术消毒",
    "伤口消毒", "创面消毒", "黏膜消毒",
]


@dataclass
class MedicalKeywordResult:
    """医疗关键词检测结果"""
    detected: bool
    level: Optional[str] = None       # "L1" | "L2" | None
    matched_keywords: list[str] = field(default_factory=list)
    should_interrupt: bool = False    # L1 → True, L2 → False
    interrupt_message: str = ""

    def __bool__(self):
        return self.detected


def detect_medical_keywords(user_input: str) -> MedicalKeywordResult:
    """
    检测用户输入中是否包含医疗暗示关键词。

    L1 命中 → should_interrupt=True，立即中断
    L2 命中 → should_interrupt=False，仅追加提示
    """
    if not user_input or not user_input.strip():
        return MedicalKeywordResult(detected=False)

    # 检查 L1（强医疗暗示）
    matched_l1: list[str] = []
    for kw in MEDICAL_KEYWORDS_L1:
        if kw in user_input:
            matched_l1.append(kw)

    if matched_l1:
        return MedicalKeywordResult(
            detected=True,
            level="L1",
            matched_keywords=matched_l1,
            should_interrupt=True,
            interrupt_message=_build_l1_interrupt(matched_l1),
        )

    # 检查 L2（边界用语）
    matched_l2: list[str] = []
    for kw in MEDICAL_KEYWORDS_L2:
        if kw in user_input:
            matched_l2.append(kw)

    if matched_l2:
        return MedicalKeywordResult(
            detected=True,
            level="L2",
            matched_keywords=matched_l2,
            should_interrupt=False,
            interrupt_message=_build_l2_warning(matched_l2),
        )

    return MedicalKeywordResult(detected=False)


def _build_l1_interrupt(keywords: list[str]) -> str:
    quoted = "、".join(f"「{kw}」" for kw in keywords[:3])
    return (
        f"需要提示：消字号产品的功效宣传不能涉及疾病治疗、抗病毒等医疗用途表述。"
        f"您提到的{quoted}可能触及这个边界。\n\n"
        f"请问您是否需要我基于消字号合规范围继续分析？"
    )


def _build_l2_warning(keywords: list[str]) -> str:
    quoted = "、".join(f"「{kw}」" for kw in keywords[:3])
    return (
        f"顺便提示：{quoted}等表述在消字号产品标签中可能受到限制，"
        f"建议在正式宣传前确认合规性。"
    )
