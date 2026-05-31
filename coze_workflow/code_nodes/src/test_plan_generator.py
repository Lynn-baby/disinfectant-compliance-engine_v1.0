"""
Coze Code Node — S5 检测方案生成（test_plan_generator.py）

架构位置：三层控制 → 第1层强约束（Code Node 查表，不进LLM）
前置节点：S2 分类判定 → S3 成分合规 → S4 风险分级 → risk_level ≤ R2
后置节点：S6 报价预估

生成逻辑：品类×剂型→基础检测包查表 + 宣称→增量检测查表 + 合并去重排序。
         80%+ 检测需求通过两张映射表覆盖，非标准宣称触发 LLM 辅助搜索。

法规依据：
  - 网上备案通知（国卫办监督函〔2018〕864号）附表2.1：首次备案检验项目清单
  - GB 15979-2002：一次性使用卫生用品卫生标准
  - GB 14930.2-2012：食品安全国家标准 消毒剂
  - GB/T 38499-2020：消毒剂稳定性评价方法
  - 《消毒技术规范》（2002年版）

Coze 兼容性：
  - Python 3.11.3（Coze 运行时版本）
  - 仅用标准库
  - 单函数入口 main()
"""

import re
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
    """构建错误响应（保守降级：禁生成、强制转人工）。"""
    return {
        "test_items_json": "[]",
        "base_count": 0,
        "incremental_count": 0,
        "test_total_count": 0,
        "test_summary": f"检测方案生成失败（{code}）",
        "safety_blocked": False,
        "safety_detail": "",
        "non_standard": "",
        "is_classified": False,
        "error_message": f"错误码: {code} — {message}",
        "diagnostics": _json.dumps(_diagnostics, ensure_ascii=False),
    }


# ═══════════════════════════════════════════════════════════════
# 表A：品类 × 剂型 → 基础检测包
# ═══════════════════════════════════════════════════════════════
# 每条记录: {code, name, category("理化"/"微生物"/"毒理"/"其他"), standard}
# 依据：网上备案通知附表2.1 + 对应产品标准

# ── 检测项定义库 ──
_test_items = {}

def _t(code, name, cat, standard=""):
    """注册检测项。"""
    _test_items[code] = {"code": code, "name": name, "category": cat, "standard": standard}

# 理化类
_t("PHYS_01", "有效成分含量测定", "理化", "《消毒技术规范》（2002年版）")
_t("PHYS_02", "pH值测定", "理化", "GB 15979-2002")
_t("PHYS_03", "稳定性试验（加速+长期）", "理化", "GB/T 38499-2020")
_t("PHYS_04", "连续使用稳定性试验", "理化", "《消毒技术规范》（2002年版）")
_t("PHYS_05", "重金属—铅的测定", "理化", "GB/T 7917.3")
_t("PHYS_06", "重金属—砷的测定", "理化", "GB/T 7917.2")
_t("PHYS_07", "重金属—汞的测定", "理化", "GB/T 7917.1")
_t("PHYS_08", "金属腐蚀性试验", "理化", "GB/T 38498-2020")
_t("PHYS_09", "残留量检测", "理化", "《消毒技术规范》（2002年版）")
_t("PHYS_10", "有效成分含量测定（复方）", "理化", "《消毒技术规范》（2002年版）")

# 微生物—杀菌
_t("MICRO_01", "金黄色葡萄球菌定量杀菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.1")
_t("MICRO_02", "大肠杆菌定量杀菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.2")
_t("MICRO_03", "白色念珠菌定量杀菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.3")
_t("MICRO_04", "铜绿假单胞菌定量杀菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.11")
_t("MICRO_05", "枯草杆菌黑色变种芽胞定量杀菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.5")
_t("MICRO_06", "龟分枝杆菌定量杀菌试验", "微生物", "《消毒技术规范》（2002年版）")
_t("MICRO_07", "脊髓灰质炎病毒灭活试验", "微生物", "《消毒技术规范》（2002年版）2.2.2")
_t("MICRO_08", "白色葡萄球菌空气消毒试验", "微生物", "《消毒技术规范》（2002年版）2.1.3")
_t("MICRO_09", "黑曲霉菌定量杀菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.14")
_t("MICRO_10", "模拟现场试验", "微生物", "《消毒技术规范》（2002年版）2.1.2")
_t("MICRO_11", "现场试验", "微生物", "《消毒技术规范》（2002年版）")
_t("MICRO_12", "灭菌效果鉴定试验", "微生物", "《消毒技术规范》（2002年版）")

# 微生物—抑菌
_t("BACT_01", "大肠杆菌抑菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.8")
_t("BACT_02", "金黄色葡萄球菌抑菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.8")
_t("BACT_03", "白色念珠菌抑菌试验", "微生物", "《消毒技术规范》（2002年版）2.1.8")
_t("BACT_04", "抗菌性能评价", "微生物", "GB 38456-2020")
_t("BACT_05", "持效性试验（多次接种）", "微生物", "《消毒技术规范》（2002年版）")

# 微生物指标
_t("MICRO_IDX_01", "细菌菌落总数检测", "微生物", "GB 15979-2002")
_t("MICRO_IDX_02", "大肠菌群检测", "微生物", "GB 15979-2002")
_t("MICRO_IDX_03", "真菌菌落总数检测", "微生物", "GB 15979-2002")
_t("MICRO_IDX_04", "致病性化脓菌检测", "微生物", "GB 15979-2002")

# 毒理类
_t("TOX_01", "急性经口毒性试验", "毒理", "GB/T 38496-2020")
_t("TOX_02", "急性吸入毒性试验", "毒理", "GB/T 38496-2020")
_t("TOX_03", "一次完整皮肤刺激试验", "毒理", "GB/T 38496-2020")
_t("TOX_04", "多次完整皮肤刺激试验", "毒理", "GB/T 38496-2020")
_t("TOX_05", "一次破损皮肤刺激试验", "毒理", "GB/T 38496-2020")
_t("TOX_06", "眼刺激试验", "毒理", "GB/T 38496-2020")
_t("TOX_07", "阴道粘膜刺激试验", "毒理", "GB/T 38496-2020")
_t("TOX_08", "致突变试验", "毒理", "GB/T 38496-2020")

# 其他
_t("OTHER_01", "载体材料相容性", "其他", "——")
_t("OTHER_02", "浸渍液含量测定", "其他", "——")
_t("OTHER_03", "压力容器安全性", "其他", "——")
_t("OTHER_04", "喷雾粒径分布", "其他", "——")
_t("OTHER_05", "全成分分析", "其他", "——")
_t("OTHER_06", "食品安全相关检测（GB 14930.2）", "其他", "GB 14930.2-2012")


# ── 基础检测包映射表 ──
# key: (product_category, sub_type, dosage_form)
# value: list of item codes

BASE_TEST_PACKAGES = {
    # ═══ 第二类 — 抗（抑）菌制剂 ═══
    ("第二类", "抗抑菌制剂", "液体"): [
        "PHYS_01", "PHYS_02",
        "BACT_01", "BACT_02", "BACT_03",
        "PHYS_03",
        "TOX_03", "TOX_06",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
    ],
    ("第二类", "抗抑菌制剂", "凝胶"): [
        "PHYS_01", "PHYS_02",
        "BACT_01", "BACT_02", "BACT_03",
        "PHYS_03",
        "TOX_03", "TOX_06",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
    ],
    ("第二类", "抗抑菌制剂", "喷雾"): [
        "PHYS_01", "PHYS_02",
        "BACT_01", "BACT_02", "BACT_03",
        "PHYS_03",
        "TOX_03", "TOX_06",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
    ],
    ("第二类", "抗抑菌制剂", "湿巾"): [
        "PHYS_01", "PHYS_02",
        "BACT_01", "BACT_02", "BACT_03",
        "PHYS_03",
        "TOX_03", "TOX_06",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
        "OTHER_01", "OTHER_02",
    ],
    ("第二类", "抗抑菌制剂", "片剂"): [
        "PHYS_01", "PHYS_02",
        "BACT_01", "BACT_02", "BACT_03",
        "PHYS_03",
        "TOX_03", "TOX_06",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
    ],

    # ═══ 第二类 — 消毒剂 ═══
    ("第二类", "消毒剂", "液体"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
    ],
    ("第二类", "消毒剂", "凝胶"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
    ],
    ("第二类", "消毒剂", "喷雾"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
    ],
    ("第二类", "消毒剂", "气雾"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
        "OTHER_03", "OTHER_04",
    ],
    ("第二类", "消毒剂", "湿巾"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
        "OTHER_01", "OTHER_02",
    ],
    ("第二类", "消毒剂", "片剂"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
    ],
    ("第二类", "消毒剂", "粉剂"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
    ],

    # ═══ 第二类 — 消毒器械（基础理化+杀菌因子验证） ═══
    ("第二类", "消毒器械", "——"): [
        "PHYS_02",
        "MICRO_12",
        "PHYS_03",
        "PHYS_08",
        "TOX_08",
    ],

    # ═══ 第一类 — 皮肤黏膜消毒剂 ═══
    ("第一类", None, "液体"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03", "MICRO_04",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
        "MICRO_10",
        "TOX_01", "TOX_03", "TOX_08",
    ],
    ("第一类", None, "凝胶"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03", "MICRO_04",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
        "MICRO_10",
        "TOX_01", "TOX_03", "TOX_08",
    ],
    ("第一类", None, "喷雾"): [
        "PHYS_01", "PHYS_02",
        "MICRO_01", "MICRO_02", "MICRO_03", "MICRO_04",
        "PHYS_03",
        "PHYS_05", "PHYS_06", "PHYS_07",
        "MICRO_IDX_01", "MICRO_IDX_02",
        "MICRO_10",
        "TOX_01", "TOX_03", "TOX_08",
    ],

    # ═══ 第三类 — 卫生用品 ═══
    ("第三类", "卫生用品", "湿巾"): [
        "PHYS_02",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
    ],
    ("第三类", "卫生用品", "液体"): [
        "PHYS_02",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
    ],
    ("第三类", "卫生用品", "——"): [
        "PHYS_02",
        "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
    ],
}

# ── 默认/兜底检测包 ──
# 当品类×剂型无精确匹配时使用
DEFAULT_BASE_PACKAGE = {
    "第二类": {
        "抗抑菌制剂": [
            "PHYS_01", "PHYS_02", "BACT_01", "BACT_02", "BACT_03",
            "PHYS_03", "TOX_03", "TOX_06",
            "PHYS_05", "PHYS_06", "PHYS_07",
            "MICRO_IDX_01", "MICRO_IDX_02", "MICRO_IDX_03", "MICRO_IDX_04",
        ],
        "消毒剂": [
            "PHYS_01", "PHYS_02", "MICRO_01", "MICRO_02", "MICRO_03",
            "PHYS_03", "PHYS_05", "PHYS_06", "PHYS_07",
            "MICRO_IDX_01", "MICRO_IDX_02",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# 表B：功效宣称 → 增量检测项
# ═══════════════════════════════════════════════════════════════
# 格式: ("触发关键词", [增量检测项code列表], "说明")

CLAIMS_INCREMENTAL_MAP = [
    # 抑菌/抗菌类 — 基础包未含抑菌试验时追加
    ("抑菌", ["BACT_01", "BACT_02", "BACT_03", "BACT_04"],
     "产品宣称抑菌功效，需加做抑菌试验和抗菌性能评价"),
    ("抗菌", ["BACT_01", "BACT_02", "BACT_03", "BACT_04"],
     "产品宣称为抗菌制剂，需加做抑菌试验和抗菌性能评价"),
    ("长效抑菌", ["BACT_05"],
     "宣称长效抑菌，需加做持效性试验（多次接种法）"),
    ("持久抑菌", ["BACT_05"],
     "宣称持久抑菌，需加做持效性试验"),
    ("广谱抑菌", ["BACT_01", "BACT_02", "BACT_03", "BACT_04"],
     "宣称广谱抑菌，需覆盖多种微生物抑菌试验"),

    # 消毒/杀菌类
    ("消毒", ["MICRO_01", "MICRO_02", "MICRO_03"],
     "产品宣称消毒功效，需加做定量杀菌试验"),
    ("杀菌", ["MICRO_01", "MICRO_02", "MICRO_03"],
     "产品宣称杀菌功效，需加做定量杀菌试验"),
    ("高效杀菌", ["MICRO_01", "MICRO_02", "MICRO_03", "MICRO_10"],
     "宣称高效杀菌，除基础杀菌外需加做模拟现场试验"),
    ("杀灭", ["MICRO_01", "MICRO_02", "MICRO_03"],
     "宣称杀灭微生物，需加做定量杀菌试验"),

    # 特殊使用场景
    ("食品工业", ["OTHER_06"],
     "适用于食品工业，需加做GB 14930.2相关食品安全检测"),
    ("食品接触", ["OTHER_06"],
     "适用于食品接触表面，需加做GB 14930.2相关检测"),
    ("餐饮具", ["PHYS_05", "PHYS_06", "MICRO_02", "TOX_01", "TOX_08"],
     "用于餐饮具消毒，需加做重金属和病毒灭活相关检测"),
    ("母婴", ["TOX_03", "TOX_01"],
     "宣称母婴适用，需加做皮肤刺激和急性经口毒性试验"),
    ("孕妇", ["TOX_03", "TOX_01"],
     "宣称孕妇适用，需加做安全性毒理学试验"),
    ("婴儿", ["TOX_03", "TOX_01"],
     "宣称婴儿适用，需加做皮肤刺激和急性经口毒性试验"),
    ("免洗", ["PHYS_09"],
     "宣称免洗，需加做残留量检测"),
    ("速干", ["PHYS_09"],
     "宣称速干免洗，需加做残留量检测"),

    # 医疗器械灭菌/高水平消毒
    ("灭菌", ["MICRO_05", "MICRO_12", "MICRO_10", "TOX_01", "TOX_03", "TOX_08"],
     "宣称灭菌用途，需加做芽胞杀灭、灭菌效果鉴定及全套毒理学试验"),
    ("高水平消毒", ["MICRO_05", "MICRO_06", "MICRO_07", "MICRO_10",
                    "TOX_01", "TOX_03", "TOX_08"],
     "宣称高水平消毒，需加做分枝杆菌、芽胞和病毒杀灭试验"),
    ("中水平消毒", ["MICRO_06", "MICRO_07", "MICRO_10", "TOX_01", "TOX_03", "TOX_08"],
     "宣称中水平消毒，需加做分枝杆菌和病毒杀灭试验"),

    # 皮肤/黏膜类（第一类产品时需追加）
    ("皮肤消毒", ["TOX_03", "TOX_04", "MICRO_01", "MICRO_04", "MICRO_10",
                  "PHYS_05", "PHYS_06", "PHYS_07", "MICRO_IDX_01",
                  "TOX_01", "TOX_08"],
     "宣称皮肤消毒（第一类），需加做全套皮肤消毒相关检测"),
    ("黏膜消毒", ["TOX_01", "TOX_03", "TOX_06", "TOX_07", "TOX_08",
                  "MICRO_01", "MICRO_04", "MICRO_03", "MICRO_10",
                  "PHYS_05", "PHYS_06", "PHYS_07", "MICRO_IDX_01"],
     "宣称黏膜消毒（第一类），需加做全套黏膜消毒相关检测"),
    ("外科手消毒", ["TOX_03", "TOX_04", "MICRO_01", "MICRO_02", "MICRO_03",
                    "MICRO_10", "TOX_01", "TOX_08"],
     "宣称外科手消毒，需加做多次皮肤刺激和全套杀菌试验"),
    ("卫生手消毒", ["TOX_03", "TOX_04", "MICRO_01", "MICRO_02", "MICRO_03",
                    "MICRO_10", "TOX_01", "TOX_08"],
     "宣称卫生手消毒，需加做多次皮肤刺激和全套杀菌试验"),

    # 特殊病原体宣称 — 触发安全层 R3，不生成检测方案
    ("病毒", None, "R3_SAFETY_BLOCK"),
    ("新冠", None, "R3_SAFETY_BLOCK"),
    ("COVID", None, "R3_SAFETY_BLOCK"),
    ("SARS", None, "R3_SAFETY_BLOCK"),
    ("禽流感", None, "R3_SAFETY_BLOCK"),
    ("诺如", None, "R3_SAFETY_BLOCK"),
    ("手足口", None, "R3_SAFETY_BLOCK"),
    ("艾滋", None, "R3_SAFETY_BLOCK"),
    ("乙肝", None, "R3_SAFETY_BLOCK"),
    ("结核", None, "R3_SAFETY_BLOCK"),
    ("MRSA", None, "R3_SAFETY_BLOCK"),
    ("治疗", None, "R3_SAFETY_BLOCK"),
    ("预防", None, "R3_SAFETY_BLOCK"),
    ("治愈", None, "R3_SAFETY_BLOCK"),
    ("抗病毒", None, "R3_SAFETY_BLOCK"),

    # 清洁 — 不增加
    ("清洁", [], "清洁为基本功能宣称，不增加检测项"),
    ("清洗", [], "清洗为基本功能宣称，不增加检测项"),
    ("去污", [], "去污为基本功能宣称，不增加检测项"),
    ("除异味", [], "除异味不增加检测项"),
    ("清香", [], "香气宣称不增加检测项"),
    ("滋润", [], "滋润宣称不增加检测项"),
    ("护肤", [], "护肤宣称不增加检测项"),
]


def get_base_package(product_category: str, sub_type: str, dosage_form: str) -> dict:
    """查询基础检测包。

    返回:
        items:          检测项code列表
        match_type:     "exact" / "fallback" / "not_found"
        basis:          映射依据
        note:           匹配说明
    """
    # 归一化：第一类产品无子类型，统一为 None
    sub_type_normalized = sub_type if sub_type else None
    sub_type_for_key = sub_type_normalized

    # 精确匹配
    key = (product_category, sub_type_for_key, dosage_form)
    if key in BASE_TEST_PACKAGES:
        return {
            "items": list(BASE_TEST_PACKAGES[key]),
            "match_type": "exact",
            "basis": (
                "依据网上备案通知（国卫办监督函〔2018〕864号）附表2.1，"
                f"{'第一类' if product_category == '第一类' else '第二类' if product_category == '第二类' else '第三类'}"
                f"产品（{'抗（抑）菌制剂' if sub_type == '抗抑菌制剂' else sub_type or ''}"
                f"{'/' + dosage_form if dosage_form != '——' else ''}）的基础检测要求。"
            ),
            "note": "",
        }

    # 剂型兜底匹配
    for (cat, st, df), codes in BASE_TEST_PACKAGES.items():
        if cat == product_category and st == sub_type_for_key:
            return {
                "items": list(codes),
                "match_type": "fallback",
                "basis": (
                    "产品剂型未精确匹配，使用该品类默认剂型的基础检测包。"
                ),
                "note": f"剂型「{dosage_form}」不在精确映射表中，已使用默认方案。",
            }

    # 品类×子类型兜底
    if product_category in DEFAULT_BASE_PACKAGE:
        cat_default = DEFAULT_BASE_PACKAGE[product_category]
        if sub_type_normalized and sub_type_normalized in cat_default:
            return {
                "items": list(cat_default[sub_type]),
                "match_type": "fallback",
                "basis": "使用该品类默认检测方案。",
                "note": f"品类「{product_category}」+子类型「{sub_type}」无精确剂型映射，使用默认方案。",
            }
        # 品类兜底（取该品类下第一个子类型的默认方案）
        first_sub = next(iter(cat_default))
        return {
            "items": list(cat_default[first_sub]),
            "match_type": "fallback",
            "basis": "使用该品类默认检测方案。",
            "note": f"品类「{product_category}」无对应子类型映射，使用默认方案。",
        }

    # 完全无法匹配
    return {
        "items": [],
        "match_type": "not_found",
        "basis": "",
        "note": f"无法为品类「{product_category}」+子类型「{sub_type}」生成基础检测方案，建议人工确认。",
    }


def get_incremental_items(target_claims: str) -> dict:
    """遍历功效宣称，查增量检测映射表。

    匹配顺序：安全层关键词（R3）优先于增量检测项，
    避免"杀灭"等宽泛词抢先匹配导致遗漏病毒/治疗类安全拦截。

    返回:
        items:              增量检测项code列表
        triggered_claims:   触发的宣称列表
        safety_blocked:     是否触发安全层拦截（R3病毒/治疗宣称）
        safety_detail:      拦截详情
        non_standard:       表中未覆盖的宣称列表（需LLM辅助）
    """
    if not target_claims.strip():
        return {
            "items": [],
            "triggered_claims": [],
            "safety_blocked": False,
            "safety_detail": "",
            "non_standard": [],
        }

    # 分离安全层关键词和增量检测关键词
    safety_keywords = []
    incremental_keywords = []
    for kw, items, note in CLAIMS_INCREMENTAL_MAP:
        if note == "R3_SAFETY_BLOCK":
            safety_keywords.append((kw, note))
        else:
            incremental_keywords.append((kw, items, note))

    claims_list = [c.strip() for c in re.split(r'[、，,;；\n]', target_claims) if c.strip()]

    incremental = []
    triggered = []
    safety_blocked = False
    safety_detail = ""
    non_standard = []
    blocked_claims = set()  # 被安全层拦截的宣称，不再生成增量

    # 第一轮：安全层关键词扫描（优先级最高）
    for claim in claims_list:
        for keyword, note in safety_keywords:
            if keyword in claim:
                safety_blocked = True
                safety_detail = (
                    f"宣称「{claim}」触发了安全层拦截。"
                    f"消字号产品禁止涉及疾病治疗、抗病毒等医疗用途宣称。"
                    f"不为该宣称生成检测方案，建议向用户说明合规风险并转人工确认。"
                )
                triggered.append(claim)
                blocked_claims.add(claim)
                break

    # 第二轮：增量检测关键词匹配（仅处理未被安全层拦截的宣称）
    # 按关键词长度降序排列，长词优先（如"长效抑菌"先于"抑菌"）
    incremental_keywords.sort(key=lambda x: len(x[0]), reverse=True)
    for claim in claims_list:
        if claim in blocked_claims:
            continue
        matched = False
        for keyword, items, note in incremental_keywords:
            if keyword in claim:
                if items is not None and len(items) > 0:
                    incremental.extend(items)
                triggered.append(claim)
                matched = True
                break
        if not matched:
            non_standard.append(claim)

    return {
        "items": incremental,
        "triggered_claims": triggered,
        "safety_blocked": safety_blocked,
        "safety_detail": safety_detail,
        "non_standard": non_standard,
    }


def merge_and_sort(base_items: list, incremental_items: list) -> list:
    """合并基础包和增量检测项，去重并按类别排序。

    排序规则：理化 → 微生物 → 毒理 → 其他
    """
    # 去重
    seen = set()
    merged_codes = []
    for code in base_items + incremental_items:
        if code not in seen:
            seen.add(code)
            merged_codes.append(code)

    # 按类别排序
    cat_order = {"理化": 1, "微生物": 2, "毒理": 3, "其他": 4}

    def sort_key(code):
        item = _test_items.get(code, {"category": "其他"})
        return (cat_order.get(item["category"], 99), code)

    merged_codes.sort(key=sort_key)
    return merged_codes


def generate_test_plan(product_category: str, sub_type: str, dosage_form: str,
                       target_claims: str) -> dict:
    """生成完整检测方案。

    输入:
        product_category: S2 输出（第一类/第二类/第三类/未分类）
        sub_type:         S2 输出（消毒剂/抗抑菌制剂/消毒器械/卫生用品）
        dosage_form:      S1 输出（液体/凝胶/喷雾/湿巾/片剂/其他）
        target_claims:    S1 输出（宣称功效文本）

    返回:
        test_items:       完整检测项列表 [{code, name, category, standard}, ...]
        base_count:       基础包项数
        incremental_count:增量项数
        total_count:      总项数
        summary:          方案概要
        safety_blocked:   是否触发安全层拦截
        safety_detail:    拦截详情
        non_standard:     非标准宣称列表（需LLM辅助）
        is_classified:    是否成功分类
        error_message:    错误信息
    """
    # 前置检查
    if product_category == "未分类" or not product_category:
        return {
            "test_items": [],
            "base_count": 0,
            "incremental_count": 0,
            "total_count": 0,
            "summary": "产品未分类，无法生成检测方案。",
            "safety_blocked": False,
            "safety_detail": "",
            "non_standard": [],
            "is_classified": False,
            "error_message": "产品分类未完成（S2），无法生成检测方案。请先完成分类判定。",
        }

    # Step A: 查基础检测包
    base = get_base_package(product_category, sub_type, dosage_form)
    if base["match_type"] == "not_found":
        return {
            "test_items": [],
            "base_count": 0,
            "incremental_count": 0,
            "total_count": 0,
            "summary": "无法为当前品类×剂型组合生成检测方案。",
            "safety_blocked": False,
            "safety_detail": "",
            "non_standard": [],
            "is_classified": True,
            "error_message": base["note"],
        }

    # Step B: 查宣称增量
    incremental = get_incremental_items(target_claims)

    # 如果触发安全层拦截（病毒宣称），基础包仍然生成，但增量不追加病毒相关项
    if incremental["safety_blocked"]:
        # 基础包正常生成，增量忽略R3触发项
        pass

    # Step C: 合并去重排序
    merged_codes = merge_and_sort(base["items"], incremental["items"])
    test_items = [_test_items[code] for code in merged_codes if code in _test_items]

    # 生成摘要
    parts = []
    parts.append(f"{'第一类' if product_category == '第一类' else '第二类' if product_category == '第二类' else '第三类'}")
    if sub_type:
        parts.append(f"（{sub_type}）")
    parts.append(f" | 剂型：{dosage_form}")
    parts.append(f" | 基础{base['match_type']}匹配")
    if base["note"]:
        parts.append(f"\n注意：{base['note']}")

    summary_text = "检测方案生成完毕。"
    category_summary = ""
    cat_counts = {}
    for item in test_items:
        c = item["category"]
        cat_counts[c] = cat_counts.get(c, 0) + 1
    cat_parts = []
    for cat in ("理化", "微生物", "毒理", "其他"):
        if cat in cat_counts:
            cat_parts.append(f"{cat}{cat_counts[cat]}项")
    if cat_parts:
        category_summary = "、".join(cat_parts)
        summary_text = f"检测方案：共{len(test_items)}项（{category_summary}）。"

    return {
        "test_items": test_items,
        "base_count": len(base["items"]),
        "incremental_count": len(incremental["items"]),
        "total_count": len(test_items),
        "summary": summary_text,
        "safety_blocked": incremental["safety_blocked"],
        "safety_detail": incremental["safety_detail"],
        "non_standard": incremental["non_standard"],
        "is_classified": True,
        "error_message": "",
    }


async def main(args) -> dict:
    """Coze Code Node 入口（Python 3.11.3 / Coze 当前标准格式）。

    Coze 输入变量（来自 S1 entry_merge + S2 classification_decision + S4 risk_grading）:
        product_category:  string  — S2 输出（第一类/第二类/第三类/未分类）
        sub_type:          string  — S2 输出（消毒剂/抗抑菌制剂/消毒器械/卫生用品）
        dosage_form:       string  — S1 输出（液体/凝胶/喷雾/湿巾/片剂/其他）
        target_claims:     string  — S1 输出（宣称功效）
        risk_level:        string  — S4 输出（R1/R2/R3）。R3 时阻断方案生成，仅输出安全拦截信息。

    Coze 输出变量:
        test_items_json:     string  — 检测项JSON数组 [{code, name, category, standard}, ...]
        base_count:          int     — 基础包项数
        incremental_count:   int     — 增量项数
        total_count:         int     — 总检测项数
        summary:             string  — 方案概要
        safety_blocked:      bool    — 是否触发安全层R3拦截（来自 S0 病毒/治疗类关键词 或 S4 R3 风险等级）
        safety_detail:       string  — 拦截详情
        non_standard:        string  — 非标准宣称（"、"连接）
        is_classified:       bool    — 是否成功生成
        error_message:       string  — 错误信息
    """
    global _diagnostics
    _diagnostics = []  # 每次调用清空诊断信息

    # ── 解析输入 ──
    try:
        product_category = _get(args, "product_category", "") or ""
        sub_type = _get(args, "sub_type", "") or ""
        dosage_form = _get(args, "dosage_form", "") or ""
        target_claims = _get(args, "target_claims", "") or ""
        risk_level = _get(args, "risk_level", "") or ""
    except AttributeError as e:
        _warn(f"args 结构异常: {e}")
        return _build_error("S5_ARGS_STRUCTURE_ERROR", str(e))
    except Exception as e:
        _warn(f"输入解析未预期的异常: {type(e).__name__}: {e}")
        return _build_error("S5_INPUT_PARSE_ERROR", str(e))

    # ── 检查 risk_level（S4 输出 R3 时阻断方案生成）──
    if risk_level.strip() == "R3":
        return {
            "test_items_json": "[]",
            "base_count": 0,
            "incremental_count": 0,
            "test_total_count": 0,
            "test_summary": "风险等级为 R3（高风险），禁止生成检测方案。请转人工专家处理。",
            "safety_blocked": True,
            "safety_detail": (
                f"S4 风险分级为 R3，已阻断检测方案生成。"
                f"可能原因：含禁用成分、医疗暗示宣称、退单历史、先上市后补备案、试图规避监管。"
            ),
            "non_standard": "",
            "is_classified": False,
            "error_message": "S4 风险等级 R3，系统阻断。",
            "diagnostics": _json.dumps(_diagnostics, ensure_ascii=False),
        }

    # ── 检查必填字段 ──
    if not product_category.strip():
        _warn("缺少产品分类信息（S2），无法生成检测方案")
        return _build_error("S5_MISSING_CLASSIFICATION", "产品分类缺失（S2）")

    # ── 生成检测方案 ──
    plan = generate_test_plan(product_category, sub_type, dosage_form, target_claims)

    # ── 序列化输出 ──
    try:
        items_json = _json.dumps(plan["test_items"], ensure_ascii=False)
    except (TypeError, ValueError) as e:
        _warn(f"检测项 JSON 序列化失败: {e}")
        return _build_error("S5_JSON_SERIALIZE_ERROR", str(e))

    non_standard_str = "、".join(plan["non_standard"])

    result = {
        "test_items_json": items_json,
        "base_count": plan["base_count"],
        "incremental_count": plan["incremental_count"],
        "test_total_count": plan["total_count"],
        "test_summary": plan["summary"],
        "safety_blocked": plan["safety_blocked"],
        "safety_detail": plan["safety_detail"],
        "non_standard": non_standard_str,
        "is_classified": plan["is_classified"],
        "error_message": plan["error_message"],
    }

    if _diagnostics:
        result["diagnostics"] = _json.dumps(_diagnostics, ensure_ascii=False)

    return result
