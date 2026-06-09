"""
Coze Code Node — S6 报价预估（s6_pricing.py）

架构位置：三层控制 → 第1层强约束（Code Node 查表+算价，不进LLM）
前置节点：S5 检测方案生成（test_items_json）
后置节点：S7 预审摘要生成（summary_generator.py）

定价逻辑：
  1. 解析 S5 输出的检测项列表（code→单价映射表命中）
  2. 标准总价 = Σ(各项单价)
  3. 客户折扣（品牌方 85折 / 代工厂 9折 / 中介 95折 / 其他 原价）
  4. 加急附加：urgency_level=="加急" → ×1.3
  5. 税：6% 增值税
  6. 未知项：不在映射表中的检测项收集到 unknown_items

规则依据：
  - KB 参考数据：`coze_workflow/kb_upload/02_检测项目与报价.md`
  - 价格取区间中值，实际以正式合同为准
  - 加急服务加收 30%，周期缩短约 30%

Coze 兼容性：
  - Python 3.11.3（Coze 运行时版本）
  - 仅用标准库
  - 单函数入口 main()
"""

import json as _json

# ═══════════════════════════════════════════════════════════════
# 诊断信息收集（生产环境可观测性）
# ═══════════════════════════════════════════════════════════════

_diagnostics: list[str] = []


def _warn(msg: str) -> None:
    """记录诊断警告，最终附加到输出 dict 中。"""
    _diagnostics.append(msg)


def _get(args, key, default=None):
    """安全地从 args.params 或 args dict 获取变量值。

    Coze 运行时传入的 args 对象有 .params 属性（Namespace），
    本地测试时通常直接传 dict。此函数兼容两种接口。
    """
    if hasattr(args, 'params') and hasattr(args.params, 'get'):
        return args.params.get(key, default)
    if hasattr(args, 'get'):
        return args.get(key, default)
    raise AttributeError(f"args 类型异常: {type(args).__name__}，无 params 属性也无 get 方法")


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


def _build_error(code: str, message: str) -> dict:
    """构建错误响应（保守降级：不报价、不误导）。"""
    return {
        "pricing_table": "",
        "standard_total": 0,
        "subtotal": 0,
        "tax": 0,
        "total": 0,
        "cycle": "N/A",
        "notes": f"报价生成失败（{code}）：{message}",
        "unknown_items_json": "[]",
        "is_priced": False,
        "error_message": f"错误码: {code} — {message}",
        "diagnostics": _json.dumps(_diagnostics, ensure_ascii=False),
    }


# ═══════════════════════════════════════════════════════════════
# 表A：检测项 code → 单价映射（取 KB 区间中值）
# ═══════════════════════════════════════════════════════════════
# code 与 S5 test_plan_generator.py 的 _test_items 严格对齐
# 价格单位：元（人民币）

PRICING_MAP: dict[str, int] = {
    # ── 理化类 ──
    "PHYS_01": 2500,   # 有效成分含量测定（2000-3000 中值）
    "PHYS_02": 750,    # pH值测定（500-1000 中值）
    "PHYS_03": 4000,   # 稳定性试验（3000-5000 中值）
    "PHYS_04": 4000,   # 连续使用稳定性试验
    "PHYS_05": 1500,   # 重金属—铅的测定
    "PHYS_06": 1500,   # 重金属—砷的测定
    "PHYS_07": 1500,   # 重金属—汞的测定
    "PHYS_08": 3000,   # 金属腐蚀性试验（2000-4000 中值）
    "PHYS_09": 2500,   # 残留量检测
    "PHYS_10": 3000,   # 有效成分含量测定（复方）

    # ── 微生物—杀菌 ──
    "MICRO_01": 900,   # 金黄色葡萄球菌定量杀菌试验
    "MICRO_02": 900,   # 大肠杆菌定量杀菌试验
    "MICRO_03": 900,   # 白色念珠菌定量杀菌试验
    "MICRO_04": 900,   # 铜绿假单胞菌定量杀菌试验
    "MICRO_05": 1200,  # 枯草杆菌黑色变种芽胞定量杀菌试验
    "MICRO_06": 1500,  # 龟分枝杆菌定量杀菌试验
    "MICRO_07": 6000,  # 脊髓灰质炎病毒灭活试验（5000-12000 低值，常规病毒）
    "MICRO_08": 7500,  # 白色葡萄球菌空气消毒试验（5000-10000 中值）
    "MICRO_09": 1200,  # 黑曲霉菌定量杀菌试验
    "MICRO_10": 8500,  # 模拟现场试验（5000-12000 中值）
    "MICRO_11": 7500,  # 现场试验（5000-10000 中值）
    "MICRO_12": 5000,  # 灭菌效果鉴定试验

    # ── 微生物—抑菌 ──
    "BACT_01": 3000,   # 大肠杆菌抑菌试验（2000-4000 中值）
    "BACT_02": 3000,   # 金黄色葡萄球菌抑菌试验
    "BACT_03": 3000,   # 白色念珠菌抑菌试验
    "BACT_04": 3000,   # 抗菌性能评价
    "BACT_05": 3000,   # 持效性试验（多次接种）

    # ── 微生物指标 ──
    "MICRO_IDX_01": 800,   # 细菌菌落总数检测
    "MICRO_IDX_02": 800,   # 大肠菌群检测
    "MICRO_IDX_03": 800,   # 真菌菌落总数检测
    "MICRO_IDX_04": 1000,  # 致病性化脓菌检测

    # ── 毒理类 ──
    "TOX_01": 6000,   # 急性经口毒性试验（4000-8000 中值）
    "TOX_02": 6000,   # 急性吸入毒性试验
    "TOX_03": 4000,   # 一次完整皮肤刺激试验（3000-5000 中值）
    "TOX_04": 4000,   # 多次完整皮肤刺激试验
    "TOX_05": 4000,   # 一次破损皮肤刺激试验
    "TOX_06": 5000,   # 眼刺激试验（4000-6000 中值）
    "TOX_07": 6500,   # 阴道粘膜刺激试验（5000-8000 中值）
    "TOX_08": 8000,   # 致突变试验

    # ── 其他 ──
    "OTHER_01": 2000,  # 载体材料相容性
    "OTHER_02": 2000,  # 浸渍液含量测定
    "OTHER_03": 3000,  # 压力容器安全性
    "OTHER_04": 2000,  # 喷雾粒径分布
    "OTHER_05": 3000,  # 全成分分析
    "OTHER_06": 3000,  # 食品安全相关检测（GB 14930.2）
}


# ═══════════════════════════════════════════════════════════════
# 表B：客户类型 → 折扣率
# ═══════════════════════════════════════════════════════════════

DISCOUNT_MAP: dict[str, float] = {
    "品牌方": 0.85,
    "代工厂": 0.90,
    "中介": 0.95,
    "其他": 1.00,
}

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

TAX_RATE = 0.06                # 6% 增值税
URGENCY_SURCHARGE = 1.30       # 加急附加 30%
DEFAULT_CUSTOMER_TYPE = "其他"  # 缺省客户类型（最高折扣率/无折扣）
DEFAULT_URGENCY = "普通"        # 缺省紧急程度


# ═══════════════════════════════════════════════════════════════
# 周期估算
# ═══════════════════════════════════════════════════════════════

def _estimate_cycle(
    item_count: int,
    item_codes: list[str],
    urgency_level: str,
) -> str:
    """根据检测项数量和类型估算参考周期。

    周期估算规则（基于 KB 参考数据）：
      - ≤10 项，无毒理：1-2 个月
      - 11-20 项 或 含毒理：2-4 个月
      - >20 项 或 含高毒理（TOX_02/TOX_08）：3-5 个月
      - 加急：周期 × 0.7（缩短约 30%），追加"（加急）"标记
    """
    has_tox = any(c.startswith("TOX_") for c in item_codes)
    has_heavy_tox = any(c in ("TOX_02", "TOX_08") for c in item_codes)

    if item_count > 20 or has_heavy_tox:
        base_cycle = "3-5 个月"
    elif item_count > 10 or has_tox:
        base_cycle = "2-4 个月"
    else:
        base_cycle = "1-2 个月"

    if urgency_level == "加急":
        return f"{base_cycle}（加急缩短约 30%）"

    return base_cycle


# ═══════════════════════════════════════════════════════════════
# 报价计算
# ═══════════════════════════════════════════════════════════════

def _safe_parse_json(raw, default=None):
    """安全解析 JSON 字符串。"""
    if default is None:
        default = []
    if isinstance(raw, (list, dict)):
        return raw
    if not raw or not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError, ValueError) as e:
        _warn(f"JSON 解析失败: {e}")
        return default


def _build_pricing_table(items: list[dict]) -> str:
    """构建报价明细表（纯文本，含分隔线）。"""
    header = (
        "检测项目               | 单价\n"
        "-----------------------+----------"
    )
    lines = [header]
    for item in items:
        name = item.get("name", "未知项目")
        # 截断过长的项目名
        display_name = name[:21] + "…" if len(name) > 22 else name
        price = item.get("price", 0)
        lines.append(f"{display_name:22} | ¥{price:>8,.0f}")
    return "\n".join(lines)


def _build_notes(urgency_level: str, unknown_items: list[str]) -> str:
    """构建备注文本，组合加急提示和未知项说明。"""
    parts: list[str] = []

    if urgency_level == "加急":
        parts.append("加急服务附加费已计入（+30%），周期为加急周期。")

    if unknown_items:
        unknown_list = "、".join(unknown_items)
        parts.append(
            f"⚠️ 以下检测项目暂无标准报价，需人工确认：\n"
            f"{unknown_list}\n"
            f"已知项目报价如上，请联系销售顾问获取完整报价。"
        )

    if not parts:
        parts.append("以上报价基于标准检测项目，实际费用以正式合同为准。")

    return "\n\n".join(parts)


def generate_pricing(
    test_items: list[dict],
    risk_level: str,
    customer_type: str = "",
    urgency_level: str = "",
) -> dict:
    """根据 S5 检测方案计算报价预估。

    Args:
        test_items: S5 输出的检测项列表，每项含 {"code", "name", "category", "standard"}
        risk_level: 风险等级 R1/R2/R3
        customer_type: 客户类型（品牌方/代工厂/中介/其他），空值时默认"其他"
        urgency_level: 紧急程度（普通/加急），空值时默认"普通"

    Returns:
        pricing_table: 格式化报价明细表
        standard_total: 标准总价（折前）
        subtotal: 折后小计（税前）
        tax: 税额（6%）
        total: 折后总计（含税）
        cycle: 参考周期
        notes: 备注（加急提示 + 未知项）
        unknown_items_json: 未知项 JSON 数组
        is_priced: 是否成功生成报价
    """
    # ── 默认值处理 ──
    if not customer_type or customer_type not in DISCOUNT_MAP:
        if customer_type and customer_type not in DISCOUNT_MAP:
            _warn(f"未识别的 customer_type: '{customer_type}'，使用默认值 '{DEFAULT_CUSTOMER_TYPE}'")
        customer_type = DEFAULT_CUSTOMER_TYPE

    if not urgency_level or urgency_level not in ("普通", "加急"):
        if urgency_level and urgency_level not in ("普通", "加急"):
            _warn(f"未识别的 urgency_level: '{urgency_level}'，使用默认值 '{DEFAULT_URGENCY}'")
        urgency_level = DEFAULT_URGENCY

    # ── R3 阻断（防御纵深，Coze 工作流层面也会分支）──
    if risk_level == "R3":
        _warn("risk_level=R3，禁止报价")
        return {
            "pricing_table": "",
            "standard_total": 0,
            "subtotal": 0,
            "tax": 0,
            "total": 0,
            "cycle": "N/A",
            "notes": "产品存在高风险因素（R3），系统已禁止报价。建议转人工专家评估。",
            "unknown_items_json": "[]",
            "is_priced": False,
        }

    # ── 空检测项检查 ──
    if not test_items:
        return {
            "pricing_table": "",
            "standard_total": 0,
            "subtotal": 0,
            "tax": 0,
            "total": 0,
            "cycle": "N/A",
            "notes": "暂无检测项目，无法生成报价。请确认上游分类和检测方案已完成。",
            "unknown_items_json": "[]",
            "is_priced": False,
        }

    # ── 逐项定价 ──
    priced_items: list[dict] = []
    unknown_items: list[str] = []
    standard_total = 0

    for item in test_items:
        code = item.get("code", "")
        name = item.get("name", "未知项目")
        if code and code in PRICING_MAP:
            price = PRICING_MAP[code]
            priced_items.append({"name": name, "price": price, "code": code})
            standard_total += price
        else:
            unknown_items.append(name)
            _warn(f"无定价映射: code='{code}' name='{name}'")

    # ── 全未知：无法报价 ──
    if not priced_items and unknown_items:
        return {
            "pricing_table": "",
            "standard_total": 0,
            "subtotal": 0,
            "tax": 0,
            "total": 0,
            "cycle": "N/A",
            "notes": (
                f"所有检测项均无标准报价，需人工确认：\n"
                f"{'、'.join(unknown_items)}\n\n"
                f"请联系销售顾问获取报价。"
            ),
            "unknown_items_json": _json.dumps(unknown_items, ensure_ascii=False),
            "is_priced": False,
        }

    # ── 折扣计算 ──
    discount = DISCOUNT_MAP[customer_type]
    subtotal = round(standard_total * discount)

    # ── 加急附加 ──
    if urgency_level == "加急":
        subtotal = round(subtotal * URGENCY_SURCHARGE)

    # ── 税 ──
    tax = round(subtotal * TAX_RATE)
    total = subtotal + tax

    # ── 周期 ──
    item_codes = [item.get("code", "") for item in test_items]
    cycle = _estimate_cycle(len(test_items), item_codes, urgency_level)

    # ── 备注 ──
    unknown_names = [item.get("name", "未知") for item in test_items
                     if not item.get("code") or item.get("code") not in PRICING_MAP]
    notes = _build_notes(urgency_level, unknown_names)

    # ── 报价明细表 ──
    # 添加折扣行到表格末尾（如有）
    all_table_items = list(priced_items)
    if discount < 1.0:
        all_table_items.append({"name": f"客户折扣（{customer_type} {discount:.0%}）", "price": 0})

    pricing_table = _build_pricing_table(all_table_items)

    return {
        "pricing_table": pricing_table,
        "standard_total": standard_total,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "cycle": cycle,
        "notes": notes,
        "unknown_items_json": _json.dumps(unknown_names if unknown_names else unknown_items,
                                          ensure_ascii=False),
        "is_priced": True,
    }


# ═══════════════════════════════════════════════════════════════
# Coze Code Node 入口
# ═══════════════════════════════════════════════════════════════

async def main(args) -> dict:
    """Coze Code Node 入口（Python 3.11.3）。

    Coze 输入变量（来自 S5 检测方案 + S1 客户信息）:
        # S5 输出
        test_items_json:        string  — 检测项 JSON 数组
                                          每项: {"code","name","category","standard"}
        test_total_count:       int     — 检测项总数
        safety_blocked:         bool    — S5 是否安全层拦截
        safety_detail:          string  — 安全拦截详情

        # S4 输出
        risk_level:             string  — R1/R2/R3

        # S1 输出
        customer_type:          string  — 品牌方/代工厂/中介/其他
        urgency_level:          string  — 普通/加急

    Coze 输出变量:
        pricing_table:          string  — 格式化报价明细表
        standard_total:         int     — 标准总价（折前）
        subtotal:               int     — 折后小计（税前）
        tax:                    int     — 税额（6%）
        total:                  int     — 折后总计（含税）
        cycle:                  string  — 参考周期
        notes:                  string  — 备注（加急提示 + 未知项说明）
        unknown_items_json:     string  — 未知项 JSON 数组
        is_priced:              bool    — 报价是否成功生成
    """
    global _diagnostics
    _diagnostics = []

    # ── 解析输入 ──
    try:
        test_items_json = _get(args, "test_items_json", "[]")
        risk_level = str(_get(args, "risk_level", "")).strip()
        customer_type = str(_get(args, "customer_type", "")).strip()
        urgency_level = str(_get(args, "urgency_level", "")).strip()
        safety_blocked_raw = _get(args, "safety_blocked", False)
    except AttributeError as e:
        _warn(f"args 结构异常: {e}")
        return _build_error("S6_ARGS_STRUCTURE_ERROR", str(e))
    except Exception as e:
        _warn(f"输入解析未预期的异常: {type(e).__name__}: {e}")
        return _build_error("S6_INPUT_PARSE_ERROR", str(e))

    # ── 类型转换 ──
    test_items = _safe_parse_json(test_items_json, [])
    if isinstance(test_items, dict):
        test_items = []
        _warn("test_items_json 为对象而非数组，已重置为空列表")

    safety_blocked = _coerce_bool(safety_blocked_raw)

    # ── S5 安全层拦截检查 ──
    if safety_blocked:
        _warn(f"S5 安全层拦截，跳过报价: {_get(args, 'safety_detail', '')}")
        return {
            "pricing_table": "",
            "standard_total": 0,
            "subtotal": 0,
            "tax": 0,
            "total": 0,
            "cycle": "N/A",
            "notes": f"检测方案未生成（安全层拦截），无法报价。{_get(args, 'safety_detail', '')}",
            "unknown_items_json": "[]",
            "is_priced": False,
        }

    # ── 生成报价 ──
    try:
        result = generate_pricing(
            test_items=test_items,
            risk_level=risk_level,
            customer_type=customer_type,
            urgency_level=urgency_level,
        )
    except Exception as e:
        _warn(f"generate_pricing 未预期的异常: {type(e).__name__}: {e}")
        return _build_error("S6_PRICING_ERROR", str(e))

    if _diagnostics:
        result["diagnostics"] = _json.dumps(_diagnostics, ensure_ascii=False)

    return result
