"""
Coze Code Node — 问卷入口解析（安全扫描之后第一个节点）。

用户填写固定模板 → 此节点解析 → 输出结构化字段。

输入:  args.params.structured_text (用户填好的模板文本)
输出:  ready, product_name, dosage_form, main_ingredients,
       target_claims, domestic_or_imported, customer_type,
       urgency_level, error_message

模板格式见 parse_structured_text() 的文档。
"""

import re

REQUIRED = [
    "product_name", "dosage_form", "main_ingredients",
    "target_claims", "domestic_or_imported", "customer_type",
]

VALID_DOSAGE_FORMS = {"液体", "凝胶", "喷雾", "湿巾", "片剂", "粉剂", "膏霜", "气雾"}

DOSAGE_NORMALIZE = {
    "液": "液体", "水": "液体", "水剂": "液体", "液剂": "液体",
    "乳": "膏霜", "霜": "膏霜", "膏": "膏霜", "乳液": "膏霜",
    "气雾": "气雾", "压力罐": "气雾", "喷罐": "气雾",
}

ORIGIN_NORMALIZE = {
    "国内": "国产", "中国": "国产", "本地": "国产",
    "海外": "进口", "国外": "进口", "美国": "进口",
    "日本": "进口", "韩国": "进口", "欧洲": "进口",
}

CUSTOMER_NORMALIZE = {
    "工厂": "代工厂", "代工": "代工厂", "生产商": "代工厂",
    "品牌": "品牌方", "品牌商": "品牌方",
    "贸易": "贸易商", "经销商": "贸易商",
    "个人": "其他", "创业者": "其他",
}


def parse_structured_text(text: str) -> dict:
    """
    解析用户填写的模板。格式示例：

      产品名称：维达免洗洗手液
      剂型：凝胶
      核心成分：酒精（75%）、甘油、卡波姆
      宣称功效：消毒、抑菌
      产地：国产
      您的角色：品牌方
      使用场景：家庭
      已有检测报告：没有
      退单历史：没有
      紧急程度：普通

    规则：
    - 每行一个字段，格式「标签：值」
    - 支持全角冒号（：）和半角冒号（:）
    - 值为"未提供"或"（用户未提供）"视为空
    - 空行和【】开头的标题行自动跳过
    """
    if not text:
        return {}

    LABEL_TO_KEY = {
        "产品名称": "product_name",
        "剂型": "dosage_form",
        "核心成分": "main_ingredients",
        "宣称功效": "target_claims",
        "产地": "domestic_or_imported",
        "您的角色": "customer_type",
        "客户类型": "customer_type",
        "使用场景": "usage_scenarios",
        "已有检测报告": "existing_reports",
        "退单历史": "historical_rejection",
        "紧急程度": "urgency_level",
    }

    result = {}
    pattern = re.compile(r"^\s*(.+?)[：:]\s*(.+?)\s*$")

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("【") or line.startswith("#"):
            continue
        m = pattern.match(line)
        if m:
            label = m.group(1).strip()
            value = m.group(2).strip()
            key = LABEL_TO_KEY.get(label)
            if key and value and value not in ("未提供", "（用户未提供）", "(用户未提供)", ""):
                result[key] = value

    return result


def normalize(fields: dict) -> dict:
    """值域归一化。返回规范化后的字段副本。"""
    out = dict(fields)

    # 剂型
    df = out.get("dosage_form", "").strip()
    if df in DOSAGE_NORMALIZE:
        out["dosage_form"] = DOSAGE_NORMALIZE[df]

    # 产地
    origin = out.get("domestic_or_imported", "").strip()
    if origin in ORIGIN_NORMALIZE:
        out["domestic_or_imported"] = ORIGIN_NORMALIZE[origin]

    # 客户类型
    ct = out.get("customer_type", "").strip()
    if ct in CUSTOMER_NORMALIZE:
        out["customer_type"] = CUSTOMER_NORMALIZE[ct]
    elif ct and ct not in {"品牌方", "代工厂", "中介", "贸易商", "其他"}:
        out["customer_type"] = "其他"

    # 紧急程度
    urgency = out.get("urgency_level", "").strip()
    if not urgency:
        out["urgency_level"] = "普通"
    elif "加急" in urgency or "急" in urgency:
        out["urgency_level"] = "加急"
    else:
        out["urgency_level"] = "普通"

    return out


async def main(args) -> dict:
    """
    入口：解析用户填写的模板 → 输出结构化字段。

    Coze 输入变量:
      structured_text: string  — 用户填写的完整模板文本

    Coze 输出变量:
      ready:            bool
      product_name:     string
      dosage_form:      string
      main_ingredients: string
      target_claims:    string
      domestic_or_imported: string
      customer_type:    string
      urgency_level:    string
      error_message:    string
    """
    params = args.params if hasattr(args, "params") else args
    text = str(params.get("structured_text", "")).strip()

    if not text:
        return {
            "ready": False,
            "error_message": "未收到产品信息。请填写模板后发送。",
            "product_name": "", "dosage_form": "", "main_ingredients": "",
            "target_claims": "", "domestic_or_imported": "", "customer_type": "",
            "urgency_level": "普通",
        }

    # 解析
    fields = parse_structured_text(text)
    fields = normalize(fields)

    # Gate：6 必采字段缺一不可
    missing = [f for f in REQUIRED if not fields.get(f)]
    if missing:
        labels = {
            "product_name": "产品名称", "dosage_form": "剂型",
            "main_ingredients": "核心成分", "target_claims": "宣称功效",
            "domestic_or_imported": "产地", "customer_type": "您的角色",
        }
        missing_cn = [labels.get(f, f) for f in missing]
        return {
            "ready": False,
            "error_message": f"以下必填项未填写：{'、'.join(missing_cn)}。请补充后重新发送。",
            "product_name": fields.get("product_name", ""),
            "dosage_form": fields.get("dosage_form", ""),
            "main_ingredients": fields.get("main_ingredients", ""),
            "target_claims": fields.get("target_claims", ""),
            "domestic_or_imported": fields.get("domestic_or_imported", ""),
            "customer_type": fields.get("customer_type", ""),
            "urgency_level": fields.get("urgency_level", "普通"),
        }

    # 剂型二次校验（归一化后仍不在有效值域 → 提示用户）
    df = fields.get("dosage_form", "")
    if df not in VALID_DOSAGE_FORMS:
        valid_list = "、".join(sorted(VALID_DOSAGE_FORMS))
        return {
            "ready": False,
            "error_message": f"剂型「{df}」不在标准列表中。有效值：{valid_list}。请修改后重新发送。",
            "product_name": fields.get("product_name", ""),
            "dosage_form": df,
            "main_ingredients": fields.get("main_ingredients", ""),
            "target_claims": fields.get("target_claims", ""),
            "domestic_or_imported": fields.get("domestic_or_imported", ""),
            "customer_type": fields.get("customer_type", ""),
            "urgency_level": fields.get("urgency_level", "普通"),
        }

    return {
        "ready": True,
        "error_message": "",
        "product_name": fields.get("product_name", ""),
        "dosage_form": fields.get("dosage_form", ""),
        "main_ingredients": fields.get("main_ingredients", ""),
        "target_claims": fields.get("target_claims", ""),
        "domestic_or_imported": fields.get("domestic_or_imported", ""),
        "customer_type": fields.get("customer_type", ""),
        "urgency_level": fields.get("urgency_level", "普通"),
        "historical_rejection": fields.get("historical_rejection", ""),
        "existing_reports": fields.get("existing_reports", ""),
    }
