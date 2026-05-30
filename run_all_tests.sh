#!/bin/bash
# 消字号合规预审引擎 — 全项目测试
# 运行: bash run_all_tests.sh

set -e
cd "$(dirname "$0")"

PASS=0
FAIL=0

run_module() {
    local name="$1"
    local path="$2"
    echo "═══════════════════════════════════════"
    echo "  $name"
    echo "═══════════════════════════════════════"
    if python3 "$path" 2>&1; then
        PASS=$((PASS + 1))
        echo "  ✅ $name 通过"
    else
        FAIL=$((FAIL + 1))
        echo "  ❌ $name 失败"
    fi
    echo ""
}

echo ""
echo "  消字号合规预审引擎 — 全项目测试"
echo "  Phase 1: S0 S1 S2 (Code Nodes)"
echo ""

run_module "S0 安全扫描"       coze_workflow/code_nodes/test_safety_block.py
run_module "S1 入口解析"       coze_workflow/code_nodes/test_entry_merge.py
run_module "S2 分类判定"       coze_workflow/code_nodes/test_classification_decision.py

echo ""
echo "  Phase 2: F2 F3 F4 F5 F6 F7"
echo ""

run_module "F2 信息采集"       info_collection/test_suite.py
run_module "F3 反幻觉策略"     anti_hallucination/test_suite.py
run_module "F4 拒答策略"       refusal_strategy/test_suite.py
run_module "F5 输出模板"       output_templates/test_suite.py
run_module "F6 状态机"         state_machine/test_suite.py
run_module "F7 风险分级"       risk_grading/test_suite.py

echo "═══════════════════════════════════════"
echo "  模块: $((PASS + FAIL)) 个, 通过: $PASS, 失败: $FAIL"
echo "═══════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
