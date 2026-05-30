"""
全链路集成测试 — S1→S2→S3→S4→S5→S6→S7 串联

验证 7 个 Code Node 的端到端数据流转：
  - 场景 A: 抗抑菌制剂 R1 正常路径（品牌方 + 普通）
  - 场景 B: R3 阻断路径（医疗宣称 + 历史退单）
  - 场景 C: 最小输入 + 默认值容错
"""

import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── MockArgs: 模拟 Coze 运行时的 args 对象 ──
class MockArgs:
    def __init__(self, params: dict):
        self.params = self._Params(params)

    class _Params:
        def __init__(self, d: dict):
            self._d = d
        def get(self, key, default=None):
            return self._d.get(key, default)


async def run_node(module_name: str, params: dict) -> dict:
    """加载模块并调用 main(args)，返回结果 dict。"""
    mod = __import__(module_name)
    args = MockArgs(params)
    result = await mod.main(args)
    return result


PASS, FAIL = 0, 0


def check(desc, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✅ {desc}")
    else:
        FAIL += 1
        print(f"  ❌ {desc}")
        print(f"     期望: {expected!r}")
        print(f"     实际: {actual!r}")


def check_contains(desc, haystack: str, needle: str):
    global PASS, FAIL
    if needle in haystack:
        PASS += 1
        print(f"  ✅ {desc}")
    else:
        FAIL += 1
        print(f"  ❌ {desc}")
        print(f"     '{needle}' 未出现在输出中")
        print(f"     输出截断: {haystack[:200]}...")


# ═══════════════════════════════════════════════════════════════
# 场景 A: 抗抑菌制剂 R1 正常路径
# ═══════════════════════════════════════════════════════════════

async def test_scenario_a():
    """
    产品: 维达免洗洗手液（凝胶）
    成分: 酒精75%、甘油、卡波姆
    宣称: 消毒、抑菌
    客户: 品牌方, 国产, 普通
    预期: S2→第二类抗抑菌制剂, S3→部分已知部分未知, S4→R1或R2, S5→有检测方案, S6→有报价, S7→完整报告
    """
    print("\n" + "=" * 60)
    print("  场景 A: 抗抑菌制剂 R1 正常路径")
    print("=" * 60)

    # ── S1: 入口解析 ──
    template = """产品名称：维达免洗洗手液
剂型：凝胶
核心成分：酒精（75%）、甘油、卡波姆
宣称功效：消毒、抑菌
产地：国产
您的角色：品牌方
使用场景：家庭
已有检测报告：没有
退单历史：没有
紧急程度：普通"""

    s1 = await run_node("entry_merge", {"structured_text": template})
    print("\n── S1 入口解析 ──")
    check("ready=True", s1.get("ready"), True)
    check("产品名称", s1.get("product_name"), "维达免洗洗手液")
    check("剂型", s1.get("dosage_form"), "凝胶")
    check("产地", s1.get("domestic_or_imported"), "国产")
    check("客户类型", s1.get("customer_type"), "品牌方")
    check("紧急程度", s1.get("urgency_level"), "普通")
    check("error_message 空", s1.get("error_message"), "")

    # ── S2: 分类判定 ──
    s2 = await run_node("classification_decision", {
        "product_name": s1["product_name"],
        "target_claims": s1["target_claims"],
        "dosage_form": s1["dosage_form"],
    })
    print("\n── S2 分类判定 ──")
    check("product_category=第二类", s2.get("product_category"), "第二类")
    check("is_classified=True", s2.get("is_classified"), True)
    # 「消毒、抑菌」同时命中 消毒剂 + 抗抑菌制剂 → 触发冲突消解
    # needs_review=True, sub_type 为空，这是 PRD resolve_conflict 的正确行为
    check("needs_review=True (冲突消解)", s2.get("needs_review"), True)
    check("sub_type 空(需人工确认)", s2.get("sub_type"), "")
    check("error_message 含冲突提示", "需人工确认" in s2.get("error_message", ""), True)

    # ── S3: 成分合规检查 ──
    s3 = await run_node("ingredient_compliance", {
        "main_ingredients": s1["main_ingredients"],
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
    })
    print("\n── S3 成分合规检查 ──")
    check("ingredient_count > 0", s3.get("ingredient_count", 0) > 0, True)
    check("results_json 非空", len(s3.get("results_json", "[]")) > 2, True)  # 至少是 "[]"

    # 验证 results_json 可解析
    results = json.loads(s3["results_json"])
    check("results_json 可解析为列表", isinstance(results, list), True)
    check("结果条目数 = 3", len(results), 3)

    # 酒精应该被识别（市场俗名→乙醇）
    alcohol = [r for r in results if "酒精" in r.get("original_input", "") or "乙醇" in r.get("ingredient", "")]
    check("酒精被识别", len(alcohol) > 0, True)

    # ── S4: 风险分级 ──
    s4 = await run_node("risk_engine", {
        "results_json": s3["results_json"],
        "domestic_or_imported": s1["domestic_or_imported"],
        "target_claims": s1["target_claims"],
        "medical_keyword_hit": False,
        "historical_rejection": False,
        "prior_market_flag": False,
        "regulation_circumvention": False,
        "kb_table_expired": False,
    })
    print("\n── S4 风险分级 ──")
    check("risk_level 非空", len(s4.get("risk_level", "")) > 0, True)
    check("risk_level in R1/R2", s4.get("risk_level") in ("R1", "R2"), True)
    check("can_quote", s4.get("can_quote"), True)
    check("human_review_required 存在", "human_review_required" in s4, True)

    risk_level = s4["risk_level"]
    print(f"  → 风险等级: {risk_level}")

    # ── S5: 检测方案 ──
    s5 = await run_node("test_plan_generator", {
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
        "dosage_form": s1["dosage_form"],
        "target_claims": s1["target_claims"],
        "risk_level": risk_level,
    })
    print("\n── S5 检测方案 ──")
    check("safety_blocked=False", s5.get("safety_blocked"), False)
    check("test_total_count > 0", s5.get("test_total_count", 0) > 0, True)
    check("test_summary 非空", len(s5.get("test_summary", "")) > 0, True)

    # 验证 test_items_json 可解析
    items = json.loads(s5["test_items_json"])
    check("test_items_json 可解析为列表", isinstance(items, list), True)
    check("检测项数量 > 0", len(items) > 0, True)
    # 验证每个 item 有 code/name/category/standard
    for item in items:
        for k in ("code", "name", "category", "standard"):
            if k not in item:
                check(f"检测项含 {k}", False, True)
                break
        else:
            continue
        break
    else:
        check("所有检测项结构完整", True, True)

    # ── S6: 报价预估 ──
    s6 = await run_node("s6_pricing", {
        "test_items_json": s5["test_items_json"],
        "risk_level": risk_level,
        "customer_type": s1["customer_type"],
        "urgency_level": s1["urgency_level"],
        "safety_blocked": False,
    })
    print("\n── S6 报价预估 ──")
    check("is_priced=True", s6.get("is_priced"), True)
    check("standard_total > 0", s6.get("standard_total", 0) > 0, True)
    check("total > 0", s6.get("total", 0) > 0, True)
    check("cycle 非空", len(s6.get("cycle", "")) > 0, True)
    check("pricing_table 非空", len(s6.get("pricing_table", "")) > 0, True)

    # 品牌方85折验证：subtotal < standard_total
    check("品牌方有折扣", s6.get("subtotal") < s6.get("standard_total"), True)

    print(f"  → 标准总价: ¥{s6['standard_total']:,}")
    print(f"  → 折后总计(含税): ¥{s6['total']:,}")
    print(f"  → 周期: {s6['cycle']}")

    # ── S7: 预审摘要 ──
    s7 = await run_node("summary_generator", {
        "product_name": s1["product_name"],
        "dosage_form": s1["dosage_form"],
        "domestic_or_imported": s1["domestic_or_imported"],
        "target_claims": s1["target_claims"],
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
        "results_json": s3["results_json"],
        "risk_level": risk_level,
        "risk_label": s4.get("risk_label", ""),
        "trigger_labels_json": s4.get("trigger_labels_json", "[]"),
        "trigger_details_json": s4.get("trigger_details_json", "[]"),
        "test_total_count": s5["test_total_count"],
        "test_summary": s5["test_summary"],
        "safety_blocked": s5.get("safety_blocked", False),
        "safety_detail": s5.get("safety_detail", ""),
        "non_standard": s5.get("non_standard", ""),
        "pricing_total": s6["total"],
        "pricing_cycle": s6["cycle"],
        "is_priced": s6["is_priced"],
        "pricing_notes": s6.get("notes", ""),
    })
    print("\n── S7 预审摘要 ──")
    check("report_ready=True", s7.get("report_ready"), True)
    check("markdown_report 非空", len(s7.get("markdown_report", "")) > 100, True)
    check("summary_json 非空", len(s7.get("summary_json", "{}")) > 2, True)
    check("next_steps 非空", len(s7.get("next_steps", "")) > 0, True)

    # 关键内容检查
    report = s7["markdown_report"]
    check_contains("报告含产品名称", report, "维达免洗洗手液")
    check_contains("报告含品类", report, "第二类")
    check_contains("报告含风险等级", report, risk_level)
    check_contains("报告含费用预估", report, "费用预估")

    # 验证 summary_json 可解析
    summary = json.loads(s7["summary_json"])
    check("summary_json 可解析", isinstance(summary, dict), True)
    check("summary 含 pricing", "pricing" in summary, True)

    print(f"\n  ✅ 场景 A 全链路通过（S1→S2→S3→S4→S5→S6→S7）")
    return True


# ═══════════════════════════════════════════════════════════════
# 场景 B: R3 阻断路径（医疗宣称）
# ═══════════════════════════════════════════════════════════════

async def test_scenario_b():
    """
    产品含医疗宣称 + 历史退单 → R3 阻断
    预期: S4→R3, S5→safety_blocked, S6→is_priced=False, S7→阻断报告
    """
    print("\n" + "=" * 60)
    print("  场景 B: R3 阻断路径（医疗宣称 + 历史退单）")
    print("=" * 60)

    # ── S1: 入口解析 ──
    template = """产品名称：XX抑菌凝胶
剂型：凝胶
核心成分：醋酸氯己定（0.2%）、三氯生（0.1%）、纯化水
宣称功效：治疗皮肤感染、杀灭致病菌、促进伤口愈合
产地：国产
您的角色：代工厂
使用场景：医院
已有检测报告：没有
退单历史：有（宣称不合规）
紧急程度：加急"""

    s1 = await run_node("entry_merge", {"structured_text": template})
    print("\n── S1 入口解析 ──")
    check("ready=True", s1.get("ready"), True)

    # ── S2: 分类判定 ──
    s2 = await run_node("classification_decision", {
        "product_name": s1["product_name"],
        "target_claims": s1["target_claims"],
        "dosage_form": s1["dosage_form"],
    })
    print("\n── S2 分类判定 ──")
    # 「XX抑菌凝胶」+ 医疗宣称，分类结果取决于关键词匹配
    # 分类结果不影响下游 R3 阻断路径测试核心目标
    product_category_b = s2.get("product_category", "未分类")
    print(f"  → 品类: {product_category_b}, is_classified: {s2.get('is_classified')}")

    # ── S3: 成分合规检查 ──
    s3 = await run_node("ingredient_compliance", {
        "main_ingredients": s1["main_ingredients"],
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
    })
    print("\n── S3 成分合规检查 ──")
    results = json.loads(s3["results_json"])
    # 氯己定和三氯生都是限用物质
    restricted = [r for r in results if r.get("status") == "restricted"]
    print(f"  → 限用成分数: {len(restricted)}")

    # ── S4: 风险分级 ──
    # 医疗宣称 + 历史退单 → R3
    s4 = await run_node("risk_engine", {
        "results_json": s3["results_json"],
        "domestic_or_imported": s1["domestic_or_imported"],
        "target_claims": s1["target_claims"],
        "medical_keyword_hit": True,     # 触发 R3
        "historical_rejection": True,     # 触发 R3
        "prior_market_flag": False,
        "regulation_circumvention": False,
        "kb_table_expired": False,
    })
    print("\n── S4 风险分级 ──")
    check("risk_level=R3", s4.get("risk_level"), "R3")
    check("can_quote=False", s4.get("can_quote"), False)

    # ── S5: 检测方案（R3 阻断）──
    s5 = await run_node("test_plan_generator", {
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
        "dosage_form": s1["dosage_form"],
        "target_claims": s1["target_claims"],
        "risk_level": "R3",
    })
    print("\n── S5 检测方案（R3 阻断）──")
    check("safety_blocked=True", s5.get("safety_blocked"), True)

    # ── S6: 报价（R3 阻断）──
    s6 = await run_node("s6_pricing", {
        "test_items_json": s5.get("test_items_json", "[]"),
        "risk_level": "R3",
        "customer_type": s1["customer_type"],
        "urgency_level": s1["urgency_level"],
        "safety_blocked": True,
    })
    print("\n── S6 报价（R3 阻断）──")
    check("is_priced=False", s6.get("is_priced"), False)
    check("total=0", s6.get("total"), 0)

    # ── S7: 预审摘要（R3 报告）──
    s7 = await run_node("summary_generator", {
        "product_name": s1["product_name"],
        "dosage_form": s1["dosage_form"],
        "domestic_or_imported": s1["domestic_or_imported"],
        "target_claims": s1["target_claims"],
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
        "results_json": s3["results_json"],
        "risk_level": "R3",
        "risk_label": s4.get("risk_label", "R3 高风险"),
        "trigger_labels_json": s4.get("trigger_labels_json", "[]"),
        "trigger_details_json": s4.get("trigger_details_json", "[]"),
        "test_total_count": s5.get("test_total_count", 0),
        "test_summary": s5.get("test_summary", ""),
        "safety_blocked": True,
        "safety_detail": s5.get("safety_detail", ""),
        "non_standard": s5.get("non_standard", ""),
        "pricing_total": 0,
        "pricing_cycle": "",
        "is_priced": False,
        "pricing_notes": s6.get("notes", ""),
    })
    print("\n── S7 预审摘要（R3）──")
    check("report_ready=True", s7.get("report_ready"), True)

    report = s7["markdown_report"]
    check_contains("报告含 R3", report, "R3")
    # R3 报告应该有关键提示
    has_block_wording = any(kw in report for kw in ["不建议", "不可备案", "高风险", "转人工", "阻断"])
    check("报告含阻断/转人工提示", has_block_wording, True)

    print(f"\n  ✅ 场景 B R3 阻断全链路通过")
    return True


# ═══════════════════════════════════════════════════════════════
# 场景 C: 边界输入 — 最小字段 + 默认值容错
# ═══════════════════════════════════════════════════════════════

async def test_scenario_c():
    """
    最小化输入，验证各节点默认值容错：
    - 仅提供最基础的产品信息
    - customer_type 为空 → 默认"其他"
    - urgency_level 为空 → 默认"普通"
    - 无退单/无报告 → 空字符串
    """
    print("\n" + "=" * 60)
    print("  场景 C: 边界输入 — 最小字段 + 默认值容错")
    print("=" * 60)

    # ── S1: 最简模板 ──
    template = """产品名称：测试湿巾
剂型：湿巾
核心成分：苯扎氯铵（0.1%）、纯化水
宣称功效：清洁
产地：国产
您的角色：未提供"""

    s1 = await run_node("entry_merge", {"structured_text": template})
    print("\n── S1 入口解析 ──")
    # 缺失字段但核心字段有 → ready 应该是 True（待确认 S1 逻辑）
    check("产品名称", s1.get("product_name"), "测试湿巾")
    check("剂型=湿巾", s1.get("dosage_form"), "湿巾")
    # 未提供 customer_type → "其他"
    check("customer_type 默认", s1.get("customer_type") in ("其他", ""), True)
    # urgency_level 未提供 → "普通"
    check("urgency_level 默认", s1.get("urgency_level"), "普通")

    # ── S2: 分类判定 ──
    s2 = await run_node("classification_decision", {
        "product_name": s1["product_name"],
        "target_claims": s1["target_claims"],
        "dosage_form": s1["dosage_form"],
    })
    print("\n── S2 分类判定 ──")
    check("品类非空", len(s2.get("product_category", "")) > 0, True)

    # ── S3: 成分合规 ──
    s3 = await run_node("ingredient_compliance", {
        "main_ingredients": s1["main_ingredients"],
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
    })
    print("\n── S3 成分合规 ──")
    results = json.loads(s3["results_json"])
    check("结果条目 > 0", len(results) > 0, True)
    # 苯扎氯铵是限用物质
    bzk = [r for r in results if "苯扎氯铵" in r.get("ingredient", "")]
    if bzk:
        check("苯扎氯铵=restricted", bzk[0]["status"], "restricted")

    # ── S4: 风险分级（最少布尔标志）──
    s4 = await run_node("risk_engine", {
        "results_json": s3["results_json"],
        "domestic_or_imported": s1["domestic_or_imported"],
        "target_claims": s1["target_claims"],
        # 所有布尔标志省略 → 默认 False
    })
    print("\n── S4 风险分级 ──")
    check("risk_level 存在", len(s4.get("risk_level", "")) > 0, True)

    risk_level = s4["risk_level"]

    # ── S5: 检测方案 ──
    s5 = await run_node("test_plan_generator", {
        "product_category": s2["product_category"],
        "sub_type": s2["sub_type"],
        "dosage_form": s1["dosage_form"],
        "target_claims": s1["target_claims"],
        "risk_level": risk_level,
    })
    print("\n── S5 检测方案 ──")
    check("safety_blocked 存在", "safety_blocked" in s5, True)

    # ── S6: 报价（默认 customer_type/urgency）──
    s6 = await run_node("s6_pricing", {
        "test_items_json": s5.get("test_items_json", "[]"),
        "risk_level": risk_level,
        "customer_type": "",       # 空 → 默认"其他"
        "urgency_level": "",       # 空 → 默认"普通"
    })
    print("\n── S6 报价 ──")
    # 其他客户无折扣，验证 subtotal == standard_total
    if s6.get("is_priced"):
        check("默认无折扣", s6["subtotal"] == s6["standard_total"], True)

    # ── S7: 摘要 ──
    s7 = await run_node("summary_generator", {
        "product_name": s1["product_name"],
        "dosage_form": s1["dosage_form"],
        "domestic_or_imported": s1.get("domestic_or_imported", ""),
        "target_claims": s1.get("target_claims", ""),
        "product_category": s2["product_category"],
        "sub_type": s2.get("sub_type", ""),
        "results_json": s3["results_json"],
        "risk_level": risk_level,
        "risk_label": s4.get("risk_label", ""),
        "trigger_labels_json": s4.get("trigger_labels_json", "[]"),
        "trigger_details_json": s4.get("trigger_details_json", "[]"),
        "test_total_count": s5.get("test_total_count", 0),
        "test_summary": s5.get("test_summary", ""),
        "safety_blocked": s5.get("safety_blocked", False),
        "safety_detail": s5.get("safety_detail", ""),
        "non_standard": s5.get("non_standard", ""),
        "pricing_total": s6.get("total", 0),
        "pricing_cycle": s6.get("cycle", ""),
        "is_priced": s6.get("is_priced", False),
        "pricing_notes": s6.get("notes", ""),
    })
    print("\n── S7 预审摘要 ──")
    check("report_ready=True", s7.get("report_ready"), True)
    check("markdown_report 非空", len(s7.get("markdown_report", "")) > 50, True)

    print(f"\n  ✅ 场景 C 边界输入全链路通过")
    return True


# ═══════════════════════════════════════════════════════════════
# 运行全部场景
# ═══════════════════════════════════════════════════════════════

async def main():
    global PASS, FAIL

    print("=" * 60)
    print("  消字号合规预审引擎 — 全链路集成测试")
    print("  S1 → S2 → S3 → S4 → S5 → S6 → S7")
    print("=" * 60)

    await test_scenario_a()
    await test_scenario_b()
    await test_scenario_c()

    print(f"\n{'=' * 60}")
    print(f"  集成测试结果: {PASS} PASS / {FAIL} FAIL")
    print(f"{'=' * 60}")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
