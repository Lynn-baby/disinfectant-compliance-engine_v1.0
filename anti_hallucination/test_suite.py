"""
反幻觉策略 — 完整测试套件。

覆盖 PRD 10.2 定义的单元测试：
- 10.2.1 安全关键词扫描（15 条）
- 10.2.2 Gate 变量完整性检查（10 条）
- 10.2.3 风险判定查表（12 条）
- 10.2.4 成分合规查表（6 条）
- 输出校验层（8 条）
- Gate 冲突检测与回退（5 条）

运行方式：
    python3 anti_hallucination/test_suite.py
    或
    python3 -m pytest anti_hallucination/test_suite.py -v
"""

import sys
import os

# 确保项目根在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anti_hallucination.safety_keywords import scan_safety_keywords, detect_potential_variants
from anti_hallucination.gate_check import (
    check_gate,
    get_rollback_state,
    get_stale_states,
    REQUIRED_FIELDS,
)
from anti_hallucination.output_verifier import verify_output

# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════

_passed = 0
_failed = 0


def test(name: str, actual, expected):
    """简易断言，打印每个用例结果"""
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


def summary():
    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    return _failed


# ═══════════════════════════════════════════════════════════════════
# 10.2.1 安全关键词扫描（15 条）
# ═══════════════════════════════════════════════════════════════════

def test_safety_scan():
    print("\n── 10.2.1 安全关键词扫描 ──")

    # 命中类
    test("ID-SEC-01 绕备案",
         scan_safety_keywords("怎么绕备案").blocked, True)
    test("ID-SEC-02 不留痕迹",
         scan_safety_keywords("能不能不留痕迹").blocked, True)
    test("ID-SEC-03 擦边宣传",
         scan_safety_keywords("怎么写擦边宣传").blocked, True)
    test("ID-SEC-04 夸大效果",
         scan_safety_keywords("可以夸大效果吗").blocked, True)
    test("ID-SEC-05 改检测报告",
         scan_safety_keywords("改检测报告怎么弄").blocked, True)
    test("ID-SEC-06 p一下检测",
         scan_safety_keywords("帮我p一下检测结果").blocked, True)
    test("ID-SEC-07 虚构材料",
         scan_safety_keywords("虚构一个备案材料").blocked, True)

    # 正常放行
    test("ID-SEC-08 正常产品咨询",
         scan_safety_keywords("帮我看看这个洗手液").blocked, False)
    test("ID-SEC-09 备案周期",
         scan_safety_keywords("备案要多久").blocked, False)
    test("ID-SEC-10 检测项目",
         scan_safety_keywords("检测项目有哪些").blocked, False)

    # 边界
    test("ID-SEC-11 规避词嵌在长文本中",
         scan_safety_keywords("我想问一下，如果是一个新产品，不备案会怎样").blocked, True)
    test("ID-SEC-12 空输入",
         scan_safety_keywords("").blocked, False)
    test("ID-SEC-13 纯空白",
         scan_safety_keywords("   ").blocked, False)
    test("ID-SEC-14 纯英文",
         scan_safety_keywords("what is the price for testing").blocked, False)
    test("ID-SEC-15 正常含'备案'关键词",
         scan_safety_keywords("帮我看看能不能备案").blocked, False)

    # block_reason 正确性
    result = scan_safety_keywords("怎么绕备案")
    test("ID-SEC-reason-01 规避监管",
         result.block_reason, "规避监管")
    test("ID-SEC-reason-02 虚假宣传",
         scan_safety_keywords("怎么写夸大功效").block_reason, "虚假宣传")


# ═══════════════════════════════════════════════════════════════════
# 10.2.2 Gate 变量完整性检查（10 条）
# ═══════════════════════════════════════════════════════════════════

def test_gate():
    print("\n── 10.2.2 Gate 变量完整性检查 ──")

    # 全填满 → 放行
    full = {
        "product_name": "免洗洗手液",
        "dosage_form": "液体",
        "main_ingredients": ["酒精"],
        "target_claims": ["抑菌"],
        "domestic_or_imported": "国产",
        "customer_type": "品牌方",
    }
    test("ID-GATE-01 全填满",
         check_gate(full).passed, True)

    # 单字段缺失
    for field in REQUIRED_FIELDS:
        incomplete = dict(full)
        incomplete[field] = None
        result = check_gate(incomplete)
        test(f"ID-GATE-02~07 {field} 缺失",
             result.passed, False)

    # 全空
    test("ID-GATE-08 全空", check_gate({}).passed, False)

    # 3 填 3 空
    half = {"product_name": "测试", "dosage_form": "液体", "customer_type": "品牌方"}
    result = check_gate(half)
    test("ID-GATE-09 3填3空", result.passed, False)
    test("ID-GATE-09 缺失3字段",
         len(result.missing_fields), 3)

    # 5 填 1 空
    five = dict(full)
    five["customer_type"] = None
    result = check_gate(five)
    test("ID-GATE-10 5填1空",
         result.passed, False)


# ═══════════════════════════════════════════════════════════════════
# Gate 变量冲突检测（5 条）
# ═══════════════════════════════════════════════════════════════════

def test_conflict_detection():
    print("\n── Gate 变量冲突检测 ──")

    full_vars = {
        "product_name": "洗手液",
        "dosage_form": "液体",
        "main_ingredients": ["酒精"],
        "target_claims": ["抑菌"],
        "domestic_or_imported": "国产",
        "customer_type": "品牌方",
    }

    # 无冲突
    new = {"main_ingredients": ["酒精"]}
    result = check_gate(full_vars, newly_extracted=new)
    test("CONFLICT-01 相同值不触发冲突",
         len(result.conflict_fields), 0)

    # 有冲突
    new = {"main_ingredients": ["苯扎氯铵"]}
    result = check_gate(full_vars, newly_extracted=new)
    test("CONFLICT-02 main_ingredients 变更",
         len(result.conflict_fields), 1)
    test("CONFLICT-02 冲突字段名",
         result.conflict_fields[0]["field"], "main_ingredients")

    # 多字段冲突
    new = {"main_ingredients": ["苯扎氯铵"], "domestic_or_imported": "进口"}
    result = check_gate(full_vars, newly_extracted=new)
    test("CONFLICT-03 多字段冲突",
         len(result.conflict_fields), 2)

    # 回退状态计算
    test("CONFLICT-04 成分变更→回退S3",
         get_rollback_state(["main_ingredients"]), "S3")
    test("CONFLICT-05 成分+产地→回退S2",
         get_rollback_state(["main_ingredients", "domestic_or_imported"]), "S2")


# ═══════════════════════════════════════════════════════════════════
# 10.2.3 风险判定查表（12 条）
# ═══════════════════════════════════════════════════════════════════

def assess_risk(
    ingredient_status: str,
    claims: list[str],
    domestic_or_imported: str,
    historical_rejection: bool = False,
    medical_keyword_hit: bool = False,
    prior_market_flag: bool = False,
) -> str:
    """
    Code Node 风险判定查表函数（PRD 3.4.1 伪代码的实现）。
    注入测试套件而非单独模块，因为正式版本应作为 Code Node 部署。
    """
    if ingredient_status == "prohibited":
        return "R3"
    if medical_keyword_hit:
        return "R3"
    if historical_rejection:
        return "R3"
    if prior_market_flag:
        return "R3"
    if ingredient_status == "unknown":
        return "R2"
    if domestic_or_imported == "进口":
        return "R2"
    return "R1"


def test_risk_assessment():
    print("\n── 10.2.3 风险判定查表 ──")

    test("ID-RISK-01 prohibited→R3",
         assess_risk("prohibited", ["消毒"], "国产"), "R3")
    test("ID-RISK-02 medical→R3",
         assess_risk("allowed", ["治疗湿疹"], "国产", medical_keyword_hit=True), "R3")
    test("ID-RISK-03 rejection→R3",
         assess_risk("allowed", ["消毒"], "国产", historical_rejection=True), "R3")
    test("ID-RISK-04 prior_market→R3",
         assess_risk("allowed", ["消毒"], "国产", prior_market_flag=True), "R3")
    test("ID-RISK-05 unknown→R2",
         assess_risk("unknown", ["消毒"], "国产"), "R2")
    test("ID-RISK-06 imported→R2",
         assess_risk("allowed", ["消毒"], "进口"), "R2")
    test("ID-RISK-07 allowed_normal→R1",
         assess_risk("allowed", ["消毒"], "国产"), "R1")
    test("ID-RISK-08 prohibited+imported→R3",
         assess_risk("prohibited", ["消毒"], "进口"), "R3")
    test("ID-RISK-09 unknown+imported→R2",
         assess_risk("unknown", ["消毒"], "进口"), "R2")
    test("ID-RISK-10 allowed+imported_normal_claims→R2",
         assess_risk("allowed", ["消毒"], "进口"), "R2")
    test("ID-RISK-11 allowed+domestic_normal→R1",
         assess_risk("allowed", ["消毒"], "国产"), "R1")
    test("ID-RISK-12 R3优先(prohibited+imported+rejection)",
         assess_risk("prohibited", ["消毒"], "进口", historical_rejection=True), "R3")


# ═══════════════════════════════════════════════════════════════════
# 10.2.4 成分合规查表（6 条）
# ═══════════════════════════════════════════════════════════════════

def check_ingredient(ingredient: str, kb_hit_result: str) -> dict:
    """
    Code Node 成分合规查表函数（PRD 3.4.1 伪代码的实现）。
    """
    if kb_hit_result == "in_allowed_list":
        return {"name": ingredient, "status": "allowed", "reference": "《消毒剂原料清单》"}
    if kb_hit_result == "in_prohibited_list":
        return {"name": ingredient, "status": "prohibited", "reference": "《消毒剂原料清单》禁限用物质"}
    if kb_hit_result == "no_hit":
        return {"name": ingredient, "status": "unknown", "reference": "现行消字号法规目录中暂无明确收录"}
    return {"name": ingredient, "status": "error", "reference": ""}


def test_ingredient_check():
    print("\n── 10.2.4 成分合规查表 ──")

    test("ID-ING-01 酒精→allowed",
         check_ingredient("酒精", "in_allowed_list")["status"], "allowed")
    test("ID-ING-02 三氯生→prohibited",
         check_ingredient("三氯生", "in_prohibited_list")["status"], "prohibited")
    test("ID-ING-03 纳米银→unknown",
         check_ingredient("纳米银", "no_hit")["status"], "unknown")
    test("ID-ING-04 引用包含法规编号",
         "《消毒剂原料清单》" in check_ingredient("酒精", "in_allowed_list")["reference"], True)
    test("ID-ING-05 空成分",
         check_ingredient("", "no_hit")["status"], "unknown")
    test("ID-ING-06 特殊字符成分",
         check_ingredient("A/B-123", "no_hit")["status"], "unknown")


# ═══════════════════════════════════════════════════════════════════
# 输出校验层（8 条）
# ═══════════════════════════════════════════════════════════════════

def test_output_verifier():
    print("\n── 输出校验层 ──")

    # 合规输出有引用 + 结构完整 → 通过
    output = "【风险等级】R1 低风险\n【触发条件】成分在允许清单中，国产，无退单历史\n依据《消毒技术规范》和 GB 15979。"
    result = verify_output(output, "S4", contains_compliance_judgment=True)
    test("VERIFY-01 有引用通过", result.passed, True)

    # 合规输出无引用 → 标记
    output = "经分析，您的产品风险等级为 R1 低风险，可以正常备案。"
    result = verify_output(output, "S4", contains_compliance_judgment=True)
    test("VERIFY-02 无引用标记", result.citation_ok, False)

    # 幻觉信号检测
    output = "您这个产品肯定能过备案，绝对没问题。"
    result = verify_output(output, "S4", contains_compliance_judgment=False)
    test("VERIFY-03 幻觉信号", result.safety_ok, False)

    # 结构缺失
    result = verify_output("风险等级 R1", "S4", contains_compliance_judgment=True)
    test("VERIFY-04 缺少触发条件", result.structure_ok, False)

    # 非合规内容不需要引用
    output = "您好，请问有什么可以帮您的？"
    result = verify_output(output, "S0", contains_compliance_judgment=False)
    test("VERIFY-05 非合规通过", result.passed, True)

    # 编造法规模式
    output = "根据行业惯例和一般经验，这个产品应该可以备案。"
    result = verify_output(output, "S4", contains_compliance_judgment=True)
    test("VERIFY-06 编造模式", result.safety_ok, False)

    # 空输出
    result = verify_output("", "S4")
    test("VERIFY-07 空输出不崩溃", result.passed, False)

    # 正常合规输出全通过
    output = (
        "【风险等级】R1 低风险\n"
        "【触发条件】成分在允许清单中，国产，无退单历史\n"
        "根据《消毒剂原料清单》（GB 38850-2020），您的产品成分均在允许使用范围内。"
    )
    result = verify_output(output, "S4", contains_compliance_judgment=True)
    test("VERIFY-08 完整合规通过", result.passed, True)


# ═══════════════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — F3 反幻觉策略 测试套件")
    print(f"测试模块: anti_hallucination/")
    print(f"覆盖: PRD 10.2.1 ~ 10.2.4 + 输出校验 + 冲突检测")

    test_safety_scan()
    test_gate()
    test_conflict_detection()
    test_risk_assessment()
    test_ingredient_check()
    test_output_verifier()

    failed = summary()
    sys.exit(failed)
