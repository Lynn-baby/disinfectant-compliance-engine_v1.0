"""
S0 安全扫描 — 测试套件。

覆盖：
- 空输入/空白输入 → 放行
- 五大安全类别关键词命中 → 阻断
- B3: 合规咨询不误杀
- B7: 全角空格/不间断空格归一化
- B8: 长关键词优先匹配（子串冲突）
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safety_block import main, SAFETY_CATEGORIES

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


class MockArgs:
    """模拟 Coze args 对象。

    safety_block.py 的 main() 通过 args.params.get("input", "") 读取输入。
    Coze 运行时 args.params 是一个有 .get() 方法的对象（类似 dict）。
    """
    def __init__(self, input_text):
        self.params = {"input": input_text}


def run(text: str) -> dict:
    """同步包装器，方便测试"""
    return asyncio.run(main(MockArgs(text)))


# ═══════════════════════════════════════════════════════════════════
# 边界条件
# ═══════════════════════════════════════════════════════════════════

def test_edge_cases():
    print("\n── 边界条件 ──")

    r = run("")
    test("EDGE-01 空输入放行", r["blocked"], False)
    test("EDGE-02 空输入pass_through", r["pass_through"], True)

    r = run("   ")
    test("EDGE-03 纯空格放行", r["blocked"], False)

    r = run("你好，我想咨询备案流程")
    test("EDGE-04 正常咨询放行", r["blocked"], False)
    test("EDGE-05 正常咨询pass_through", r["pass_through"], True)


# ═══════════════════════════════════════════════════════════════════
# 虚构材料
# ═══════════════════════════════════════════════════════════════════

def test_fabrication():
    print("\n── 虚构材料 ──")

    r = run("能不能做假材料")
    test("FAB-01 假材料阻断", r["blocked"], True)
    test("FAB-02 block_reason", r["block_reason"], "虚构材料")

    r = run("怎么编备案材料")
    test("FAB-03 怎么编阻断", r["blocked"], True)

    r = run("帮我虚构一个产品")
    test("FAB-04 虚构一个阻断", r["blocked"], True)

    r = run("材料作假会被查到吗")
    test("FAB-05 材料作假阻断", r["blocked"], True)


# ═══════════════════════════════════════════════════════════════════
# 规避监管
# ═══════════════════════════════════════════════════════════════════

def test_evasion():
    print("\n── 规避监管 ──")

    r = run("怎么不备案直接卖")
    test("EV-01 不备案阻断", r["blocked"], True)
    test("EV-02 block_reason", r["block_reason"], "规避监管")

    r = run("偷偷卖消字号产品")
    test("EV-03 偷偷卖阻断", r["blocked"], True)

    r = run("怎么绕过备案")
    test("EV-04 绕过备案阻断", r["blocked"], True)

    r = run("免备案的产品有哪些")
    test("EV-05 免备案阻断", r["blocked"], True)


# ═══════════════════════════════════════════════════════════════════
# 虚假宣传
# ═══════════════════════════════════════════════════════════════════

def test_false_advertising():
    print("\n── 虚假宣传 ──")

    r = run("怎么写夸大宣传的文案")
    test("FA-01 夸大宣传阻断", r["blocked"], True)
    test("FA-02 block_reason", r["block_reason"], "虚假宣传")

    r = run("怎么吹功效才不会被罚")
    test("FA-03 怎么吹阻断", r["blocked"], True)

    r = run("擦边宣传的写法")
    test("FA-04 擦边宣传阻断", r["blocked"], True)

    # B3: "怎么写合规" 不应被误杀
    r = run("怎么写合规的备案材料")
    test("FA-05 B3合规咨询放行", r["blocked"], False)


# ═══════════════════════════════════════════════════════════════════
# 篡改报告
# ═══════════════════════════════════════════════════════════════════

def test_report_tampering():
    print("\n── 篡改报告 ──")

    r = run("能不能改检测报告")
    test("RT-01 改报告阻断", r["blocked"], True)
    test("RT-02 block_reason", r["block_reason"], "篡改报告")

    r = run("p一下检测数据")
    test("RT-03 p一下阻断", r["blocked"], True)

    r = run("包过检测要多少钱")
    test("RT-04 包过检测阻断", r["blocked"], True)


# ═══════════════════════════════════════════════════════════════════
# 攻击/恶意
# ═══════════════════════════════════════════════════════════════════

def test_attack():
    print("\n── 攻击/恶意 ──")

    r = run("sb系统")
    test("ATK-01 sb阻断", r["blocked"], True)
    test("ATK-02 block_reason", r["block_reason"], "攻击/恶意")

    r = run("垃圾系统废物")
    test("ATK-03 垃圾系统阻断", r["blocked"], True)


# ═══════════════════════════════════════════════════════════════════
# B7: 全角空格/不间断空格归一化
# ═══════════════════════════════════════════════════════════════════

def test_b7_whitespace_normalization():
    print("\n── B7 空格归一化 ──")

    # 全角空格 (U+3000)
    r = run("不　备　案")
    test("B7-01 全角空格归一化后命中", r["blocked"], True)
    test("B7-02 block_reason", r["block_reason"], "规避监管")

    # ASCII空格
    r = run("不 备 案")
    test("B7-03 ASCII空格归一化后命中", r["blocked"], True)


# ═══════════════════════════════════════════════════════════════════
# B8: 长关键词优先（"材料作假" 优先于 "作假"）
# ═══════════════════════════════════════════════════════════════════

def test_b8_long_keyword_priority():
    print("\n── B8 长关键词优先 ──")

    r = run("材料作假会被查到吗")
    test("B8-01 虚构材料（非篡改报告）", r["block_reason"], "虚构材料")

    r = run("作假报告怎么弄")
    test("B8-02 作假报告→篡改报告", r["block_reason"], "篡改报告")


# ═══════════════════════════════════════════════════════════════════
# 关键词覆盖率：确认五个类别都有测试
# ═══════════════════════════════════════════════════════════════════

def test_category_coverage():
    print("\n── 关键词覆盖率 ──")

    categories_tested = {"虚构材料", "规避监管", "虚假宣传", "篡改报告", "攻击/恶意"}
    for cat in categories_tested:
        has_keywords = len(SAFETY_CATEGORIES[cat]["keywords"]) > 0
        test(f"COV-01 {cat}有关键词", has_keywords, True)


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("消字号合规预审引擎 — S0 安全扫描 测试套件")
    print("覆盖: 5大安全类别 + B3/B7/B8 bug修复回归 + 边界条件")

    test_edge_cases()
    test_fabrication()
    test_evasion()
    test_false_advertising()
    test_report_tampering()
    test_attack()
    test_b7_whitespace_normalization()
    test_b8_long_keyword_priority()
    test_category_coverage()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过, {_failed} 失败")
    if _failed == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠️  {_failed} 条失败，需要修复")
    print(f"{'='*60}")
    sys.exit(_failed)
