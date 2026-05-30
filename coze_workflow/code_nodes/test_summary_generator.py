"""
S7 预审摘要生成 — 单元测试
运行: python3 test_summary_generator.py
"""

import json
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(__file__))
from summary_generator import (
    generate_summary,
    _build_product_section,
    _build_classification_section,
    _build_compliance_section,
    _build_risk_section,
    _build_testplan_section,
    _build_next_steps,
    _build_error,
    NEXT_STEPS,
    DISCLAIMERS,
)

PASS = 0
FAIL = 0


def test(name, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")
        print(f"     预期: {expected!r}")
        print(f"     实际: {actual!r}")


def test_contains(name, text, substring):
    global PASS, FAIL
    if substring in text:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: 文本中未找到 '{substring}'")


def test_not_contains(name, text, substring):
    global PASS, FAIL
    if substring not in text:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: 文本中不应包含 '{substring}'")


# ═══════════════════════════════════════════════════════════════
# 产品信息章节
# ═══════════════════════════════════════════════════════════════

print("── 产品信息章节 ──")
r = _build_product_section("抑菌洗手液", "液体", "国产", "抑菌、清洁")
test_contains("PROD-01 含产品名称", r, "抑菌洗手液")
test_contains("PROD-01 含剂型", r, "液体")
test_contains("PROD-01 含产地", r, "国产")
test_contains("PROD-01 含宣称", r, "抑菌、清洁")

r = _build_product_section("", "", "", "")
test_contains("PROD-02 空名称仍输出章节标题", r, "产品信息")
test("PROD-02 空产地显示未提供", "未提供" in r, True)


# ═══════════════════════════════════════════════════════════════
# 分类判定章节
# ═══════════════════════════════════════════════════════════════

print("\n── 分类判定章节 ──")
r = _build_classification_section("第二类", "抗抑菌制剂")
test_contains("CLS-01 含第二类", r, "第二类消毒产品")
test_contains("CLS-01 含子类型", r, "抗抑菌制剂")
test_contains("CLS-01 含法规路径", r, "中等风险")

r = _build_classification_section("第一类", "")
test_contains("CLS-02 第一类", r, "第一类消毒产品")
test_contains("CLS-02 高风险管理", r, "严格的安全性评价")

r = _build_classification_section("第三类", "卫生用品")
test_contains("CLS-03 第三类", r, "第三类消毒产品")
test_contains("CLS-03 低风险", r, "风险较低")

r = _build_classification_section("未分类", "")
test_contains("CLS-04 未分类提示", r, "未完成分类判定")

r = _build_classification_section("", "")
test_contains("CLS-05 空分类→未分类提示", r, "未完成分类判定")


# ═══════════════════════════════════════════════════════════════
# 成分合规章节
# ═══════════════════════════════════════════════════════════════

print("\n── 成分合规章节 ──")
ingredients = [
    {"ingredient": "酒精", "status": "allowed_active"},
    {"ingredient": "甘油", "status": "allowed_inert"},
    {"ingredient": "苯扎氯铵", "status": "restricted"},
    {"ingredient": "神秘提取物", "status": "unknown"},
]
r = _build_compliance_section(ingredients)
test_contains("COMP-01 含允许成分", r, "酒精")
test_contains("COMP-01 含限制成分", r, "苯扎氯铵")
test_contains("COMP-01 含未收录成分", r, "神秘提取物")
test_contains("COMP-01 含✅标记", r, "✅")
test_contains("COMP-01 含⚠️标记", r, "⚠️")
test_contains("COMP-01 含❓标记", r, "❓")

# 仅允许成分
r = _build_compliance_section([{"ingredient": "酒精", "status": "allowed_active"}])
test_contains("COMP-02 全合规提示", r, "所有成分均在 GB 38850-2020")

# 空成分
r = _build_compliance_section([])
test_contains("COMP-03 空成分", r, "无成分数据")


# ═══════════════════════════════════════════════════════════════
# 风险分级章节
# ═══════════════════════════════════════════════════════════════

print("\n── 风险分级章节 ──")
r = _build_risk_section("R1", "R1 低风险", ["常规合规产品"], ["所有成分合规"])
test_contains("RISK-01 含R1标签", r, "R1 低风险")
test_contains("RISK-01 含可报价提示", r, "正常进入检测报价")
test_contains("RISK-01 含🟢", r, "🟢")

r = _build_risk_section("R2", "R2 中风险", ["含未收录成分", "进口产品"],
                         ["不在清单中", "进口走不同法规路径"])
test_contains("RISK-02 含R2标签", r, "R2 中风险")
test_contains("RISK-02 含🟡", r, "🟡")
test_contains("RISK-02 含人工复核", r, "人工复核")
test_contains("RISK-02 两个触发条件", r, "含未收录成分")
test_contains("RISK-02 含进口触发", r, "进口产品")

r = _build_risk_section("R3", "R3 高风险", ["含禁用成分", "医疗暗示"],
                         ["含禁用物质", "宣称涉及疾病治疗"])
test_contains("RISK-03 含R3标签", r, "R3 高风险")
test_contains("RISK-03 含🔴", r, "🔴")
test_contains("RISK-03 含禁止报价", r, "禁止生成报价")
test_contains("RISK-03 含转人工", r, "转人工专家")

r = _build_risk_section("", "", [], [])
test_contains("RISK-04 空风险数据", r, "风险分级数据缺失")


# ═══════════════════════════════════════════════════════════════
# 检测方案章节
# ═══════════════════════════════════════════════════════════════

print("\n── 检测方案章节 ──")
r = _build_testplan_section(14, "检测方案：共14项（理化6项、微生物6项、毒理2项）",
                            False, "", "")
test_contains("TP-01 含检测项数", r, "共14项")
test_contains("TP-01 含分类统计", r, "理化6项")

r = _build_testplan_section(14, "检测方案：共14项", True,
                            "宣称「抗病毒」触发安全拦截", "除螨、除甲醛")
test_contains("TP-02 安全拦截提示", r, "⚠️")
test_contains("TP-02 含拦截详情", r, "抗病毒")
test_contains("TP-02 含非标准宣称", r, "除螨、除甲醛")

r = _build_testplan_section(0, "", True, "R3阻断", "")
test_contains("TP-03 无检测方案", r, "未生成")
test_contains("TP-03 含拦截原因", r, "R3阻断")

r = _build_testplan_section(0, "", False, "", "")
test_contains("TP-04 零项提示", r, "暂未生成检测方案")


# ═══════════════════════════════════════════════════════════════
# 下一步建议
# ═══════════════════════════════════════════════════════════════

print("\n── 下一步建议 ──")
r = _build_next_steps("R1", True)
test_contains("NEXT-01 R1下一步", r, "启动消字号备案流程")
test_contains("NEXT-01 含后续流程", r, "后续流程")

r = _build_next_steps("R2", True)
test_contains("NEXT-02 R2下一步", r, "人工复核")

r = _build_next_steps("R3", True)
test_contains("NEXT-03 R3下一步", r, "转接人工专家")
test_not_contains("NEXT-03 不含常规流程", r, "后续流程")

r = _build_next_steps("R1", False)
test_contains("NEXT-04 未分类", r, "尚未完成分类判定")


# ═══════════════════════════════════════════════════════════════
# 完整报告生成 — Golden Path
# ═══════════════════════════════════════════════════════════════

print("\n── 完整报告生成 ──")

# Golden Path A: R1 抑菌洗手液
result = generate_summary(
    product_name="免洗抑菌洗手液",
    dosage_form="液体",
    domestic_or_imported="国产",
    target_claims="抑菌、清洁",
    product_category="第二类",
    sub_type="抗抑菌制剂",
    ingredient_results=[
        {"ingredient": "酒精", "status": "allowed_active"},
        {"ingredient": "甘油", "status": "allowed_inert"},
        {"ingredient": "卡波姆", "status": "allowed_inert"},
    ],
    risk_level="R1",
    risk_label="R1 低风险",
    trigger_labels=["常规合规产品"],
    trigger_details=["成分在允许清单中，功效合规，国产，无退单历史"],
    test_total_count=16,
    test_summary="检测方案：共16项（理化6项、微生物8项、毒理2项）",
)

report = result["markdown_report"]
test("FULL-01 report_ready", result["report_ready"], True)
test_contains("FULL-01 含产品名称", report, "免洗抑菌洗手液")
test_contains("FULL-01 含分类", report, "第二类消毒产品")
test_contains("FULL-01 含抗抑菌制剂", report, "抗抑菌制剂")
test_contains("FULL-01 含✅标记", report, "✅")
test_contains("FULL-01 含🟢", report, "🟢")
test_not_contains("FULL-01 不含免责声明", report, "风险提示")
test_contains("FULL-01 含检测项数", report, "16项")
test_contains("FULL-01 含下一步", report, "启动消字号备案流程")
test("FULL-01 disclaimer为空", result["disclaimer"], "")

# Golden Path B: R2 进口产品
result = generate_summary(
    product_name="抗菌湿巾",
    dosage_form="湿巾",
    domestic_or_imported="进口",
    target_claims="抗菌",
    product_category="第二类",
    sub_type="抗抑菌制剂",
    ingredient_results=[
        {"ingredient": "苯扎氯铵", "status": "restricted"},
        {"ingredient": "茶树精油", "status": "unknown"},
    ],
    risk_level="R2",
    risk_label="R2 中风险",
    trigger_labels=["含未收录成分", "进口产品"],
    trigger_details=["茶树精油不在清单中", "进口产品走不同法规路径"],
    test_total_count=17,
    test_summary="检测方案：共17项",
)
report = result["markdown_report"]
test("FULL-02 report_ready", result["report_ready"], True)
test_contains("FULL-02 含进口", report, "进口")
test_contains("FULL-02 含R2等级", report, "R2 中风险")
test_contains("FULL-02 含限制成分", report, "苯扎氯铵")
test_contains("FULL-02 含未收录", report, "茶树精油")
test_contains("FULL-02 含⚠️风险提示", report, "风险提示")
test_contains("FULL-02 含人工复核建议", report, "人工复核")
test("FULL-02 disclaimer非空", bool(result["disclaimer"]), True)

# Golden Path C: 未分类产品
result = generate_summary(
    product_name="某种喷雾",
    product_category="",
    sub_type="",
)
report = result["markdown_report"]
test("FULL-03 report_ready", result["report_ready"], True)
test_contains("FULL-03 含未分类提示", report, "未完成分类判定")
test_not_contains("FULL-03 不含成分合规", report, "成分合规状态")

# Golden Path D: R3 高风险
result = generate_summary(
    product_name="消毒喷雾",
    dosage_form="喷雾",
    domestic_or_imported="国产",
    target_claims="抗病毒、治疗",
    product_category="第二类",
    sub_type="消毒剂",
    ingredient_results=[],
    risk_level="R3",
    risk_label="R3 高风险",
    trigger_labels=["功效含医疗暗示"],
    trigger_details=["宣称涉及抗病毒、治疗等医疗用途"],
    test_total_count=0,
    test_summary="",
    safety_blocked=True,
    safety_detail="宣称「抗病毒」触发安全拦截",
)
report = result["markdown_report"]
test("FULL-04 report_ready", result["report_ready"], True)
test_contains("FULL-04 含R3", report, "R3 高风险")
test_contains("FULL-04 含🔴", report, "🔴")
test_contains("FULL-04 含禁止报价", report, "禁止生成报价")
test_contains("FULL-04 含转人工", report, "转接人工专家")
test_contains("FULL-04 含高风险警示", report, "高风险警示")
test("FULL-04 disclaimer含警示", "高风险警示" in result["disclaimer"], True)


# ═══════════════════════════════════════════════════════════════
# 结构化 JSON 输出验证
# ═══════════════════════════════════════════════════════════════

print("\n── 结构化 JSON ──")
result = generate_summary(
    product_name="抑菌洗手液",
    product_category="第二类",
    sub_type="抗抑菌制剂",
    ingredient_results=[{"ingredient": "酒精", "status": "allowed_active"}],
    risk_level="R1",
    risk_label="R1 低风险",
    trigger_labels=["常规合规产品"],
    test_total_count=14,
    test_summary="共14项",
)

summary_obj = json.loads(result["summary_json"])
test("JSON-01 含product", "product" in summary_obj, True)
test("JSON-01 产品名称", summary_obj["product"]["name"], "抑菌洗手液")
test("JSON-01 含classification", "classification" in summary_obj, True)
test("JSON-01 分类正确", summary_obj["classification"]["category"], "第二类")
test("JSON-01 含compliance", "compliance" in summary_obj, True)
test("JSON-01 含risk", "risk" in summary_obj, True)
test("JSON-01 含test_plan", "test_plan" in summary_obj, True)
test("JSON-01 含next_steps", "next_steps" in summary_obj, True)


# ═══════════════════════════════════════════════════════════════
# NEXT_STEPS / DISCLAIMERS 常量验证
# ═══════════════════════════════════════════════════════════════

print("\n── 常量验证 ──")
test("CONST-01 R1有下一步", bool(NEXT_STEPS.get("R1")), True)
test("CONST-02 R2有下一步", bool(NEXT_STEPS.get("R2")), True)
test("CONST-03 R3有下一步", bool(NEXT_STEPS.get("R3")), True)
test("CONST-04 R1无免责", DISCLAIMERS.get("R1"), "")
test("CONST-05 R2有免责", bool(DISCLAIMERS.get("R2")), True)
test("CONST-06 R3有免责", bool(DISCLAIMERS.get("R3")), True)


# ═══════════════════════════════════════════════════════════════
# Coze main() 集成测试
# ═══════════════════════════════════════════════════════════════

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
    from summary_generator import main
    args = MockArgs(params)
    return await main(args)


async def test_main():
    print("\n── Coze main() 集成 ──")

    r = await _call_main({
        "product_name": "抑菌洗手液",
        "dosage_form": "液体",
        "domestic_or_imported": "国产",
        "target_claims": "抑菌",
        "product_category": "第二类",
        "sub_type": "抗抑菌制剂",
        "results_json": json.dumps([
            {"ingredient": "酒精", "status": "allowed_active"},
            {"ingredient": "甘油", "status": "allowed_inert"},
        ]),
        "risk_level": "R1",
        "risk_label": "R1 低风险",
        "trigger_labels_json": json.dumps(["常规合规产品"]),
        "trigger_details_json": json.dumps(["成分在允许清单中"]),
        "test_total_count": 14,
        "test_summary": "检测方案：共14项",
        "safety_blocked": False,
    })
    test("MAIN-01 report_ready", r["report_ready"], True)
    test_contains("MAIN-01 含报告", r["markdown_report"], "抑菌洗手液")
    test_contains("MAIN-01 含JSON", r["summary_json"], "product")
    test("MAIN-01 next_steps非空", bool(r["next_steps"]), True)

    # 空输入 → 仍生成报告（S7 容错设计）
    r = await _call_main({})
    test("MAIN-02 空输入仍生成", r["report_ready"], True)
    test_contains("MAIN-02 含未分类提示", r["markdown_report"], "未完成分类判定")

    # 完整 R3 路径
    r = await _call_main({
        "product_name": "问题产品",
        "product_category": "第二类",
        "sub_type": "消毒剂",
        "results_json": "[]",
        "risk_level": "R3",
        "risk_label": "R3 高风险",
        "trigger_labels_json": json.dumps(["医疗暗示"]),
        "trigger_details_json": json.dumps(["宣称涉及治疗"]),
        "test_total_count": 0,
        "safety_blocked": True,
        "safety_detail": "安全拦截",
    })
    test("MAIN-03 R3路径", r["report_ready"], True)
    test_contains("MAIN-03 含R3", r["markdown_report"], "R3 高风险")
    test_contains("MAIN-03 含转人工", r["next_steps"], "转接人工专家")


async def test_main_errors():
    print("\n── Coze main() 错误路径 ──")

    # 非法 JSON → 不崩溃，降级处理
    r = await _call_main({
        "product_name": "测试",
        "results_json": "这不是JSON{[",
        "trigger_labels_json": "也不是JSON",
        "risk_level": "R1",
    })
    test("ERR-01 非法JSON不崩溃", r["report_ready"], True)

    # trigger_labels_json 为对象而非数组
    r = await _call_main({
        "product_name": "测试",
        "product_category": "第二类",
        "trigger_labels_json": '{"a": 1}',
        "trigger_details_json": '{"b": 2}',
        "risk_level": "R1",
    })
    test("ERR-02 对象而非数组→不崩溃", r["report_ready"], True)

    # test_total_count 类型异常
    r = await _call_main({
        "product_name": "测试",
        "product_category": "第二类",
        "test_total_count": "不是数字",
        "risk_level": "R1",
    })
    test("ERR-03 非数字count→不崩溃", r["report_ready"], True)

    # safety_blocked 字符串化
    r = await _call_main({
        "product_name": "测试",
        "product_category": "第二类",
        "risk_level": "R1",
        "safety_blocked": "true",
    })
    test("ERR-04 'true'字符串→不崩溃", r["report_ready"], True)


def test_build_error():
    print("\n── 错误构建 ──")
    r = _build_error("TEST_CODE", "测试错误")
    test("ERRBLD-01 report_ready=False", r["report_ready"], False)
    test_contains("ERRBLD-02 含错误码", r["markdown_report"], "TEST_CODE")
    test_contains("ERRBLD-03 diagnostics存在", r["diagnostics"], "[]")
    test("ERRBLD-04 next_steps提示人工", "转人工" in r["next_steps"], True)


# ═══════════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — S7 预审摘要生成 测试套件")
    print("覆盖: 产品信息 / 分类判定 / 成分合规 / 风险分级 / 检测方案 / 下一步建议")
    print("      Golden Path(R1/R2/R3/未分类) / 结构化JSON / main()集成 / 错误路径")
    print()

    asyncio.run(test_main())
    asyncio.run(test_main_errors())
    test_build_error()

    print(f"\n{'='*50}")
    total = PASS + FAIL
    print(f"通过: {PASS}/{total}")
    if FAIL > 0:
        print(f"失败: {FAIL}/{total}")
        sys.exit(1)
    else:
        print("全部通过！")
        sys.exit(0)
