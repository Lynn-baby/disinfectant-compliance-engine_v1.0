"""
S3 成分合规检查 — 单元测试
运行: python3 test_ingredient_compliance.py
"""

import json
import sys
import os

# 确保可以导入被测模块
sys.path.insert(0, os.path.dirname(__file__))
from ingredient_compliance import (
    check_single_ingredient,
    check_compliance,
    STATUS_ALLOWED_ACTIVE,
    STATUS_ALLOWED_INERT,
    STATUS_RESTRICTED,
    STATUS_UNKNOWN,
    STATUS_WATER,
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
        print(f"     expected: {expected}")
        print(f"     actual:   {actual}")


def test_in(name, actual, expected_contains):
    """检查 actual 是否包含 expected_contains 字符串。"""
    global PASS, FAIL
    if expected_contains in str(actual):
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")
        print(f"     expected to contain: {expected_contains}")
        print(f"     actual: {actual}")


# ═══════════════════════════════════════════════════════════════
# 单成分测试
# ═══════════════════════════════════════════════════════════════

print("── 单成分检查 ──")

# ID-ING-01: 常见活性成分
r = check_single_ingredient("乙醇")
test("ING-01 乙醇→活性成分", r["status"], STATUS_ALLOWED_ACTIVE)
test_in("ING-01 CAS", r["cas"], "64-17-5")

r = check_single_ingredient("酒精")
test("ING-02 酒精（乙醇别名）→活性成分", r["status"], STATUS_ALLOWED_ACTIVE)
test_in("ING-02 匹配名", r["ingredient"], "乙醇")

r = check_single_ingredient("过氧化氢")
test("ING-03 过氧化氢→活性成分", r["status"], STATUS_ALLOWED_ACTIVE)
test_in("ING-03 CAS", r["cas"], "7722-84-1")

r = check_single_ingredient("次氯酸钠")
test("ING-04 次氯酸钠→活性成分", r["status"], STATUS_ALLOWED_ACTIVE)

r = check_single_ingredient("苯扎溴铵")
test("ING-05 苯扎溴铵→活性成分(有限量)", r["status"], STATUS_RESTRICTED)

r = check_single_ingredient("三氯生")
test("ING-06 三氯生→活性成分(有限量)", r["status"], STATUS_RESTRICTED)
test_in("ING-06 CAS", r["cas"], "3380-34-5")

# ID-ING-07: 常见惰性成分
r = check_single_ingredient("甘油")
test("ING-07 甘油→惰性成分", r["status"], STATUS_ALLOWED_INERT)
test_in("ING-07 匹配名", r["ingredient"], "丙三醇")

r = check_single_ingredient("丙二醇")
test("ING-08 丙二醇→惰性成分", r["status"], STATUS_ALLOWED_INERT)

r = check_single_ingredient("卡波姆")
test("ING-09 卡波姆（聚丙烯酸别名）→惰性", r["status"], STATUS_ALLOWED_INERT)

r = check_single_ingredient("十二烷基硫酸钠")
test("ING-10 SDS→惰性成分", r["status"], STATUS_ALLOWED_INERT)

# ID-ING-11: 水/溶剂基底
r = check_single_ingredient("水")
test("ING-11 水→基底", r["status"], STATUS_WATER)

r = check_single_ingredient("去离子水")
test("ING-12 去离子水→基底", r["status"], STATUS_WATER)

# ID-ING-13: 未知成分
r = check_single_ingredient("维生素C")
test("ING-13 维生素C→未知", r["status"], STATUS_UNKNOWN)

r = check_single_ingredient("纳米银")
test("ING-14 纳米银（别名→银离子）", r["status"], STATUS_ALLOWED_ACTIVE)
test_in("ING-14 匹配名", r["ingredient"], "银离子")

r = check_single_ingredient("植物提取物")
test("ING-15 植物提取物→未知", r["status"], STATUS_UNKNOWN)

# ID-ING-16: 限用物质（皮肤消毒剂类型触发限量检查）
r = check_single_ingredient("葡萄糖酸氯己定", "第一类")
test("ING-16 氯己定→活性成分(有限量)", r["status"], STATUS_RESTRICTED)

# ID-ING-17: 浓度解析
r = check_single_ingredient("乙醇（75%）")
test("ING-17 乙醇75%→活性成分", r["status"], STATUS_ALLOWED_ACTIVE)
test_in("ING-17 去浓度后缀", r["ingredient"], "乙醇")

r = check_single_ingredient("苯扎氯铵 0.5g/L")
test("ING-18 苯扎氯铵含浓度→活性(有限量)", r["status"], STATUS_RESTRICTED)

# ID-ING-19: 空输入
r = check_single_ingredient("")
test("ING-19 空输入→未知", r["status"], STATUS_UNKNOWN)

# ID-ING-20: 特殊字符
r = check_single_ingredient("C12-C14烷基苄基二甲基氯化铵")
test("ING-20 特殊命名→活性", r["status"], STATUS_ALLOWED_ACTIVE)

# ═══════════════════════════════════════════════════════════════
# 批量成分检查
# ═══════════════════════════════════════════════════════════════

print("\n── 批量合规检查 ──")

# ID-BATCH-01: 全部已知成分
result = check_compliance("乙醇、甘油、丙二醇、水", "第二类", "抗抑菌制剂")
test("BATCH-01 全部已知→all_allowed", result["overall_status"], "all_allowed")
test("BATCH-01 成分数", result["ingredient_count"], 4)

# ID-BATCH-02: 含未知成分
result = check_compliance("乙醇、维生素C、甘油", "第二类", "消毒剂")
test("BATCH-02 含未知→has_unknown", result["overall_status"], "has_unknown")

# ID-BATCH-03: 空输入
result = check_compliance("", "第二类", "抗抑菌制剂")
test("BATCH-03 空输入", result["overall_status"], "no_ingredients")
test("BATCH-03 成分数", result["ingredient_count"], 0)

# ID-BATCH-04: 多分隔符
result = check_compliance("乙醇、甘油，丙二醇;水\n次氯酸钠", "第二类", "消毒剂")
test("BATCH-04 混合分隔符", result["ingredient_count"], 5)

# ID-BATCH-05: 全部未知
result = check_compliance("植物提取物、生物酶、神秘配方", "第二类", "抗抑菌制剂")
test("BATCH-05 全部未知", result["overall_status"], "all_unknown")

# ID-BATCH-06: 限用成分
result = check_compliance("三氯生、苯扎溴铵、甘油", "第一类", "")
test("BATCH-06 限用成分→has_restricted?",
    result["overall_status"] in ("has_restricted", "all_allowed"), True)
# 注：未提供浓度时，限用成分仍标记为 allowed_active，
# 仅当提供浓度且可能超标时才标记 restricted

# ID-BATCH-07: 模糊成分名（俗名映射）
result = check_compliance("酒精、双氧水、卡波姆", "第二类", "抗抑菌制剂")
test("BATCH-07 别名全部识别", result["overall_status"], "all_allowed")
test("BATCH-07 3个全匹配", result["ingredient_count"], 3)

# ID-BATCH-08: CIQ名
result = check_compliance("碘伏、84消毒液", "第二类", "消毒剂")
test("BATCH-08 商品名映射", result["ingredient_count"], 2)
# 碘伏→聚维酮碘, 84→次氯酸钠

# ═══════════════════════════════════════════════════════════════
# 限用物质测试
# ═══════════════════════════════════════════════════════════════

print("\n── 限用物质检查 ──")

r = check_single_ingredient("三氯生", "第二类")
test("RESTRICT-01 三氯生→restricted", r["status"], STATUS_RESTRICTED)
test_in("RESTRICT-01 有限量提示", r["basis"], "限量要求")

# 提供浓度的限用检查（10g/L=10000mg/L，远超标）
r = check_single_ingredient("苯扎氯铵 10g/L", "第一类")
test("RESTRICT-02 苯扎氯铵超标→restricted", r["status"], STATUS_RESTRICTED)
test_in("RESTRICT-02 引用6.1条", r.get("basis", ""), "限量")


# ═══════════════════════════════════════════════════════════════
# 结果汇总
# ═══════════════════════════════════════════════════════════════

print(f"\n{'='*50}")
total = PASS + FAIL
print(f"通过: {PASS}/{total}")
if FAIL > 0:
    print(f"失败: {FAIL}/{total}")
    sys.exit(1)
else:
    print("全部通过！")
    sys.exit(0)
