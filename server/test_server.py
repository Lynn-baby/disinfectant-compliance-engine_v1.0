"""
服务端测试 — 不启动真实 HTTP 服务，直接调用 pipeline 和 ocr_service。

用法:
    cd /Users/ml/Desktop/ai_sale_agent001 && python3 server/test_server.py
"""

import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.pipeline import preaudit, PipelineResult

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  — {detail}")


# ═══════════════════════════════════════════════════════════════════
# Test 1: 正常流程 — 75% 酒精消毒液
# ═══════════════════════════════════════════════════════════════════

async def test_normal_flow():
    print("\n── Test 1: 正常流程 — 75% 酒精消毒液 ──")
    result = await preaudit({
        "product_name": "75%酒精消毒液",
        "dosage_form": "液体",
        "main_ingredients": "乙醇、纯化水",
        "target_claims": "消毒",
        "domestic_or_imported": "国产",
        "customer_type": "品牌方",
        "urgency_level": "普通",
    })

    check("流水线成功", result.success)
    check("未阻断", not result.blocked)
    check("S0 通过", result.stages.get("S0", {}).get("blocked") is False)
    check("S1 就绪", result.stages.get("S1", {}).get("ready") is True)
    check("S2 分类完成", result.stages.get("S2", {}).get("is_classified") is True)
    check("S3 成分分析完成", "overall_status" in result.stages.get("S3", {}))
    check("S4 风险分级完成", "risk_level" in result.stages.get("S4", {}))
    check("S5 检测方案生成", "test_total_count" in result.stages.get("S5", {}))
    check("S6 报价成功", result.stages.get("S6", {}).get("is_priced", False))
    check("S7 报告生成", result.stages.get("S7", {}).get("report_ready", False))
    check("含 Markdown 报告", len(result.markdown_report) > 100)
    check("含 JSON 摘要", len(result.summary_json) > 100)


# ═══════════════════════════════════════════════════════════════════
# Test 2: R3 阻断 — 医疗宣称产品
# ═══════════════════════════════════════════════════════════════════

async def test_r3_block():
    print("\n── Test 2: R3 阻断 — 医疗宣称产品 ──")
    result = await preaudit({
        "product_name": "湿疹抑菌喷雾",
        "dosage_form": "液体",
        "main_ingredients": "苯扎氯铵、纯化水",
        "target_claims": "治疗、止痒",
        "domestic_or_imported": "国产",
        "customer_type": "品牌方",
        "urgency_level": "普通",
    })

    check("流水线成功", result.success)
    s4 = result.stages.get("S4", {})
    # R3 风险级别
    risk = s4.get("risk_level", "")
    check(f"风险级别 R3 (实际: {risk})", risk == "R3" or "R3" in str(risk))
    # S5 应被 safety_blocked
    s5 = result.stages.get("S5", {})
    if s5:
        check("S5 安全拦截或 R3 特殊处理", s5.get("safety_blocked", False) or "safety" in str(s5).lower())
    # S6 应不报价
    s6 = result.stages.get("S6", {})
    if s6:
        check("S6 被阻断不报价", not s6.get("is_priced", True))


# ═══════════════════════════════════════════════════════════════════
# Test 3: 缺必填字段返回错误
# ═══════════════════════════════════════════════════════════════════

async def test_missing_fields():
    print("\n── Test 3: 缺必填字段 ──")
    result = await preaudit({
        "product_name": "",
        "dosage_form": "液体",
        "main_ingredients": "",
        "target_claims": "",
    })

    check("返回错误", result.error != "" or not result.success, f"error={result.error}")


# ═══════════════════════════════════════════════════════════════════
# Test 4: 进口产品
# ═══════════════════════════════════════════════════════════════════

async def test_imported():
    print("\n── Test 4: 进口产品 ──")
    result = await preaudit({
        "product_name": "威露士抗菌洗手凝胶",
        "dosage_form": "凝胶",
        "main_ingredients": "乙醇、卡波姆、三氯生",
        "target_claims": "抗菌、消毒",
        "domestic_or_imported": "进口",
        "customer_type": "品牌方",
        "urgency_level": "普通",
    })

    check("流水线成功", result.success)
    s2 = result.stages.get("S2", {})
    check("分类判定完成", "product_category" in s2, f"category={s2.get('product_category', 'N/A')}")
    s4 = result.stages.get("S4", {})
    # 进口 + 三氯生 → 可能 R2 或 R3
    risk = s4.get("risk_level", "")
    check(f"风险级别已判定 (实际: {risk})", risk in ("R1", "R2", "R3"))


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def main():
    global PASS, FAIL
    PASS = 0
    FAIL = 0

    await test_normal_flow()
    await test_r3_block()
    await test_missing_fields()
    await test_imported()

    total = PASS + FAIL
    print(f"\n{'='*50}")
    print(f"  server/test_server.py 结果: {PASS}/{total} PASS")
    if FAIL > 0:
        print(f"  {FAIL} FAILURES")
        sys.exit(1)
    else:
        print(f"  全部通过!")


if __name__ == "__main__":
    asyncio.run(main())
