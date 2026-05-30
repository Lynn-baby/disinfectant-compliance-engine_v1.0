"""
F4 拒答策略 — 7 大业务边界场景检测器。

对应 PRD 5.1.1 ~ 5.1.7。每个场景有独立的检测函数和处理规则。
所有规则写死在 Code Node，不进 LLM。

输出标准化为 EdgeCaseResult，由 refusal_engine 统一决策。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EdgeAction(str, Enum):
    """边界场景的处理动作"""
    BLOCK = "block"              # 硬阻断，不继续
    INTERRUPT = "interrupt"      # 中断当前流程，等待用户确认
    WARN = "warn"                # 继续但追加警告/标注
    FAST_TRACK = "fast_track"    # 跳过中间阶段加速到目标状态
    ESCALATE = "escalate"        # 强制转人工
    PROMPT = "prompt"            # 追问一轮
    FLAG = "flag"                # 标记变量，不影响流程


class EdgeCase(str, Enum):
    """边界场景类型"""
    GREY_AREA_INGREDIENT = "grey_area_ingredient"     # 5.1.1 成分灰色地带
    MEDICAL_CLAIM = "medical_claim"                    # 5.1.2 医疗暗示
    IMPORT_UNDECLARED = "import_undeclared"            # 5.1.3 进口未声明
    REJECTION_HISTORY = "rejection_history"            # 5.1.4 退单隐瞒
    BUNDLE_PRODUCT = "bundle_product"                  # 5.1.5 套装/组合
    PRIOR_MARKET = "prior_market"                      # 5.1.6 先上市后补
    VAGUE_INGREDIENT = "vague_ingredient"              # 5.1.7 成分模糊


@dataclass
class EdgeCaseResult:
    """边界场景检测结果"""
    triggered: bool
    case: Optional[EdgeCase] = None
    action: EdgeAction = EdgeAction.FLAG
    message: str = ""
    metadata: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# 5.1.1 成分灰色地带
# ═══════════════════════════════════════════════════════════════════

GREY_AREA_INGREDIENTS: set[str] = {
    "植物提取物", "纳米银", "生物酶", "银离子", "锌离子",
    "壳聚糖", "溶菌酶", "噬菌体", "益生菌", "抗菌肽",
    "光触媒", "负离子", "远红外", "量子",
    "草本提取物", "中草药提取物", "天然提取物",
}


def detect_grey_area_ingredients(
    ingredients: list[str],
    kb_hit_statuses: Optional[list[str]] = None,
) -> EdgeCaseResult:
    """
    5.1.1: 检测成分是否处于法规灰色地带。

    触发条件：成分名称匹配灰色地带列表 OR kb_hit_status 中有 'no_hit'

    处理：标记 R2，禁止推断。输出「该成分在现行消字号法规目录中暂无明确收录」
    """
    matched: list[str] = []

    if ingredients:
        for ing in ingredients:
            if ing in GREY_AREA_INGREDIENTS:
                matched.append(ing)

    # 如果 kb 检索结果是 no_hit，也作为灰色地带处理
    if kb_hit_statuses:
        for i, status in enumerate(kb_hit_statuses):
            if status == "no_hit":
                ing_name = ingredients[i] if i < len(ingredients) else f"成分{i+1}"
                if ing_name not in matched:
                    matched.append(ing_name)

    if matched:
        names = "、".join(f"「{m}」" for m in matched[:5])
        return EdgeCaseResult(
            triggered=True,
            case=EdgeCase.GREY_AREA_INGREDIENT,
            action=EdgeAction.WARN,
            message=(
                f"以下成分在现行消字号法规目录中暂无明确收录，"
                f"建议提交省级卫健委进行法规释义确认：{names}"
            ),
            metadata={"grey_ingredients": matched, "force_r2": True},
        )

    return EdgeCaseResult(triggered=False)


# ═══════════════════════════════════════════════════════════════════
# 5.1.3 进口产品未声明产地
# ═══════════════════════════════════════════════════════════════════

IMPORT_SIGNALS: list[str] = [
    "进口", "原装进口", "日本", "韩国", "美国", "德国", "法国",
    "澳洲", "新西兰", "泰国", "意大利", "瑞士", "台湾", "香港",
    "国外品牌", "海外", "跨境", "保税仓",
]


def detect_import_undeclared(
    user_input: str,
    domestic_or_imported: Optional[str],
) -> EdgeCaseResult:
    """
    5.1.3: 检测进口产品是否声明产地。

    触发：用户输入包含进口信号但 domestic_or_imported 字段为空
    处理：所有后续结论标注「基于国产产品假设，如为进口产品请纠正」
    """
    if domestic_or_imported and domestic_or_imported.strip():
        return EdgeCaseResult(triggered=False)

    matched = [sig for sig in IMPORT_SIGNALS if sig in user_input]

    if matched:
        return EdgeCaseResult(
            triggered=True,
            case=EdgeCase.IMPORT_UNDECLARED,
            action=EdgeAction.WARN,
            message=(
                "基于国产产品假设进行以下分析。如为进口产品，"
                "备案路径和材料要求会有差异，请告知以便调整。"
            ),
            metadata={"import_signals": matched, "assume_domestic": True},
        )

    return EdgeCaseResult(triggered=False)


# ═══════════════════════════════════════════════════════════════════
# 5.1.4 退单历史隐瞒
# ═══════════════════════════════════════════════════════════════════

REJECTION_AVOIDANCE_SIGNALS: list[str] = [
    "之前做过", "之前备案", "之前咨询", "别的机构",
    "之前没过", "被退过", "被拒过", "没通过",
    "换一家", "重新备案",
]


def detect_rejection_history(
    user_input: str,
    historical_rejection: Optional[str],  # None / "yes" / "no" / "declined_to_answer"
    rejection_ask_count: int = 0,
) -> EdgeCaseResult:
    """
    5.1.4: 检测客户是否回避退单历史问题。

    处理规则：
    - 未问过 → PROMPT 主动询问
    - 问过1次客户回避 → PROMPT 再问1次
    - 问过2次仍回避 → FLAG，标注「未获取退单历史」
    - 确认有退单 → FLAG，进入退单诊断子流程
    """
    if historical_rejection == "yes":
        return EdgeCaseResult(
            triggered=True,
            case=EdgeCase.REJECTION_HISTORY,
            action=EdgeAction.FLAG,
            message="",
            metadata={"has_rejection": True, "enter_diagnosis_subflow": True},
        )

    if historical_rejection == "declined_to_answer" and rejection_ask_count >= 2:
        return EdgeCaseResult(
            triggered=True,
            case=EdgeCase.REJECTION_HISTORY,
            action=EdgeAction.FLAG,
            message="未获取退单历史，以下分析基于首次申报假设。",
            metadata={"assume_first_filing": True},
        )

    # 用户输入中包含退单信号但字段为空 → 追问
    if not historical_rejection:
        matched = [sig for sig in REJECTION_AVOIDANCE_SIGNALS if sig in user_input]
        if matched:
            return EdgeCaseResult(
                triggered=True,
                case=EdgeCase.REJECTION_HISTORY,
                action=EdgeAction.PROMPT,
                message=(
                    "了解备案历史是为了帮您规避之前的问题，提高本次通过率。"
                    "您的产品之前是否在消字号备案或检测过程中被退回或拒绝过？"
                ),
                metadata={"rejection_signals": matched},
            )

    return EdgeCaseResult(triggered=False)


# ═══════════════════════════════════════════════════════════════════
# 5.1.5 套装/组合/系列产品
# ═══════════════════════════════════════════════════════════════════

BUNDLE_SIGNALS: list[str] = [
    "套装", "系列", "一套", "组合", "搭配使用",
    "套盒", "礼盒", "套装产品", "全套",
]

MULTI_DOSAGE_SIGNALS: list[str] = [
    "加", "和", "还有", "以及", "另外", "搭配",
]


def detect_bundle_product(
    user_input: str,
    dosage_form: Optional[str] = None,
    ingredients_list_length: int = 0,
) -> EdgeCaseResult:
    """
    5.1.5: 检测套装/组合产品。

    触发：输入中含套装信号 OR 同时出现多个剂型 OR 成分列表包含分隔符

    处理：触发拆分追问。相同→合并处理，不同→逐个采集。
    """
    matched_signal: list[str] = []

    for signal in BUNDLE_SIGNALS:
        if signal in user_input:
            matched_signal.append(signal)

    # 成分列表用分隔符 → 也可能是多个产品
    if ingredients_list_length > 1:
        joined = " ".join(user_input.split()[-50:])  # 最后 50 词
        separators = ["、", "，", "；", ";", "和"]
        for sep in separators:
            if sep in joined:
                if "多个产品" not in " ".join(matched_signal):
                    pass  # 弱信号，不单独触发

    if matched_signal:
        return EdgeCaseResult(
            triggered=True,
            case=EdgeCase.BUNDLE_PRODUCT,
            action=EdgeAction.INTERRUPT,
            message=(
                "消字号备案以单个产品为单位。请问这些产品的成分和功效是否相同？\n"
                "· 如果相同 → 可以合并处理\n"
                "· 如果不同 → 需要逐个分析，每个产品我先采集 3 个核心信息做快速评级"
            ),
            metadata={"bundle_signals": matched_signal},
        )

    return EdgeCaseResult(triggered=False)


# ═══════════════════════════════════════════════════════════════════
# 5.1.6 先上市后补备案
# ═══════════════════════════════════════════════════════════════════

PRIOR_MARKET_SIGNALS: list[str] = [
    "已经在卖", "已经上市", "上市了", "在卖了",
    "被查了", "被举报", "被投诉", "被抽查",
    "平台下架", "被下架", "要求下架", "下架了",
    "被处罚", "收到通知", "整改通知",
    "工商查", "市场监管局", "药监局查",
    "偷偷卖", "私下卖", "已经在流通",
]


def detect_prior_market(user_input: str) -> EdgeCaseResult:
    """
    5.1.6: 检测产品是否已上市销售。

    触发：输入中包含已上市/被查处信号

    处理：标记 urgency_level=high, 跳过常规流程直接进 S4,
          强制建议人工介入, 提示标签合规检查
    """
    matched = [sig for sig in PRIOR_MARKET_SIGNALS if sig in user_input]

    if matched:
        return EdgeCaseResult(
            triggered=True,
            case=EdgeCase.PRIOR_MARKET,
            action=EdgeAction.FAST_TRACK,
            message=(
                "由于产品已在市场流通，建议尽快核查现有标签是否符合"
                "《消毒产品标签说明书管理规范》。如不合规，先行整改再提交备案。\n"
                "已为您标记为紧急处理，建议安排技术专家介入。"
            ),
            metadata={
                "prior_market_signals": matched,
                "force_urgency_high": True,
                "skip_to_s4": True,
                "force_human_review": True,
            },
        )

    return EdgeCaseResult(triggered=False)


# ═══════════════════════════════════════════════════════════════════
# 5.1.7 成分信息模糊
# ═══════════════════════════════════════════════════════════════════

VAGUE_INGREDIENT_TERMS: set[str] = {
    "植物提取物", "活性成分", "专利配方", "复合成分",
    "表面活性剂", "天然成分", "草本精华", "植物精华",
    "植物萃取", "中草药", "生物活性物", "功能性成分",
    "有效成分", "核心配方", "保密成分", "专有成分",
}


def detect_vague_ingredients(
    ingredients: list[str],
    vague_ask_count: int = 0,
) -> EdgeCaseResult:
    """
    5.1.7: 检测成分信息是否模糊。

    触发：成分列表中有 VAGUE_INGREDIENT_TERMS 中的笼统描述

    处理：
    - 第1-2次触发 → INTERRUPT 追问具体 INCI 名称或 CAS 号
    - 第3次仍不提供 → BLOCK，不输出合规结论
    """
    matched: list[str] = []
    for ing in ingredients:
        if ing in VAGUE_INGREDIENT_TERMS:
            matched.append(ing)

    if not matched:
        return EdgeCaseResult(triggered=False)

    if vague_ask_count >= 2:
        return EdgeCaseResult(
            triggered=True,
            case=EdgeCase.VAGUE_INGREDIENT,
            action=EdgeAction.BLOCK,
            message=(
                "成分信息不完整，无法输出合规结论。备案需要具体成分的 INCI 名称"
                "或 CAS 号。建议您在准备完整成分列表后重新咨询，或联系技术专家"
                "进行线下评估。"
            ),
            metadata={
                "vague_terms": matched,
                "ask_count": vague_ask_count,
                "block_conclusion": True,
            },
        )

    names = "、".join(f"「{m}」" for m in matched)
    return EdgeCaseResult(
        triggered=True,
        case=EdgeCase.VAGUE_INGREDIENT,
        action=EdgeAction.PROMPT,
        message=(
            f"{names}是笼统的类别名称。备案需要具体成分的 INCI 名称或 CAS 号，"
            f"能否提供完整的成分列表？"
        ),
        metadata={"vague_terms": matched, "ask_count": vague_ask_count},
    )


# ═══════════════════════════════════════════════════════════════════
# 通用：检测用户输入中触发的所有边界场景
# ═══════════════════════════════════════════════════════════════════

def detect_all_edge_cases(
    user_input: str,
    ingredients: Optional[list[str]] = None,
    kb_hit_statuses: Optional[list[str]] = None,
    domestic_or_imported: Optional[str] = None,
    historical_rejection: Optional[str] = None,
    rejection_ask_count: int = 0,
    vague_ask_count: int = 0,
    dosage_form: Optional[str] = None,
) -> list[EdgeCaseResult]:
    """
    一次调用检测所有 7 个边界场景。

    返回所有触发的场景列表。多个场景可同时触发。
    优先级由 refusal_engine 统一决策。
    """
    results: list[EdgeCaseResult] = []

    # 5.1.1 成分灰色地带
    r = detect_grey_area_ingredients(ingredients or [], kb_hit_statuses)
    if r.triggered:
        results.append(r)

    # 5.1.3 进口未声明
    r = detect_import_undeclared(user_input, domestic_or_imported)
    if r.triggered:
        results.append(r)

    # 5.1.4 退单隐瞒
    r = detect_rejection_history(user_input, historical_rejection, rejection_ask_count)
    if r.triggered:
        results.append(r)

    # 5.1.5 套装
    r = detect_bundle_product(
        user_input, dosage_form,
        len(ingredients) if ingredients else 0,
    )
    if r.triggered:
        results.append(r)

    # 5.1.6 先上市
    r = detect_prior_market(user_input)
    if r.triggered:
        results.append(r)

    # 5.1.7 成分模糊
    r = detect_vague_ingredients(ingredients or [], vague_ask_count)
    if r.triggered:
        results.append(r)

    return results
