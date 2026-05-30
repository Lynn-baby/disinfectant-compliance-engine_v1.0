"""
Layer 1 硬阻断 — 安全关键词扫描（纯字符串匹配，不进 LLM）。

每个请求的第一个操作永远是安全词扫描。
命中 → 直接返回拒绝模板，终止流程。
未命中 → 进入阶段 2（NLU 抽取）。

设计依据：安全关键词是封闭集合，纯字符串匹配无歧义，不需要语义理解。
"""

from dataclasses import dataclass, field
from typing import Optional

# ── 安全关键词词库 ──────────────────────────────────────────────
# 按类别组织，每个类别对应一个 block_reason
# 新增关键词只需追加到对应列表，不改代码逻辑

SAFETY_KEYWORDS: dict[str, list[str]] = {
    "规避监管": [
        "绕备案",
        "绕开备案",
        "绕过备案",
        "不备案",
        "免备案",
        "不用备案",
        "逃避监管",
        "不留痕迹",
        "不被查到",
        "偷偷卖",
        "私下卖",
        "怎么避开",
        "怎么绕过",
        "怎么逃",
        "不上备案",
        "跳过备案",
    ],
    "虚假宣传": [
        "夸大效果",
        "夸大宣传",
        "虚假宣传",
        "怎么写擦边",
        "擦边宣传",
        "夸大功效",
        "怎么写宣传",
        "违规宣传",
        "怎么写合规",
        "不会被罚",
        "怎么吹",
        "写神",
    ],
    "篡改报告": [
        "改检测报告",
        "改报告",
        "p一下检测",
        "修改检测",
        "篡改报告",
        "做假报告",
        "伪造报告",
        "包过检测",
        "保证过检",
        "作假",
        "作假报告",
        "做假检测",
    ],
    "虚构材料": [
        "虚构备案材料",
        "虚构材料",
        "假材料",
        "伪造材料",
        "怎么编",
        "材料作假",
        "虚构一个",
        "凭空编",
    ],
    "攻击/恶意": [
        "垃圾系统",
        "废物",
        "sb",
        "傻逼",
    ],
}

# ── 拒绝模板 ────────────────────────────────────────────────────
# 每个类别对应一段固定话术，LLM 不参与生成

REJECTION_TEMPLATES: dict[str, str] = {
    "规避监管": (
        "需要提示：消字号备案是国家法规要求，未备案产品上市销售属于违法行为。\n"
        "我们无法协助规避监管流程，但可以帮您了解合法合规的备案路径。\n"
        "请问您是否需要我介绍一下消字号备案的正规流程？"
    ),
    "虚假宣传": (
        "需要提示：消毒产品的功效宣传受《消毒产品标签说明书管理规范》严格约束，"
        "虚假或夸大宣传可能面临行政处罚。\n"
        "我们无法提供擦边宣传建议，但可以帮您了解合规的功效表述方式。\n"
        "请问您是否需要我介绍一下消字号产品允许的宣传范围？"
    ),
    "篡改报告": (
        "我们无法协助修改或伪造检测报告。检测报告由 CMA/CNAS 认证实验室出具，"
        "具有法律效力，篡改报告属于违法行为。\n"
        "如果您对检测结果有疑问，我们可以帮您了解复检流程。"
    ),
    "虚构材料": (
        "我们无法协助虚构备案材料。消字号备案要求真实、完整的申报材料，"
        "提供虚假材料将导致备案被拒并承担法律责任。\n"
        "如果您不清楚需要准备哪些材料，我可以为您列出完整的资料清单。"
    ),
    "攻击/恶意": (
        "抱歉，我无法处理这个请求。如果您有消字号备案相关的业务问题，欢迎继续咨询。"
    ),
}


@dataclass
class SafetyScanResult:
    """安全扫描结果"""
    blocked: bool
    block_reason: Optional[str] = None
    matched_keyword: Optional[str] = None
    rejection_message: Optional[str] = None


def scan_safety_keywords(user_input: str) -> SafetyScanResult:
    """
    对用户输入做安全关键词扫描。

    纯字符串匹配，O(n*m) 在短输入上足够快。
    匹配规则：关键词出现在输入的任意位置即命中（含子串匹配）。

    Args:
        user_input: 用户原始输入文本

    Returns:
        SafetyScanResult: blocked=True 表示命中，需拦截
    """
    if not user_input or not user_input.strip():
        return SafetyScanResult(blocked=False)

    text = user_input.lower().replace(" ", "")

    for category, keywords in SAFETY_KEYWORDS.items():
        for keyword in keywords:
            normalized_kw = keyword.lower().replace(" ", "")
            if normalized_kw in text:
                return SafetyScanResult(
                    blocked=True,
                    block_reason=category,
                    matched_keyword=keyword,
                    rejection_message=REJECTION_TEMPLATES.get(category, ""),
                )

    return SafetyScanResult(blocked=False)


# ── 变体检测（辅助词库维护）────────────────────────────────────
# PRD 10.2.1 ID-SEC-12: 输入包含规避词的变体/拼音
# 此函数用于检测可能的新变体，输出供人工 review 后决定是否扩充词库

VARIANT_PATTERNS: dict[str, list[str]] = {
    "规避监管": ["备an", "bei案", "bei4an4", "备 案"],
    "虚假宣传": ["夸大", "擦边", "擦 边"],
    "篡改报告": ["改报告", "做假", "p 图"],
    "虚构材料": ["假材料", "编材料"],
}


def detect_potential_variants(user_input: str) -> list[dict[str, str]]:
    """
    检测可能的规避词变体（不拦截，仅标记供人工 review）。

    返回潜在变体列表，每项包含 {suspected_category, matched_text}。
    空列表表示未发现潜在变体。
    """
    alerts: list[dict[str, str]] = []
    text = user_input.lower()
    for category, patterns in VARIANT_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                alerts.append({
                    "suspected_category": category,
                    "matched_text": pattern,
                })
    return alerts
