"""
Coze Code Node — S2 产品分类判定（classification_decision.py）

架构位置：三层控制 → 第1层强约束（Code Node 硬编码决策树，不进LLM）
前置节点：S1 入口解析（entry_merge.py）→ ready=True 后进入
后置节点：S3 成分合规检查

分类逻辑：5步决策树，纯字符串子串匹配，每步命中直接返回不继续判断。
         关键词按风险从高到低排列（第一类 > 第二类 > 第三类）。

Coze 兼容性：
  - Python 3.11.3（Coze 运行时版本）
  - 仅用标准库
  - 单函数入口 main()
  - 输入: args.params 从 S1 输出的结构化字段
  - 输出: category, sub_type, is_classified, matched_keywords,
          classification_step, basis, error_message
"""

# ═══════════════════════════════════════════════════════════════
# 分类决策树
# ═══════════════════════════════════════════════════════════════
#
# 设计原则：
#   - 关键词按风险从高到低排列（第一类 > 第二类 > 第三类）
#   - Step 1（第一类）仅搜索 product_name，不搜索 target_claims。
#     理由：第一类是高风险产品（医疗器械消毒/灭菌），必须通过产品名称本身
#     判定，不能因为宣称功效中含某个关键词就升级风险等级。
#   - Step 2-3 搜索 product_name + target_claims。
#   - Step 2 消毒剂/消毒器械/抗抑菌制剂为并列子类型，非优先级关系。
#     同时命中不同子类型关键词 → needs_review=True 转人工确认。
#   - 每步内关键词按长度降序匹配，长词优先（如"消毒器械"先于"消毒"）。
#   - 短关键词是已命中长关键词的子串时不计为独立匹配（如"消毒"⊂"消毒机"）。
#   - "keyword|sub_type" 格式支持同一步内不同子类型。
#
# 法规依据：
#   - 《消毒产品分类目录》三类风险等级定义
#   - 《卫生安全评价规定》(2014) 第二条："同一产品涉及不同类别时，
#     以较高风险类别管理"

STEPS = [
    # ── Step 1: 医疗器械/灭菌/皮肤黏膜 → 第一类 ──
    #  仅搜索 product_name，不搜索 target_claims。
    #  2026-05-28 修正：移除裸词，仅搜 product_name。
    {
        "label": "Step1",
        "category": "第一类",
        "default_sub_type": None,
        "search_product_name_only": True,
        "resolve_conflict": False,
        "basis": (
            "依据《消毒产品分类目录》，具有较高风险，需严格管理。"
            "属于第一类消毒产品（用于医疗器械的高水平消毒剂/灭菌剂/皮肤黏膜消毒剂等）。"
        ),
        "keywords": [
            "医疗器械", "手术器械", "内窥镜", "透析", "植入物",
            "灭菌", "灭菌器械", "灭菌剂", "灭菌效果",
            "高水平消毒", "皮肤黏膜", "黏膜消毒", "伤口消毒",
            "生物指示物", "化学指示物", "灭菌指示物",
        ],
    },
    # ── Step 2: 消毒剂/消毒器械/抗（抑）菌制剂 → 第二类 ──
    #  三类子类型并列，不是优先级关系。同一产品可能同时匹配多类关键词。
    #  resolve_conflict: 收集全部命中关键词，无冲突→直接定 sub_type，
    #  消毒剂+抗抑菌制剂同时命中→needs_review=True 转人工。
    {
        "label": "Step2",
        "category": "第二类",
        "default_sub_type": "",
        "search_product_name_only": False,
        "resolve_conflict": True,
        "basis": (
            "依据《消毒产品分类目录》，属于第二类消毒产品（中度风险，加强管理）。"
        ),
        "keywords": [
            # 消毒器械
            "消毒器械|消毒器械",
            "消毒机|消毒器械",
            "消毒器|消毒器械",
            "消毒仪|消毒器械",
            # 消毒剂
            "消毒喷雾|消毒剂",
            "消毒液|消毒剂",
            "消毒剂|消毒剂",
            "消毒片|消毒剂",
            "消毒粉|消毒剂",
            "杀菌|消毒剂",
            "杀灭率|消毒剂",
            "灭活|消毒剂",
            "杀灭|消毒剂",
            "消毒|消毒剂",  # 裸词放最后
            # 抗（抑）菌制剂
            "抗菌制剂|抗抑菌制剂",
            "抑菌制剂|抗抑菌制剂",
            "抗（抑）菌|抗抑菌制剂",
            "抗抑菌|抗抑菌制剂",
            "抗菌洗液|抗抑菌制剂",
            "抑菌洗手液|抗抑菌制剂",
            "抗菌洗手液|抗抑菌制剂",
            "抗菌喷雾|抗抑菌制剂",
            "抑菌喷雾|抗抑菌制剂",
            "抗菌凝胶|抗抑菌制剂",
            "抑菌凝胶|抗抑菌制剂",
            "抗菌|抗抑菌制剂",
            "抑菌|抗抑菌制剂",
        ],
    },
    # ── Step 3: 卫生用品 → 第三类 ──
    {
        "label": "Step3",
        "category": "第三类",
        "default_sub_type": "卫生用品",
        "search_product_name_only": False,
        "resolve_conflict": False,
        "basis": (
            "依据《消毒产品分类目录》，属于第三类消毒产品（较低风险，常规管理）— "
            "除抗（抑）菌制剂外的卫生用品。"
        ),
        "keywords": [
            "卫生巾", "卫生护垫", "纸尿裤", "纸尿片", "尿不湿",
            "湿巾", "卫生湿巾", "纸巾", "棉柔巾", "洗脸巾",
            "化妆棉", "棉签", "棉棒", "口罩", "手套",
            "一次性", "卫生用品",
        ],
    },
]

# ── Step 4 剂型兜底映射 ──
DOSAGE_FORM_FALLBACK = {
    "湿巾": {
        "category": "第三类",
        "sub_type": "卫生用品",
        "basis": (
            "依据《消毒产品分类目录》，剂型为湿巾且未命中消毒/抑菌关键词，"
            "归入第三类卫生用品。"
        ),
    },
}

# ═══════════════════════════════════════════════════════════════
# Phase 0: 命名规范前置校验（卫生部《健康相关产品命名规定》）
# ═══════════════════════════════════════════════════════════════
#
# 第四条：产品名称须为「商标名+通用名+属性名」三段式结构，三者缺一不可
# 第五条第三款：属性名应使用表明产品客观形态的词语
# 第八条：不得使用绝对化词语、治疗暗示、外文字母

# ── 禁用词：绝对化词语（第八条）──
FORBIDDEN_CLAIM_WORDS = (
    "特效", "高效", "奇效", "广谱", "第×代", "第一代", "第二代", "第三代",
    "最强", "顶级", "最好", "100%", "百分百", "绝对",
)

# ── 属性名后缀（第五条第三款）──
# 按长度降序，长词优先，避免"洗手液"被"液"截断
ATTRIBUTE_SUFFIXES = sorted([
    "泡腾片", "气雾剂",
    "洗手液", "喷雾", "凝胶", "湿巾", "洗液", "棉片",
    "液", "片", "粉", "膏", "乳", "霜", "皂", "巾", "剂", "水",
], key=lambda x: -len(x))

# ── 功能性开头词：名称以这些词开头 → 缺商标名 ──
FUNCTIONAL_STARTS = (
    "消毒", "抗菌", "抑菌", "杀菌", "灭菌", "除菌",
    "医用", "医疗", "一次性", "卫生", "清洁",
)

# ── 外文字母检测（第八条）──
# 匹配非型号的英文/拼音/符号（简单版：检测ASCII字母）
import re
_FOREIGN_LETTER_RE = re.compile(r'[a-zA-Z]{2,}')


def classify_product(
    product_name: str,
    target_claims: str,
    dosage_form: str,
) -> dict:
    """
    执行 5 步分类决策树。

    输入:
        product_name:   产品名称（S1 输出）
        target_claims:  宣称功效（S1 输出）
        dosage_form:    剂型（S1 输出）

    返回:
        category:              "第一类" | "第二类" | "第三类" | "未分类"
        sub_type:              第二类子类型，冲突时为 None
        is_classified:         是否成功分类
        needs_review:          是否需要人工复核（子类型冲突时 True）
        matched_keywords:      命中的关键词列表
        classification_step:   命中的步骤（Step1~Step4）
        basis:                 法规依据文本
        error_message:         需要人工介入时的提示信息
    """
    # 预处理各搜索文本
    pn = product_name.lower().replace(" ", "").replace("　", "")
    tc = target_claims.lower().replace(" ", "").replace("　", "")
    combined = f"{pn} {tc}"

    # ── Phase 0: 命名规范前置校验 ──
    # 在关键词分类之前拦截不合规名称，避免将其误分类
    name = product_name.strip()

    # 1. 禁用词检测
    name_has_forbidden = any(w in name for w in FORBIDDEN_CLAIM_WORDS)
    name_has_foreign = bool(_FOREIGN_LETTER_RE.search(name))

    if name_has_forbidden or name_has_foreign:
        hints = ["产品名称不符合《健康相关产品命名规定》第八条。请修正后重新提交："]
        n = 1
        if name_has_forbidden:
            hints.append(f"{n}) 不得使用绝对化词语（如：特效、高效、广谱、第×代、100%等）；")
            n += 1
        if name_has_foreign:
            hints.append(f"{n}) 不得使用外文字母（注册商标除外）；")
        return {
            "category": "未分类", "sub_type": None,
            "is_classified": False, "needs_review": False,
            "matched_keywords": [], "classification_step": "信息不足",
            "basis": "依据卫生部《健康相关产品命名规定》第八条，产品名称不得使用绝对化词语、外文字母。",
            "error_message": "\n".join(hints),
        }

    # 2. 三段式结构检测（第四条）
    # 属性名 → 名称是否以已知属性名结尾
    has_attribute = any(name.endswith(suffix) for suffix in ATTRIBUTE_SUFFIXES)
    # 商标名 → 名称是否以功能性描述词开头（缺商标名）
    starts_with_functional = any(name.startswith(w) for w in FUNCTIONAL_STARTS)

    if not has_attribute or starts_with_functional:
        hints = ["产品名称不完整，请按「商标名+通用名+属性名」三段式格式补全："]
        n = 1
        if starts_with_functional:
            hints.append(f'{n}) 缺少商标名——请在产品名称前加上品牌名（如无品牌，可用「xx牌」代替）；')
            n += 1
        if not has_attribute:
            hints.append(f"{n}) 缺少属性名——请在名称末尾补充产品剂型（如：消毒液、抑菌凝胶、湿巾等）；")
        hints.append("示例：威露士消毒液（商标名=威露士，通用名=消毒，属性名=液）")
        return {
            "category": "未分类", "sub_type": None,
            "is_classified": False, "needs_review": False,
            "matched_keywords": [], "classification_step": "信息不足",
            "basis": "依据卫生部《健康相关产品命名规定》第四条，产品名称须为商标名+通用名+属性名三段式结构。",
            "error_message": "\n".join(hints),
        }

    # 3. 过短/占位符
    name_vague = (
        len(name) <= 2
        or name in ("新产品", "样品", "测试", "未知", "待定", "未命名", "新品")
    )
    if name_vague:
        return {
            "category": "未分类", "sub_type": None,
            "is_classified": False, "needs_review": False,
            "matched_keywords": [], "classification_step": "信息不足",
            "basis": "依据卫生部《健康相关产品命名规定》第四条，产品名称须为商标名+通用名+属性名三段式结构。",
            "error_message": "产品名称过短或为占位符，请提供完整的「商标名+通用名+属性名」格式名称（如：威露士消毒液）。",
        }

    # Step 1-3: 关键词子串匹配（按优先级顺序，每步内按长度降序）
    for step in STEPS:
        # Step 1 仅搜 product_name，Step 2-3 搜 product_name + target_claims
        search_text = pn if step.get("search_product_name_only") else combined

        # 解析关键词：支持 "keyword" 和 "keyword|sub_type" 两种格式
        parsed = []
        for kw in step["keywords"]:
            if "|" in kw:
                keyword, sub_type = kw.split("|", 1)
                parsed.append((keyword, sub_type))
            else:
                parsed.append((kw, step["default_sub_type"]))
        # 按长度降序：长关键词优先匹配（如"消毒器械"先于"消毒"）
        parsed.sort(key=lambda x: len(x[0]), reverse=True)

        if step.get("resolve_conflict"):
            # 收集全部命中关键词及其 sub_type，检测子类型冲突
            matches = []
            seen_sub_types = set()
            for keyword, sub_type in parsed:
                if keyword in search_text:
                    # 短关键词是已命中长关键词的子串时跳过
                    # （如"消毒"⊂"消毒机"，不应计为独立冲突）
                    if any(keyword in m and keyword != m for m in matches):
                        continue
                    matches.append(keyword)
                    seen_sub_types.add(sub_type)
            if matches:
                sub_types = [s for s in seen_sub_types if s]  # 排除空字符串
                if len(sub_types) == 1:
                    return {
                        "category": step["category"],
                        "sub_type": sub_types[0],
                        "is_classified": True,
                        "needs_review": False,
                        "matched_keywords": matches,
                        "classification_step": step["label"],
                        "basis": step["basis"],
                        "error_message": "",
                    }
                else:
                    return {
                        "category": step["category"],
                        "sub_type": None,
                        "is_classified": True,
                        "needs_review": True,
                        "matched_keywords": matches,
                        "classification_step": step["label"],
                        "basis": step["basis"],
                        "error_message": (
                            f"产品同时匹配{'、'.join(sub_types)}关键词"
                            f"（{'、'.join(matches)}），需人工确认子类型。"
                        ),
                    }
        else:
            for keyword, sub_type in parsed:
                if keyword in search_text:
                    return {
                        "category": step["category"],
                        "sub_type": sub_type,
                        "is_classified": True,
                        "needs_review": False,
                        "matched_keywords": [keyword],
                        "classification_step": step["label"],
                        "basis": step["basis"],
                        "error_message": "",
                    }

    # Step 4: 剂型兜底
    df = dosage_form.strip()
    if df in DOSAGE_FORM_FALLBACK:
        fb = DOSAGE_FORM_FALLBACK[df]
        return {
            "category": fb["category"],
            "sub_type": fb["sub_type"],
            "is_classified": True,
            "needs_review": False,
            "matched_keywords": [],
            "classification_step": "Step4",
            "basis": fb["basis"],
            "error_message": "",
        }

    # ── 确实无法分类：信息充足但关键词和剂型均未命中，转人工 ──
    return {
        "category": "未分类",
        "sub_type": None,
        "is_classified": False,
        "needs_review": True,
        "matched_keywords": [],
        "classification_step": "未分类",
        "basis": "",
        "error_message": (
            "您描述的产品暂无法自动分类，已转人工确认。"
            "可能原因：产品不属于消字号管辖范围，或宣称功效描述不够明确。"
        ),
    }


async def main(args) -> dict:
    """
    Coze Code Node 入口（Python 3.11.3 / Coze 当前标准格式）。

    Coze 输入变量（来自 S1 entry_merge 输出）:
        product_name:     string
        target_claims:    string
        dosage_form:      string

    Coze 输出变量（需在节点 UI 中配置为完全一致的字段名）:
        category:              string  — "第一类"/"第二类"/"第三类"/"未分类"
        sub_type:              string  — "消毒剂"/"抗抑菌制剂"/"消毒器械"/"卫生用品"/""
        is_classified:         bool    — 是否成功分类
        needs_review:          bool    — 是否需要人工复核
        matched_keywords:      string  — 命中的关键词（多个用"、"连接）
        classification_step:   string  — 命中的步骤
        basis:                 string  — 法规依据
        error_message:         string  — 未分类/需复核时的提示
    """
    # Coze 标准：通过 args.params 读取
    try:
        product_name = args.params.get("product_name", "") if hasattr(args, "params") else args.get("product_name", "")
        target_claims = args.params.get("target_claims", "") if hasattr(args, "params") else args.get("target_claims", "")
        dosage_form = args.params.get("dosage_form", "") if hasattr(args, "params") else args.get("dosage_form", "")
    except Exception:
        product_name = ""
        target_claims = ""
        dosage_form = ""

    # 前置条件检查：product_name + dosage_form 缺一不可（对应 PRD 4.2 S2 前置条件）
    if not product_name.strip() or not dosage_form.strip():
        return {
            "category": "未分类",
            "sub_type": "",
            "is_classified": False,
            "needs_review": True,
            "matched_keywords": "",
            "classification_step": "",
            "basis": "",
            "error_message": "产品名称或剂型缺失，无法执行分类判定。请先完成信息采集（S1）。",
        }

    result = classify_product(product_name, target_claims, dosage_form)

    # 将列表字段转为 Coze 友好格式（string）
    return {
        "product_category": result["category"],
        "sub_type": result["sub_type"] or "",
        "is_classified": result["is_classified"],
        "needs_review": result["needs_review"],
        "matched_keywords": "、".join(result["matched_keywords"]),
        "classification_step": result["classification_step"],
        "basis": result["basis"],
        "error_message": result["error_message"],
    }
