"""
Coze Code Node — S4 风险分级 测试套件（test_risk_engine.py）

覆盖：
  - R3 触发：医疗暗示 / 退单 / 先上市 / 规避监管（5+ 用例）
  - R2 触发：未收录 / 进口 / 灰色地带 / 模糊宣称 / KB 过期（7+ 用例）
  - R1 正常（3 用例）
  - 优先级 R3 > R2 > R1（2 用例）
  - S3→S4 接口适配：results_json 解析 + 状态归一化（6 用例）
  - 灰色地带自动检测（3 用例）
  - 模糊宣称自动检测（3 用例）
  - 边界情况：空成分 / 成分缺字段 / 非法 JSON（3 用例）
  - 限制成分处理（2 用例）
"""

import sys
import os
import json
import asyncio

# 确保可以导入同目录下的 risk_engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from risk_engine import (
    assess_risk,
    _normalize_status,
    _detect_grey_area,
    _detect_vague_claims,
    _coerce_bool,
    _build_error,
)

_passed = 0
_failed = 0


def test(name, actual, expected):
    global _passed, _failed
    ok = actual == expected
    if ok:
        _passed += 1
        print(f"  ✅ {name}")
    else:
        _failed += 1
        print(f"  ❌ {name}")
        print(f"     预期: {expected!r}")
        print(f"     实际: {actual!r}")


# ═══════════════════════════════════════════════════════════════════
# S3 → S4 状态归一化
# ═══════════════════════════════════════════════════════════════════

def test_status_normalize():
    print("\n── 状态归一化 ──")

    test("NRM-01 allowed_active→allowed",
         _normalize_status("allowed_active"), "allowed")
    test("NRM-02 allowed_inert→allowed",
         _normalize_status("allowed_inert"), "allowed")
    test("NRM-03 water_base→allowed",
         _normalize_status("water_base"), "allowed")
    test("NRM-04 restricted→restricted",
         _normalize_status("restricted"), "restricted")
    test("NRM-05 unknown→unknown",
         _normalize_status("unknown"), "unknown")
    test("NRM-06 未知状态→unknown",
         _normalize_status("bogus"), "unknown")


# ═══════════════════════════════════════════════════════════════════
# R3 高风险触发
# ═══════════════════════════════════════════════════════════════════

def test_r3():
    print("\n── R3 高风险触发 ──")

    # R3-02 医疗暗示
    r = assess_risk(ingredient_results=[], medical_keyword_hit=True)
    test("R3-02 医疗暗示", r["risk_level"], "R3")
    test("R3-02 禁报价", r["can_quote"], False)
    test("R3-02 转人工", r["human_review_required"], True)

    # R3-03 退单历史
    r = assess_risk(ingredient_results=[], historical_rejection=True)
    test("R3-03 退单历史", r["risk_level"], "R3")
    test("R3-03 触发码", "historical_rejection" in r["trigger_codes"], True)

    # R3-04 先上市
    r = assess_risk(ingredient_results=[], prior_market_flag=True)
    test("R3-04 先上市", r["risk_level"], "R3")

    # R3-05 规避监管
    r = assess_risk(ingredient_results=[], regulation_circumvention=True)
    test("R3-05 规避监管", r["risk_level"], "R3")

    # 多 R3 叠加仍是 R3（含合规成分不受影响）
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "酒精", "status": "allowed_active"},
        ],
        medical_keyword_hit=True,
        historical_rejection=True,
        domestic_or_imported="进口",
    )
    test("R3-06 多条件+合规成分→R3", r["risk_level"], "R3")
    test("R3-06 多触发码", len(r["trigger_codes"]) >= 2, True)
    test("R3-06 转人工", r["human_review_required"], True)
    test("R3-06 需免责", r["disclaimer_required"], True)
    test("R3-06 成分汇总", r["allowed_count"], 1)

    # R3 优先级：即使成分全合规，R3 标志仍生效
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "酒精", "status": "allowed_active"},
            {"ingredient": "甘油", "status": "allowed_inert"},
            {"ingredient": "水", "status": "water_base"},
        ],
        medical_keyword_hit=True,
    )
    test("R3-07 全合规+R3标志→R3", r["risk_level"], "R3")
    # trigger_codes 存语义键名（如 "medical_claim"），不存格式化编号
    # 验证逻辑：R3 判定后不应混入 R2 触发码
    r2_leak = any(c in ("ingredient_unknown", "imported_product",
                         "grey_area_ingredient", "vague_claims",
                         "kb_table_expired")
                  for c in r["trigger_codes"])
    test("R3-07 不含R2触发码", r2_leak, False)


# ═══════════════════════════════════════════════════════════════════
# R2 中风险触发
# ═══════════════════════════════════════════════════════════════════

def test_r2():
    print("\n── R2 中风险触发 ──")

    # R2-01 含未收录成分
    r = assess_risk(ingredient_results=[
        {"ingredient": "纳米银", "status": "unknown"},
    ])
    test("R2-01 未收录成分", r["risk_level"], "R2")
    test("R2-01 可报价", r["can_quote"], True)
    test("R2-01 需免责", r["disclaimer_required"], True)
    test("R2-01 不转人工", r["human_review_required"], False)
    test("R2-01 未知计数", r["unknown_count"], 1)

    # R2-02 进口产品
    r = assess_risk(ingredient_results=[
        {"ingredient": "酒精", "status": "allowed_active"},
    ], domestic_or_imported="进口")
    test("R2-02 进口产品", r["risk_level"], "R2")
    test("R2-02 触发码", "imported_product" in r["trigger_codes"], True)

    # R2-03 灰色地带成分（自动检测）
    r = assess_risk(ingredient_results=[
        {"ingredient": "植物提取物", "status": "unknown"},
    ])
    test("R2-03 灰色成分", r["risk_level"], "R2")
    test("R2-03 双触发",
         "ingredient_unknown" in r["trigger_codes"] and
         "grey_area_ingredient" in r["trigger_codes"], True)

    # R2-04 功效描述模糊（自动检测）
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "酒精", "status": "allowed_active"},
        ],
        target_claims="高效广谱杀菌，持久抑菌，进口原料配方",
    )
    test("R2-04 模糊宣称", r["risk_level"], "R2")
    test("R2-04 触发码", "vague_claims" in r["trigger_codes"], True)

    # R2-05 KB 映射表过期（独立触发，不依赖 has_unknown）
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "酒精", "status": "allowed_active"},
        ],
        kb_table_expired=True,
    )
    test("R2-05 KB过期→R2（全合规产品降级）", r["risk_level"], "R2")
    test("R2-05 触发码", "kb_table_expired" in r["trigger_codes"], True)
    test("R2-05 可报价", r["can_quote"], True)

    # KB 过期 + R3 仍为 R3（不升不降）
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "酒精", "status": "allowed_active"},
        ],
        kb_table_expired=True,
        historical_rejection=True,
    )
    test("R2-06 KB过期+R3→R3（不降级）", r["risk_level"], "R3")

    # 多 R2 叠加仍是 R2
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "纳米银", "status": "unknown"},
            {"ingredient": "植物提取物", "status": "unknown"},
        ],
        domestic_or_imported="进口",
        kb_table_expired=True,
    )
    test("R2-07 多R2叠加→R2", r["risk_level"], "R2")
    test("R2-07 多条触发", len(r["trigger_codes"]) >= 3, True)


# ═══════════════════════════════════════════════════════════════════
# R1 低风险
# ═══════════════════════════════════════════════════════════════════

def test_r1():
    print("\n── R1 低风险 ──")

    # 标准合规产品
    r = assess_risk(ingredient_results=[
        {"ingredient": "酒精", "status": "allowed_active"},
        {"ingredient": "甘油", "status": "allowed_inert"},
        {"ingredient": "水", "status": "water_base"},
    ], domestic_or_imported="国产")
    test("R1-01 标准合规", r["risk_level"], "R1")
    test("R1-01 可报价", r["can_quote"], True)
    test("R1-01 不需免责", r["disclaimer_required"], False)
    test("R1-01 不转人工", r["human_review_required"], False)
    test("R1-01 触发码", r["trigger_codes"], ["all_clear"])
    test("R1-01 成分汇总", r["allowed_count"], 3)

    # 空成分 → R1
    r = assess_risk(ingredient_results=[])
    test("R1-02 空成分→R1", r["risk_level"], "R1")
    test("R1-02 全零", (r["allowed_count"] + r["restricted_count"] +
                         r["unknown_count"]), 0)

    # 申报来源为空/国产按国产处理
    r = assess_risk(ingredient_results=[
        {"ingredient": "酒精", "status": "allowed_active"},
    ], domestic_or_imported="")
    test("R1-03 空产地按国产→R1", r["risk_level"], "R1")


# ═══════════════════════════════════════════════════════════════════
# 优先级验证
# ═══════════════════════════════════════════════════════════════════

def test_priority():
    print("\n── 优先级 R3 > R2 > R1 ──")

    # R3 + R2 → R3（R2 不出现）
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "纳米银", "status": "unknown"},
        ],
        domestic_or_imported="进口",
        medical_keyword_hit=True,
    )
    test("PRI-01 R3+R2→R3", r["risk_level"], "R3")
    test("PRI-01 不含R2触发码",
         "ingredient_unknown" not in r["trigger_codes"] and
         "imported_product" not in r["trigger_codes"], True)

    # R2 + R1 → R2
    r = assess_risk(
        ingredient_results=[
            {"ingredient": "酒精", "status": "allowed_active"},
        ],
        domestic_or_imported="进口",
    )
    test("PRI-02 R2+R1→R2", r["risk_level"], "R2")


# ═══════════════════════════════════════════════════════════════════
# 灰色地带自动检测
# ═══════════════════════════════════════════════════════════════════

def test_grey_area_detection():
    print("\n── 灰色地带自动检测 ──")

    test("GRY-01 植物提取物", _detect_grey_area("绿茶植物提取物", "unknown"), True)
    test("GRY-02 纳米材料", _detect_grey_area("纳米银", "unknown"), True)
    test("GRY-03 生物酶", _detect_grey_area("木瓜生物酶", "unknown"), True)
    test("GRY-04 已收录成分不触发",
         _detect_grey_area("植物提取物", "allowed_active"), False)
    test("GRY-05 普通未知成分不触发",
         _detect_grey_area("未知物质X", "unknown"), False)


# ═══════════════════════════════════════════════════════════════════
# 模糊宣称自动检测
# ═══════════════════════════════════════════════════════════════════

def test_vague_claims_detection():
    print("\n── 模糊宣称自动检测 ──")

    test("VC-01 强效", _detect_vague_claims("强效杀菌消毒液"), True)
    test("VC-02 天然", _detect_vague_claims("纯天然植物配方"), True)
    test("VC-03 长效抑菌", _detect_vague_claims("长效抑菌保护"), True)
    test("VC-04 正常宣称",
         _detect_vague_claims("用于环境表面消毒，杀灭金黄色葡萄球菌"), False)
    test("VC-05 空宣称", _detect_vague_claims(""), False)
    # 上下文判断："高效" 不触发技术术语
    test("VC-06 高效液相色谱法(不触发)",
         _detect_vague_claims("经高效液相色谱法检测"), False)
    test("VC-07 高效杀菌(触发)",
         _detect_vague_claims("高效杀菌消毒"), True)
    # 已移除的假阳性模式
    test("VC-08 活性成分(不触发)",
         _detect_vague_claims("活性成分含量检测"), False)
    test("VC-09 表面活性剂(不触发)",
         _detect_vague_claims("含阴离子表面活性剂"), False)


# ═══════════════════════════════════════════════════════════════════
# 限用成分处理
# ═══════════════════════════════════════════════════════════════════

def test_restricted():
    print("\n── 限用成分处理 ──")

    # 仅有限制成分（在标准内）→ R1
    r = assess_risk(ingredient_results=[
        {"ingredient": "苯扎溴铵", "status": "restricted"},
    ])
    test("RST-01 限用成分→R1", r["risk_level"], "R1")
    test("RST-01 restricted计数", r["restricted_count"], 1)
    test("RST-01 allowed计数", r["allowed_count"], 0)

    # 限制成分 + 合规成分 → R1
    r = assess_risk(ingredient_results=[
        {"ingredient": "苯扎氯铵", "status": "restricted"},
        {"ingredient": "酒精", "status": "allowed_active"},
        {"ingredient": "水", "status": "water_base"},
    ])
    test("RST-02 限制+合规→R1", r["risk_level"], "R1")
    test("RST-02 汇总正确", r["restricted_count"], 1)
    test("RST-02 合规计数", r["allowed_count"], 2)


# ═══════════════════════════════════════════════════════════════════
# S3 results_json 解析（Coze main() 路径模拟）
# ═══════════════════════════════════════════════════════════════════

def test_s3_integration():
    print("\n── S3 接口集成 ──")

    # 模拟 S3 输出的 results_json
    s3_output = json.dumps([
        {"ingredient": "三氯生", "original_input": "三氯生0.3%",
         "status": "restricted", "cas": "3380-34-5",
         "basis": "...", "category": "active", "usage_scope": "E/H/M",
         "restriction": {"rule": "皮肤≤0.5%，黏膜≤0.2%"}},
        {"ingredient": "纳米银", "original_input": "纳米银",
         "status": "unknown", "cas": "",
         "basis": "", "category": "unknown", "usage_scope": "",
         "restriction": None},
        {"ingredient": "酒精", "original_input": "酒精75%",
         "status": "allowed_active", "cas": "64-17-5",
         "basis": "...", "category": "active", "usage_scope": "H",
         "restriction": None},
    ])

    parsed = json.loads(s3_output)
    r = assess_risk(ingredient_results=parsed)

    test("S3I-01 三成分混合→R2（含unknown+灰色）", r["risk_level"], "R2")
    test("S3I-02 allowed计数", r["allowed_count"], 1)
    test("S3I-03 restricted计数", r["restricted_count"], 1)
    test("S3I-04 unknown计数", r["unknown_count"], 1)
    test("S3I-05 灰色触发",
         "grey_area_ingredient" in r["trigger_codes"], True)


def test_json_edges():
    print("\n── JSON 边界 ──")

    # 空数组
    r = assess_risk(ingredient_results=[])
    test("JSON-01 空数组→R1", r["risk_level"], "R1")

    # 成分缺 status 字段
    r = assess_risk(ingredient_results=[
        {"ingredient": "某成分"},
    ])
    test("JSON-02 缺status→unknown→R2", r["risk_level"], "R2")
    test("JSON-02 未知计数", r["unknown_count"], 1)


# ═══════════════════════════════════════════════════════════════════
# 输出结构完整性
# ═══════════════════════════════════════════════════════════════════

def test_output_structure():
    print("\n── 输出结构 ──")

    r = assess_risk(
        ingredient_results=[
            {"ingredient": "酒精", "status": "allowed_active"},
        ],
        domestic_or_imported="国产",
    )

    required_keys = [
        "risk_level", "risk_label", "trigger_codes", "trigger_codes_json",
        "trigger_labels", "trigger_labels_json", "trigger_details",
        "trigger_details_json", "can_quote", "can_generate_pdf",
        "disclaimer_required", "human_review_required", "engine_action",
        "ingredient_summary", "allowed_count", "restricted_count",
        "unknown_count",
    ]
    for key in required_keys:
        test(f"OUT-{key}", key in r, True)

    # ingredient_summary 可解析
    s = json.loads(r["ingredient_summary"])
    test("OUT-summary解析", isinstance(s, dict), True)
    test("OUT-summary含四键",
         all(k in s for k in ("allowed", "restricted", "unknown", "prohibited")), True)
    test("OUT-prohibited_count", "prohibited_count" in r, True)


# ═══════════════════════════════════════════════════════════════════
# Boolean 强制转换（Coze 字符串化防护）
# ═══════════════════════════════════════════════════════════════════

def test_boolean_coercion():
    print("\n── Boolean 强制转换 ──")

    test("BOOL-01 True→True", _coerce_bool(True), True)
    test("BOOL-02 False→False", _coerce_bool(False), False)
    test("BOOL-03 'true'→True", _coerce_bool("true"), True)
    test("BOOL-04 'false'→False", _coerce_bool("false"), False)
    test("BOOL-05 'True'→True", _coerce_bool("True"), True)
    test("BOOL-06 'FALSE'→False", _coerce_bool("FALSE"), False)
    test("BOOL-07 '1'→True", _coerce_bool("1"), True)
    test("BOOL-08 '0'→False", _coerce_bool("0"), False)
    test("BOOL-09 None→False", _coerce_bool(None), False)
    test("BOOL-10 ''→False", _coerce_bool(""), False)
    test("BOOL-11 1→True", _coerce_bool(1), True)
    test("BOOL-12 0→False", _coerce_bool(0), False)
    test("BOOL-13 'yes'→True", _coerce_bool("yes"), True)
    test("BOOL-14 'no'→False", _coerce_bool("no"), False)


# ═══════════════════════════════════════════════════════════════════
# Prohibited 成分处理（S3 未来产出 + 防呆）
# ═══════════════════════════════════════════════════════════════════

def test_prohibited():
    print("\n── Prohibited 成分处理 ──")

    # 显式 prohibited 状态 → R3
    r = assess_risk(ingredient_results=[
        {"ingredient": "汞化合物", "status": "prohibited"},
    ])
    test("PRB-01 prohibited→R3", r["risk_level"], "R3")
    test("PRB-01 禁报价", r["can_quote"], False)
    test("PRB-01 触发码", "ingredient_prohibited" in r["trigger_codes"], True)
    test("PRB-01 计数", r["prohibited_count"], 1)

    # prohibited + 合规混合 → R3
    r = assess_risk(ingredient_results=[
        {"ingredient": "酒精", "status": "allowed_active"},
        {"ingredient": "汞化合物", "status": "prohibited"},
    ])
    test("PRB-02 mixed→R3", r["risk_level"], "R3")
    test("PRB-02 合规计数", r["allowed_count"], 1)
    test("PRB-02 禁用计数", r["prohibited_count"], 1)

    # prohibited 优先级高于 R2
    r = assess_risk(ingredient_results=[
        {"ingredient": "汞化合物", "status": "prohibited"},
        {"ingredient": "纳米银", "status": "unknown"},
    ], domestic_or_imported="进口")
    test("PRB-03 R3>R2", r["risk_level"], "R3")
    test("PRB-03 无R2泄露",
         "ingredient_unknown" not in r["trigger_codes"], True)


# ═══════════════════════════════════════════════════════════════════
# Coze main() 集成测试（含错误路径）
# ═══════════════════════════════════════════════════════════════════

class MockArgs:
    """模拟 Coze 运行时的 args 对象。"""
    def __init__(self, params: dict):
        self.params = self._Params(params)

    class _Params:
        def __init__(self, d: dict):
            self._d = d
        def get(self, key, default=None):
            return self._d.get(key, default)


async def _call_main(params: dict) -> dict:
    """调用 main() 并返回结果。"""
    from risk_engine import main
    args = MockArgs(params)
    return await main(args)


async def test_main():
    print("\n── Coze main() 集成 ──")

    # 正常路径
    r = await _call_main({
        "results_json": json.dumps([
            {"ingredient": "酒精", "status": "allowed_active"},
            {"ingredient": "甘油", "status": "allowed_inert"},
        ]),
        "domestic_or_imported": "国产",
        "target_claims": "环境表面消毒",
    })
    test("MAIN-01 正常路径→R1", r["risk_level"], "R1")
    test("MAIN-01 合规计数", r["allowed_count"], 2)

    # 含 unknown 成分 → R2
    r = await _call_main({
        "results_json": json.dumps([
            {"ingredient": "酒精", "status": "allowed_active"},
            {"ingredient": "纳米银", "status": "unknown"},
        ]),
        "domestic_or_imported": "国产",
    })
    test("MAIN-02 unknown→R2", r["risk_level"], "R2")

    # Boolean 字符串 "true" → 正确识别
    r = await _call_main({
        "results_json": "[]",
        "domestic_or_imported": "国产",
        "medical_keyword_hit": "true",
    })
    test("MAIN-03 'true'字符串→R3", r["risk_level"], "R3")

    # Boolean 字符串 "false" → 不误判
    r = await _call_main({
        "results_json": json.dumps([
            {"ingredient": "酒精", "status": "allowed_active"},
        ]),
        "domestic_or_imported": "国产",
        "medical_keyword_hit": "false",
        "historical_rejection": "false",
    })
    test("MAIN-04 'false'不误判→R1", r["risk_level"], "R1")


async def test_main_errors():
    print("\n── Coze main() 错误路径 ──")

    # JSON 格式错误 → 返回错误 R3（非静默 R1）
    r = await _call_main({
        "results_json": "这不是JSON{[",
        "domestic_or_imported": "国产",
    })
    test("ERR-01 非法JSON→R3", r["risk_level"], "R3")
    test("ERR-01 禁报价", r["can_quote"], False)
    test("ERR-01 系统错误码", "system_error" in r["trigger_codes"], True)

    # results_json 是 JSON 对象而非数组 → 错误
    r = await _call_main({
        "results_json": '{"error": "timeout"}',
        "domestic_or_imported": "国产",
    })
    test("ERR-02 非数组JSON→R3", r["risk_level"], "R3")
    test("ERR-02 禁报价", r["can_quote"], False)

    # results_json 为空字符串 → R1（真实无成分）
    r = await _call_main({
        "results_json": "",
        "domestic_or_imported": "国产",
    })
    test("ERR-03 空字符串→R1", r["risk_level"], "R1")

    # results_json 是空数组 → R1
    r = await _call_main({
        "results_json": "[]",
        "domestic_or_imported": "国产",
    })
    test("ERR-04 空数组→R1", r["risk_level"], "R1")


# ═══════════════════════════════════════════════════════════════════
# 错误构建函数
# ═══════════════════════════════════════════════════════════════════

def test_build_error():
    print("\n── 错误构建 ──")

    r = _build_error("TEST_CODE", "测试错误消息")
    test("ERRBLD-01 R3", r["risk_level"], "R3")
    test("ERRBLD-02 禁报价", r["can_quote"], False)
    test("ERRBLD-03 转人工", r["human_review_required"], True)
    test("ERRBLD-04 diagnostics存在", "diagnostics" in r, True)


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — S4 风险分级 测试套件")
    print("覆盖: S3接口 / R3/R2/R1触发 / 优先级 / 灰度检测 / 模糊宣称 / 边界")
    print("      Boolean强制转换 / Prohibited处理 / main()集成 / 错误路径")

    test_status_normalize()
    test_r3()
    test_r2()
    test_r1()
    test_priority()
    test_grey_area_detection()
    test_vague_claims_detection()
    test_restricted()
    test_s3_integration()
    test_json_edges()
    test_output_structure()
    test_boolean_coercion()
    test_prohibited()
    asyncio.run(test_main())
    asyncio.run(test_main_errors())
    test_build_error()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
