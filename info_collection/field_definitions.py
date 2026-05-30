"""
F2 信息采集 — 字段定义、校验规则、采集策略。

6 必采字段 + 4 选采字段的完整 Schema。
每个字段定义了：中文标签、采集优先级、追问话术、有效值域。
"""

from dataclasses import dataclass, field
from typing import Optional, Callable

# ═══════════════════════════════════════════════════════════════════
# 字段 Schema 定义
# ═══════════════════════════════════════════════════════════════════

@dataclass
class FieldDef:
    key: str                        # 变量名
    label: str                      # 中文标签
    required: bool                  # 是否必采
    priority: int                   # 采集优先级（1最高）
    prompt: str                     # 追问话术
    prompt_short: str               # 简短追问（已问过一轮后）
    valid_values: Optional[set[str]] = None   # 有效值域（None=不限制）
    validator: Optional[Callable] = None      # 自定义校验函数
    examples: list[str] = field(default_factory=list)  # 有效示例
    hint: str = ""                  # 填写提示


# ── 剂型校验 ──

VALID_DOSAGE_FORMS: set[str] = {
    "液体", "凝胶", "喷雾", "湿巾", "片剂", "粉剂", "膏霜", "气雾"
}

def validate_dosage_form(value: str) -> tuple[bool, str]:
    """校验剂型值是否有效。返回 (是否有效, 错误提示)"""
    if not value or not value.strip():
        return False, "剂型不能为空"
    v = value.strip()
    if v in VALID_DOSAGE_FORMS:
        return True, ""
    if v in ("液", "水", "水剂", "液剂"):
        return True, ""  # accept synonyms, normalize later
    hint = f"有效剂型：{' / '.join(sorted(VALID_DOSAGE_FORMS))}。当前输入「{v}」不在标准列表中。"
    return False, hint


# ── 产地校验 ──

VALID_ORIGINS: set[str] = {"国产", "进口"}


# ── 客户类型校验 ──

VALID_CUSTOMER_TYPES: set[str] = {"品牌方", "代工厂", "中介", "贸易商", "其他"}


# ── 完整字段定义 ──

FIELD_DEFINITIONS: dict[str, FieldDef] = {
    "product_name": FieldDef(
        key="product_name",
        label="产品名称",
        required=True,
        priority=1,
        prompt="请问您的产品叫什么名字？（可以是品牌名+产品名，如「XX免洗洗手液」）",
        prompt_short="产品名称是什么？",
        examples=["免洗洗手液", "XX牌消毒喷雾", "次氯酸消毒液"],
        hint="品牌名 + 产品名",
    ),
    "dosage_form": FieldDef(
        key="dosage_form",
        label="剂型",
        required=True,
        priority=2,
        prompt="产品是什么剂型？（液体 / 凝胶 / 喷雾 / 湿巾 / 片剂 / 粉剂 / 膏霜 / 气雾）",
        prompt_short="什么剂型？",
        valid_values=VALID_DOSAGE_FORMS,
        validator=validate_dosage_form,
        examples=["液体", "凝胶", "喷雾", "湿巾", "片剂"],
        hint="从标准列表中选择",
    ),
    "main_ingredients": FieldDef(
        key="main_ingredients",
        label="核心成分",
        required=True,
        priority=3,
        prompt=(
            "请提供产品的核心成分列表。备案需要具体成分的 INCI 名称或 CAS 号，"
            "例如：酒精（75%）、苯扎氯铵、甘油。"
        ),
        prompt_short="核心成分有哪些？（INCI名称或CAS号）",
        examples=["酒精（75%）、甘油、卡波姆", "次氯酸钠（5%）、水"],
        hint="INCI 名称或 CAS 号，多个成分用逗号或顿号分隔",
    ),
    "target_claims": FieldDef(
        key="target_claims",
        label="宣称功效",
        required=True,
        priority=4,
        prompt="产品的主要宣称功效是什么？（消毒 / 抑菌 / 抗菌 / 清洁 / 除味 / 其他）",
        prompt_short="主打什么功效？",
        examples=["抑菌", "消毒、清洁", "抗菌、除味"],
        hint="可多选，如「消毒+抑菌」",
    ),
    "domestic_or_imported": FieldDef(
        key="domestic_or_imported",
        label="产地",
        required=True,
        priority=5,
        prompt="产品是国产还是进口？",
        prompt_short="国产还是进口？",
        valid_values=VALID_ORIGINS,
        examples=["国产", "进口"],
        hint="国产 / 进口",
    ),
    "customer_type": FieldDef(
        key="customer_type",
        label="您的角色",
        required=True,
        priority=6,
        prompt="您是品牌方、代工厂、中介、贸易商还是其他？",
        prompt_short="您是品牌方还是代工厂？",
        valid_values=VALID_CUSTOMER_TYPES,
        examples=["品牌方", "代工厂", "中介"],
        hint="品牌方 / 代工厂 / 中介 / 贸易商 / 其他",
    ),
    # ── 选采字段 ──
    "usage_scenarios": FieldDef(
        key="usage_scenarios",
        label="使用场景",
        required=False,
        priority=7,
        prompt="产品主要用在什么场景？（医院 / 家庭 / 食品工厂 / 学校 / 其他）",
        prompt_short="使用场景？",
        examples=["家庭", "医院", "食品工厂"],
        hint="可多选",
    ),
    "existing_reports": FieldDef(
        key="existing_reports",
        label="已有检测报告",
        required=False,
        priority=8,
        prompt="产品是否已有检测报告？（如有，后续可减少检测项目）",
        prompt_short="已有检测报告吗？",
        examples=["有", "没有", "部分有"],
        hint="有 / 没有 / 部分有",
    ),
    "historical_rejection": FieldDef(
        key="historical_rejection",
        label="退单历史",
        required=False,
        priority=9,
        prompt="产品之前是否在消字号备案或检测过程中被退回或拒绝过？",
        prompt_short="之前被退过单吗？",
        examples=["没有", "有，因为成分问题"],
        hint="如实回答，了解历史有助于规避问题",
    ),
    "urgency_level": FieldDef(
        key="urgency_level",
        label="紧急程度",
        required=False,
        priority=10,
        prompt="您的时间要求是？（普通 / 加急）",
        prompt_short="普通还是加急？",
        examples=["普通", "加急"],
        hint="普通 / 加急",
    ),
}


# ── 采集优先级排序 ──

COLLECTION_ORDER: list[str] = sorted(
    FIELD_DEFINITIONS.keys(),
    key=lambda k: FIELD_DEFINITIONS[k].priority,
)

REQUIRED_FIELDS: list[str] = [k for k, v in FIELD_DEFINITIONS.items() if v.required]
OPTIONAL_FIELDS: list[str] = [k for k, v in FIELD_DEFINITIONS.items() if not v.required]
