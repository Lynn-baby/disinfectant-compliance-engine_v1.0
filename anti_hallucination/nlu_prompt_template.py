"""
Layer 2 强约束 — 小模型 NLU 实体抽取 Prompt 模板。

用途：将用户自然语言输入转为结构化 JSON。
模型：GLM-4-flash（小模型，成本低、延迟低，抽取任务足够好）。
频率：每轮对话都调用。

设计原则：
- 提取不到的字段填 null，严禁编造
- 注入当前已采集字段 + 缺失字段列表，引导模型优先补齐缺失信息
- 幻觉风险由下一阶段 Gate 检查兜底——实体抽错了 Gate 会发现不合理值
"""


def build_nlu_system_prompt() -> str:
    """NLU 抽取的系统 Prompt（静态部分，可缓存）"""
    return """你是一个信息提取助手。你的唯一任务是从用户输入中提取结构化字段。

【核心规则】
1. 只提取用户在输入中明确提到的信息，不要推断、不要编造
2. 提取不到的字段填 null
3. 不要改写或修饰用户原话，保持原样
4. 成分列表用数组格式，每项保持用户原始表述
5. 注意区分"消毒"和"抑菌/抗菌"——用户说"抗菌"不要填成"消毒"

【剂型识别指南】
- 液体/液剂/水剂 → "液体"
- 凝胶/啫喱/凝胶剂 → "凝胶"
- 喷雾/喷剂/气雾剂/气雾 → "喷雾"或"气雾"（瓶装按压式→"喷雾"，压力罐装→"气雾"）
- 湿巾/湿纸巾/擦拭巾 → "湿巾"
- 片剂/泡腾片 → "片剂"
- 粉剂/颗粒 → "粉剂"
- 膏霜/乳霜/乳液 → "膏霜"
- 用户未提及剂型 → null

【功效宣称识别指南】
- "消毒"/"杀菌"/"灭菌" → 属于消毒类宣称
- "抑菌"/"抗菌" → 属于抑菌类宣称
- "清洁"/"去污" → 属于清洁类宣称
- "治疗XX"/"抗病毒"/"杀新冠病毒"/"抑制XX菌" → 注意：可能涉及医疗暗示
- 用户未提及功效 → null

【输出格式】
只输出一个 JSON 对象，不要任何其他文字：
{
  "product_name": "字符串或 null",
  "dosage_form": "字符串或 null",
  "main_ingredients": ["字符串数组或空数组"],
  "target_claims": ["字符串数组或空数组"],
  "domestic_or_imported": "字符串或 null",
  "customer_type": "字符串或 null",
  "usage_scenarios": "字符串或 null",
  "existing_reports": "字符串或 null",
  "historical_rejection": "字符串或 null",
  "urgency_level": "字符串或 null"
}"""


def build_nlu_user_prompt(
    user_message: str,
    filled_fields: dict[str, str],
    missing_fields: list[str],
) -> str:
    """
    构建 NLU 抽取的用户 Prompt（动态部分，每轮拼装）。

    Args:
        user_message: 用户本轮原始输入
        filled_fields: 已累积的字段 {field_name: value}，仅含已填充的
        missing_fields: 当前缺失的必采字段列表
    """
    parts: list[str] = []

    # 当前已采集的字段（让模型知道上下文）
    if filled_fields:
        filled_lines = [f"  - {k}: {v}" for k, v in filled_fields.items()]
        parts.append(f"【已采集信息】\n" + "\n".join(filled_lines))
    else:
        parts.append("【已采集信息】\n  （暂无，这是第一轮对话）")

    # 当前缺失的字段（引导模型优先关注）
    if missing_fields:
        field_names = {
            "product_name": "产品名称",
            "dosage_form": "剂型（液体/凝胶/喷雾/湿巾/片剂/其他）",
            "main_ingredients": "核心成分列表",
            "target_claims": "宣称功效",
            "domestic_or_imported": "产地（国产/进口）",
            "customer_type": "您的角色（品牌方/代工厂/中介/其他）",
        }
        labels = [field_names.get(f, f) for f in missing_fields]
        parts.append(f"【还需采集】{'、'.join(labels)}")
    else:
        parts.append("【还需采集】（信息已齐全）")

    # 用户输入
    parts.append(f"【用户输入】\n{user_message}")

    return "\n\n".join(parts)


def parse_nlu_output(raw_output: str) -> dict:
    """
    解析小模型输出的 JSON，做基本合法性校验。

    返回标准化后的 dict，解析失败返回空 dict。
    不做值域校验——那是 Gate 检查的职责。
    """
    import json
    import re

    try:
        # 尝试直接解析
        result = json.loads(raw_output.strip())
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON 块
        match = re.search(r'\{[^{}]*\}', raw_output, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                return {}
        else:
            return {}

    # 标准化：确保所有字段存在，null 的字段保持 null
    expected_fields = [
        "product_name", "dosage_form", "main_ingredients",
        "target_claims", "domestic_or_imported", "customer_type",
        "usage_scenarios", "existing_reports", "historical_rejection",
        "urgency_level",
    ]
    for field in expected_fields:
        if field not in result:
            result[field] = None

    # main_ingredients 和 target_claims 标准化为列表
    for list_field in ["main_ingredients", "target_claims"]:
        val = result.get(list_field)
        if val is None:
            result[list_field] = []
        elif isinstance(val, str):
            result[list_field] = [val]
        elif not isinstance(val, list):
            result[list_field] = []

    return result
