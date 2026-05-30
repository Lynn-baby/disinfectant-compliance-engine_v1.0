"""
Coze Code Node — S4 风险分级（risk_engine.py）

架构位置：三层控制 → 第1层强约束（Code Node 查表，不进LLM）
前置节点：S0 安全扫描 + S1 入口解析 + S2 分类判定 + S3 成分合规
后置节点：S5 检测方案生成

判定逻辑：综合成分合规状态、功效宣称、产地、退单历史、先上市标志、
          KB 表过期、灰色地带成分、模糊宣称等维度，按固定规则输出 R1/R2/R3。

R3 > R2 > R1，触发即停。R3 阻断后续报价流程。

法规依据：
  - 《消毒产品分类目录》风险等级定义
  - 《卫生安全评价规定》(2014)
  - PRD 4.4 风险分级规则表 + 5.1 异常流处理

Coze 兼容性：
  - Python 3.11.3（Coze 运行时版本）
  - 仅用标准库（json + re）
  - 单函数入口 main()
"""

import json as _json

# ═══════════════════════════════════════════════════════════════════
# 诊断信息收集（生产环境可观测性）
# ═══════════════════════════════════════════════════════════════════

_diagnostics: list[str] = []


def _warn(msg: str) -> None:
    """记录诊断警告，最终附加到输出 dict 中。"""
    _diagnostics.append(msg)


def _coerce_bool(value) -> bool:
    """将 Coze 可能字符串化的布尔值转为 Python bool。

    Coze 变量传递层可能将 True/False 序列化为字符串 "true"/"false"。
    Python 中 bool("false") 是 True，会导致误判。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in ("true", "1", "yes"):
            return True
        if lower in ("false", "0", "no", ""):
            return False
        _warn(f"无法识别的布尔值字符串: '{value}'，按 False 处理")
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return False
    _warn(f"无法识别的布尔类型: {type(value).__name__} = {value!r}，按 False 处理")
    return False


# ═══════════════════════════════════════════════════════════════════
# 风险等级与行为定义
# ═══════════════════════════════════════════════════════════════════

RISK_LABELS = {
    "R1": "R1 低风险",
    "R2": "R2 中风险",
    "R3": "R3 高风险",
}

RISK_ENGINE_ACTIONS = {
    "R1": {
        "can_quote": True,
        "can_generate_pdf": True,
        "disclaimer_required": False,
        "human_review_required": False,
        "description": "正常输出检测方案和报价预估",
    },
    "R2": {
        "can_quote": True,
        "can_generate_pdf": True,
        "disclaimer_required": True,
        "human_review_required": False,
        "description": "输出检测方案和报价，追加风险免责声明，建议人工复核",
    },
    "R3": {
        "can_quote": False,
        "can_generate_pdf": False,
        "disclaimer_required": True,
        "human_review_required": True,
        "description": "禁止报价，说明风险原因，强制建议转人工专家",
    },
}


# ═══════════════════════════════════════════════════════════════════
# 触发条件定义（PRD 4.4 表 + 5.1 异常流）
# ═══════════════════════════════════════════════════════════════════

TRIGGER_CONDITIONS = {
    # ── R3 触发条件 ──
    "ingredient_prohibited": {
        "code": "R3-01",
        "label": "含禁用成分",
        "description": "成分在《消毒剂原料清单》禁用列表中",
    },
    "medical_claim": {
        "code": "R3-02",
        "label": "功效含医疗暗示",
        "description": "宣称功效涉及疾病治疗、抗病毒等医疗用途表述",
    },
    "historical_rejection": {
        "code": "R3-03",
        "label": "有退单历史",
        "description": "产品此前在消字号备案或检测中被退回或拒绝",
    },
    "prior_market": {
        "code": "R3-04",
        "label": "先上市后补备案",
        "description": "产品已在市场流通，因举报/抽检/平台要求才来咨询",
    },
    "regulation_circumvention": {
        "code": "R3-05",
        "label": "试图规避监管",
        "description": "用户要求规避备案流程或监管审查",
    },
    # ── R2 触发条件 ──
    "ingredient_unknown": {
        "code": "R2-01",
        "label": "含未收录成分",
        "description": "成分不在GB 38850-2020活性/惰性清单中，法规状态不明确",
    },
    "imported_product": {
        "code": "R2-02",
        "label": "进口产品",
        "description": "进口产品走不同法规路径，需额外材料，风险自动提一级",
    },
    "grey_area_ingredient": {
        "code": "R2-03",
        "label": "含灰色地带成分",
        "description": "含植物提取物、纳米材料、生物酶等法规不明确的成分",
    },
    "vague_claims": {
        "code": "R2-04",
        "label": "功效描述模糊",
        "description": "宣称功效表述边界模糊，可能触及合规边界",
    },
    "kb_table_expired": {
        "code": "R2-05",
        "label": "知识库表过期",
        "description": "判定依据的知识库映射表已超过复核周期，保守提级",
    },
    # ── R1 ──
    "all_clear": {
        "code": "R1-01",
        "label": "常规合规产品",
        "description": "成分在允许清单中，功效合规，国产，无退单历史",
    },
}


# ═══════════════════════════════════════════════════════════════════
# S3 → S4 状态归一化
# ═══════════════════════════════════════════════════════════════════
#
# S3 实际输出的 5 种状态 → S4 风险判定的 3 种简化状态：
#   allowed_active / allowed_inert / water_base  → allowed   (在 GB 38850 清单中)
#   restricted                                    → restricted (在清单但有限量要求)
#   unknown                                       → unknown   (不在任何清单中)
#
# 注：S3 定义了 STATUS_PROHIBITED 但当前实现不产出此状态。
#     GB 38850 是正清单制——不在清单中 = unknown，而非 prohibited。

def _normalize_status(s3_status: str) -> str:
    """将 S3 成分状态归一化为 S4 风险判定用的简化状态。"""
    if s3_status in ("allowed_active", "allowed_inert", "water_base"):
        return "allowed"
    if s3_status == "restricted":
        return "restricted"
    if s3_status == "prohibited":
        return "prohibited"         # 预留：S3 未来产出禁用状态 → R3
    if s3_status == "unknown":
        return "unknown"
    _warn(f"未识别的 S3 成分状态: '{s3_status}'，按 unknown 处理")
    return "unknown"


# ═══════════════════════════════════════════════════════════════════
# 灰色地带成分检测
# ═══════════════════════════════════════════════════════════════════
#
# 当 S3 标记为 unknown 且成分名称匹配以下模式时，触发"灰色地带"而非泛"未收录"。
# PRD 5.1.1：植物提取物、纳米银、生物酶等——法无明文，但业内常见。

GREY_AREA_PATTERNS = [
    "植物提取", "提取物", "植物萃取",
    "纳米",
    "生物酶", "酵素", "酶解",
    "精油", "挥发油",
    "发酵", "菌发酵",
    "中药", "草本", "中草药",
    "壳聚糖", "甲壳素",
    "蜂胶", "蜂蜡", "蜂蜜",
    "芦荟", "绿茶", "茶树",
    "银离子", "铜离子", "锌离子",
    "光触媒", "光催化",
    "负离子", "远红外",
    "肽", "蛋白",
    "微生物", "益生菌",
]


def _detect_grey_area(ingredient_name: str, status: str) -> bool:
    """检测单个成分是否属于灰色地带成分。"""
    if status != "unknown":
        return False
    for pat in GREY_AREA_PATTERNS:
        if pat in ingredient_name:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════
# 模糊宣称检测
# ═══════════════════════════════════════════════════════════════════
#
# PRD 5.1.7：客户用了笼统的描述词，没有具体功效指向。

VAGUE_CLAIMS_PATTERNS = [
    "强效", "速效", "长效",
    "广谱", "光谱",
    "天然", "纯天然", "绿色", "环保",
    "温和", "安全", "无毒", "无害",
    "深层", "深度", "持久",
    "专利配方", "复合成分",
    "进口原料",
]

# 需要额外上下文判断的模式（含技术术语误匹配风险）
VAGUE_CLAIMS_CONTEXTUAL = {
    "高效": ["液相色谱", "色谱法", "检测方法", "分析方法"],
}


def _detect_vague_claims(claims_text: str) -> bool:
    """检测功效宣称文本中是否含模糊表述。

    '高效' 需要上下文判断：'高效液相色谱法' 是标准检测方法，不触发。
    已移除的假阳性模式：'活性成分'（标准化学表述）、'表面活性剂'（标准化学分类）。
    """
    if not claims_text:
        return False
    for pat in VAGUE_CLAIMS_PATTERNS:
        if pat in claims_text:
            return True
    # 上下文模式：仅当不含技术排除词时才触发
    for pat, exclusions in VAGUE_CLAIMS_CONTEXTUAL.items():
        if pat in claims_text:
            if not any(excl in claims_text for excl in exclusions):
                return True
    return False


# ═══════════════════════════════════════════════════════════════════
# 风险判定主函数
# ═══════════════════════════════════════════════════════════════════

def assess_risk(
    ingredient_results: list[dict],
    domestic_or_imported: str = "国产",
    historical_rejection: bool = False,
    medical_keyword_hit: bool = False,
    prior_market_flag: bool = False,
    regulation_circumvention: bool = False,
    kb_table_expired: bool = False,
    target_claims: str = "",
) -> dict:
    """
    综合多维度判定风险等级。

    R3 触发条件（满足任一 → R3，即停不继续）：
      - 含禁用成分（来自 S3 prohibited 状态，当前 S3 未产出）
      - 医疗暗示关键词命中（来自 S0 安全扫描）
      - 有退单历史（来自 S1 问卷）
      - 先上市后补备案（来自 S1 问卷）
      - 试图规避监管（来自 S0 安全扫描）

    R2 触发条件（满足任一且无 R3 → R2）：
      - 含未收录成分（S3 unknown 状态）
      - 进口产品
      - 含灰色地带成分（unknown + 关键词命中）
      - 功效描述模糊（claims 文本关键词命中）
      - KB 映射表过期（独立触发，R1→R2 降级）

    其他 → R1

    返回 dict，包含完整风险判定结果。
    """
    trigger_codes: list[str] = []

    # ── 成分汇总 ──
    allowed_count = 0
    restricted_count = 0
    unknown_count = 0
    prohibited_count = 0
    has_grey = False

    for ing in ingredient_results:
        raw_status = ing.get("status", "unknown")
        norm = _normalize_status(raw_status)
        if norm == "allowed":
            allowed_count += 1
        elif norm == "restricted":
            restricted_count += 1
        elif norm == "prohibited":
            prohibited_count += 1
        elif norm == "unknown":
            unknown_count += 1
            # 同时检测灰色地带
            if _detect_grey_area(ing.get("ingredient", ""), raw_status):
                has_grey = True

    # 模糊宣称检测
    has_vague_claims = _detect_vague_claims(target_claims)

    has_unknown = unknown_count > 0
    is_imported = domestic_or_imported in ("进口",)  # 未来可扩展

    # ── R3 判定（最先检查，一个命中就够）──
    if prohibited_count > 0:
        trigger_codes.append("ingredient_prohibited")
    if medical_keyword_hit:
        trigger_codes.append("medical_claim")
    if historical_rejection:
        trigger_codes.append("historical_rejection")
    if prior_market_flag:
        trigger_codes.append("prior_market")
    if regulation_circumvention:
        trigger_codes.append("regulation_circumvention")

    if trigger_codes:
        return _build_result("R3", trigger_codes, allowed_count, restricted_count, unknown_count, prohibited_count)

    # ── R2 判定 ──
    if has_unknown:
        trigger_codes.append("ingredient_unknown")
    if is_imported:
        trigger_codes.append("imported_product")
    if has_grey:
        trigger_codes.append("grey_area_ingredient")
    if has_vague_claims:
        trigger_codes.append("vague_claims")
    if kb_table_expired:
        # PRD：表过期时 R1→R2 降级，永不放宽。独立于 has_unknown。
        trigger_codes.append("kb_table_expired")

    if trigger_codes:
        return _build_result("R2", trigger_codes, allowed_count, restricted_count, unknown_count, prohibited_count)

    # ── R1 ──
    trigger_codes.append("all_clear")
    return _build_result("R1", trigger_codes, allowed_count, restricted_count, unknown_count, prohibited_count)


def _build_result(
    level: str,
    trigger_codes: list[str],
    allowed_count: int,
    restricted_count: int,
    unknown_count: int,
    prohibited_count: int = 0,
) -> dict:
    """构建风险判定结果 dict。"""
    labels = []
    details = []
    for code in trigger_codes:
        tc = TRIGGER_CONDITIONS.get(code)
        if tc:
            labels.append(tc["label"])
            details.append(tc["description"])
        else:
            _warn(f"未注册的触发码: '{code}' — 可能是 typo 或 TRIGGER_CONDITIONS 遗漏")
            labels.append(f"[UNKNOWN:{code}]")
            details.append(f"内部错误：触发码 '{code}' 未注册到 TRIGGER_CONDITIONS")

    if level not in RISK_ENGINE_ACTIONS:
        _warn(f"未识别的风险等级: '{level}'，强制降级为 R3（保守策略）")
        level = "R3"
        trigger_codes.append("system_error")
        labels.append("系统错误")
        details.append("风险等级判定异常，安全降级为 R3")

    action = RISK_ENGINE_ACTIONS[level]

    result = {
        "risk_level": level,
        "risk_label": RISK_LABELS.get(level, level),
        "trigger_codes": trigger_codes,
        "trigger_codes_json": _json.dumps(trigger_codes, ensure_ascii=False),
        "trigger_labels": labels,
        "trigger_labels_json": _json.dumps(labels, ensure_ascii=False),
        "trigger_details": details,
        "trigger_details_json": _json.dumps(details, ensure_ascii=False),
        "can_quote": action["can_quote"],
        "can_generate_pdf": action["can_generate_pdf"],
        "disclaimer_required": action["disclaimer_required"],
        "human_review_required": action["human_review_required"],
        "engine_action": action["description"],
        "ingredient_summary": _json.dumps({
            "allowed": allowed_count,
            "restricted": restricted_count,
            "unknown": unknown_count,
            "prohibited": prohibited_count,
        }, ensure_ascii=False),
        "allowed_count": allowed_count,
        "restricted_count": restricted_count,
        "unknown_count": unknown_count,
        "prohibited_count": prohibited_count,
    }

    # 附加诊断信息（如果有的话）
    if _diagnostics:
        result["diagnostics"] = _json.dumps(_diagnostics, ensure_ascii=False)

    return result


# ═══════════════════════════════════════════════════════════════════
# Coze Code Node 入口
# ═══════════════════════════════════════════════════════════════════

async def main(args) -> dict:
    """Coze Code Node 入口（Python 3.11.3）。

    输入变量（来自 S0/S1/S2/S3）:
        results_json:            string  — S3 输出的逐成分结果 JSON
        domestic_or_imported:    string  — 国产/进口（S1）
        target_claims:           string  — 功效宣称文本（S1）
        medical_keyword_hit:     bool    — S0 安全扫描是否命中医疗关键词
        historical_rejection:    bool    — S1 是否有退单历史
        prior_market_flag:       bool    — S1 是否先上市
        regulation_circumvention: bool   — S0 是否检测到规避监管意图
        kb_table_expired:        bool    — KV 映射表是否已过期

    输出变量:
        risk_level:              string  — R1 / R2 / R3
        risk_label:              string  — 中文标签
        trigger_codes_json:      string  — 触发条件编号 JSON 数组
        trigger_labels_json:     string  — 触发条件中文 JSON 数组
        trigger_details_json:    string  — 触发条件详情 JSON 数组
        can_quote:               bool    — 是否可进报价
        can_generate_pdf:        bool    — 是否可生成 PDF
        disclaimer_required:     bool    — 是否需免责声明
        human_review_required:   bool    — 是否需转人工
        engine_action:           string  — 引擎行为描述
        ingredient_summary:      string  — 成分汇总 JSON
        allowed_count:           int     — 合规成分数
        restricted_count:        int     — 限用成分数
        unknown_count:           int     — 未收录成分数
    """
    global _diagnostics
    _diagnostics = []  # 每次调用清空诊断信息

    # ── 解析输入，处理 Coze args.params vs dict 两种接口 ──
    def _get(key, default=None):
        """安全地从 args.params 或 args dict 获取变量值。"""
        if hasattr(args, 'params') and hasattr(args.params, 'get'):
            return args.params.get(key, default)
        if hasattr(args, 'get'):
            return args.get(key, default)
        raise AttributeError(f"args 类型异常: {type(args).__name__}，无 params 属性也无 get 方法")

    try:
        raw_json = _get("results_json", "[]")
        domestic_or_imported = _get("domestic_or_imported", "国产") or ""
        target_claims = _get("target_claims", "") or ""

        medical_keyword_hit = _coerce_bool(_get("medical_keyword_hit", False))
        historical_rejection = _coerce_bool(_get("historical_rejection", False))
        prior_market_flag = _coerce_bool(_get("prior_market_flag", False))
        regulation_circumvention = _coerce_bool(_get("regulation_circumvention", False))
        kb_table_expired = _coerce_bool(_get("kb_table_expired", False))
    except AttributeError as e:
        _warn(f"args 结构异常: {e}")
        return _build_error("S4_ARGS_STRUCTURE_ERROR", str(e))
    except Exception as e:
        _warn(f"输入解析未预期的异常: {type(e).__name__}: {e}")
        return _build_error("S4_INPUT_PARSE_ERROR", str(e))

    # ── 解析 S3 成分结果 ──
    ingredient_results: list[dict] = []
    if isinstance(raw_json, (list, tuple)):
        # Coze 可能直接传递 Python 列表而非 JSON 字符串
        ingredient_results = list(raw_json)
    elif isinstance(raw_json, str):
        if not raw_json.strip():
            ingredient_results = []
        else:
            try:
                parsed = _json.loads(raw_json)
            except _json.JSONDecodeError as e:
                _warn(f"S3 results_json 解析失败: {e.msg} (行 {e.lineno}, 列 {e.colno})")
                return _build_error("S4_S3_PARSE_ERROR",
                    f"无法解析 S3 输出的 results_json: {e.msg}")
            except Exception as e:
                _warn(f"results_json 解析未预期的异常: {type(e).__name__}: {e}")
                return _build_error("S4_S3_PARSE_UNEXPECTED", str(e))
            else:
                if not isinstance(parsed, list):
                    _warn(f"S3 results_json 非数组类型: {type(parsed).__name__}，数据已丢弃")
                    return _build_error("S4_S3_TYPE_ERROR",
                        f"S3 results_json 应为 JSON 数组，实际为 {type(parsed).__name__}")
                ingredient_results = parsed
    else:
        _warn(f"results_json 类型异常: {type(raw_json).__name__}")
        return _build_error("S4_S3_TYPE_ERROR",
            f"results_json 类型异常: {type(raw_json).__name__}")

    # ── 执行风险判定 ──
    return assess_risk(
        ingredient_results=ingredient_results,
        domestic_or_imported=domestic_or_imported,
        historical_rejection=historical_rejection,
        medical_keyword_hit=medical_keyword_hit,
        prior_market_flag=prior_market_flag,
        regulation_circumvention=regulation_circumvention,
        kb_table_expired=kb_table_expired,
        target_claims=target_claims,
    )


def _build_error(code: str, message: str) -> dict:
    """构建错误响应（保守降级：强制 R3 + 转人工 + 禁报价）。"""
    return {
        "risk_level": "R3",
        "risk_label": "R3 高风险 (系统错误)",
        "trigger_codes": ["system_error"],
        "trigger_codes_json": _json.dumps(["system_error"], ensure_ascii=False),
        "trigger_labels": ["系统内部错误"],
        "trigger_labels_json": _json.dumps(["系统内部错误"], ensure_ascii=False),
        "trigger_details": [f"错误码: {code} — {message}"],
        "trigger_details_json": _json.dumps([f"错误码: {code} — {message}"], ensure_ascii=False),
        "can_quote": False,
        "can_generate_pdf": False,
        "disclaimer_required": True,
        "human_review_required": True,
        "engine_action": f"风险引擎内部错误（{code}），安全降级为 R3。请联系技术支持。",
        "ingredient_summary": _json.dumps({"allowed": 0, "restricted": 0, "unknown": 0, "prohibited": 0}, ensure_ascii=False),
        "allowed_count": 0,
        "restricted_count": 0,
        "unknown_count": 0,
        "prohibited_count": 0,
        "diagnostics": _json.dumps(_diagnostics, ensure_ascii=False),
    }
