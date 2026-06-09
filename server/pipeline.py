"""
合规预审流水线编排 — 串联 S0→S7 全流程。

复用 coze_workflow/code_nodes/src/ 下的所有 Code Node 模块，
通过统一接口调用，返回每阶段的中间结果 + 最终报告。

用法:
    from server.pipeline import preaudit
    result = await preaudit(product_info_dict)
"""

import sys
import os
import asyncio
import json
import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Optional

# 将 Code Node 源码目录加入 path
_CODE_NODES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "coze_workflow", "code_nodes", "src"
)
if _CODE_NODES_DIR not in sys.path:
    sys.path.insert(0, _CODE_NODES_DIR)


@dataclass
class PipelineResult:
    """流水线执行结果。"""
    success: bool
    blocked: bool = False          # S0 安全阻断
    block_reason: str = ""
    markdown_report: str = ""      # S7 最终报告
    summary_json: str = ""         # S7 JSON 摘要
    stages: dict = field(default_factory=dict)  # {stage: output_dict}
    error: str = ""


class MockArgs:
    """模拟 Coze 运行时的 args 对象。

    兼容两种参数访问模式：
    - args.params.get(key, default) — S0, S4, S5, S7
    - args.params[key]             — S1, S2, S3, S6
    """
    def __init__(self, params: dict):
        self.params = self._Params(params)

    class _Params:
        def __init__(self, d: dict):
            self._d = d
        def get(self, key, default=None):
            return self._d.get(key, default)
        def __getitem__(self, key):
            return self._d[key]
        def __contains__(self, key):
            return key in self._d


# ── 医疗暗示关键词（用于 API 模式下的 target_claims 检测）──
# 与 refusal_strategy/medical_keywords.py 保持同步
_MEDICAL_CLAIM_PATTERNS = [
    "治疗", "医治", "治愈", "诊疗", "药用", "药品", "药物",
    "消炎", "消肿", "止痛", "止痒", "止血",
    "抗病毒", "杀病毒", "杀灭病毒",
    "抗癌", "抗肿瘤",
    "促进愈合", "伤口愈合", "加速愈合",
    "提高免疫力", "增强免疫",
    "术前消毒", "术后消毒", "手术消毒", "伤口消毒",
    "深层杀菌", "彻底灭菌",
]


def _detect_medical_claim(text: str) -> bool:
    """检测 target_claims 中是否含医疗暗示关键词。"""
    if not text:
        return False
    for pat in _MEDICAL_CLAIM_PATTERNS:
        if pat in text:
            return True
    return False


async def preaudit(product_info: dict, user_input: str = "") -> PipelineResult:
    """执行完整的合规预审流水线。

    Args:
        product_info: 产品信息 dict，包含:
            - product_name (必填)
            - dosage_form (必填)
            - main_ingredients (必填)
            - target_claims
            - domestic_or_imported
            - customer_type
            - urgency_level
        user_input: 用户原始输入文本（用于 S0 安全扫描）

    Returns:
        PipelineResult 包含全部阶段结果和最终报告
    """
    result = PipelineResult(success=False, stages={})

    try:
        # ── S0: 安全扫描 ──
        if user_input:
            s0_result = await _run_node(
                "s0_safety_block", {"input": user_input}
            )
            result.stages["S0"] = s0_result
            if s0_result.get("blocked"):
                result.blocked = True
                result.block_reason = s0_result.get("block_reason", "安全扫描命中")
                result.success = True  # 成功执行了阻断
                return result
        else:
            result.stages["S0"] = {"blocked": False, "pass_through": True}

        # ── S1: 入口解析 ──
        # 对于 API 直接提交模式，跳过模板解析，直接用传入参数
        s1_ready = {
            "ready": True,
            "product_name": product_info.get("product_name", ""),
            "dosage_form": product_info.get("dosage_form", "液体"),
            "main_ingredients": product_info.get("main_ingredients", ""),
            "target_claims": product_info.get("target_claims", ""),
            "domestic_or_imported": product_info.get("domestic_or_imported", "国产"),
            "customer_type": product_info.get("customer_type", "品牌方"),
            "urgency_level": product_info.get("urgency_level", "普通"),
            "error_message": "",
        }
        if not s1_ready["product_name"] or not s1_ready["main_ingredients"]:
            result.error = "缺少必填字段: product_name 和 main_ingredients 为必填"
            result.stages["S1"] = s1_ready
            return result
        result.stages["S1"] = s1_ready

        # ── S2: 分类判定 ──
        s2_result = await _run_node("s2_classification_decision", {
            "product_name": s1_ready["product_name"],
            "target_claims": s1_ready["target_claims"],
            "dosage_form": s1_ready["dosage_form"],
        })
        result.stages["S2"] = s2_result

        if not s2_result.get("is_classified"):
            result.success = True
            result.error = s2_result.get("error_message", "分类失败")
            return result

        # ── S3: 成分合规 ──
        s3_result = await _run_node("s3_ingredient_compliance", {
            "main_ingredients": s1_ready["main_ingredients"],
            "product_category": s2_result.get("product_category", "第二类"),
            "sub_type": s2_result.get("sub_type", ""),
        })
        result.stages["S3"] = s3_result

        # ── S4: 风险分级 ──
        s4_result = await _run_node("s4_risk_engine", {
            "results_json": s3_result.get("results_json", "[]"),
            "domestic_or_imported": s1_ready["domestic_or_imported"],
            "target_claims": s1_ready["target_claims"],
            "medical_keyword_hit": _detect_medical_claim(s1_ready["target_claims"]),
            "historical_rejection": False,
            "prior_market_flag": False,
            "regulation_circumvention": False,
            "kb_table_expired": False,
        })
        result.stages["S4"] = s4_result

        risk_level = s4_result.get("risk_level", "R1")

        # ── S5: 检测方案 ──
        s5_result = await _run_node("s5_test_plan_generator", {
            "product_category": s2_result.get("product_category", "第二类"),
            "sub_type": s2_result.get("sub_type", ""),
            "dosage_form": s1_ready["dosage_form"],
            "target_claims": s1_ready["target_claims"],
            "risk_level": risk_level,
        })
        result.stages["S5"] = s5_result

        # ── S6: 报价预估 ──
        s6_result = await _run_node("s6_pricing", {
            "test_items_json": s5_result.get("test_items_json", "[]"),
            "test_total_count": s5_result.get("test_total_count", 0),
            "safety_blocked": s5_result.get("safety_blocked", False),
            "safety_detail": s5_result.get("safety_detail", ""),
            "risk_level": risk_level,
            "customer_type": s1_ready["customer_type"],
            "urgency_level": s1_ready["urgency_level"],
        })
        result.stages["S6"] = s6_result

        # ── S7: 预审摘要 ──
        s7_result = await _run_node("s7_summary_generator", {
            "product_name": s1_ready["product_name"],
            "dosage_form": s1_ready["dosage_form"],
            "domestic_or_imported": s1_ready["domestic_or_imported"],
            "target_claims": s1_ready["target_claims"],
            "product_category": s2_result.get("product_category", ""),
            "sub_type": s2_result.get("sub_type", ""),
            "results_json": s3_result.get("results_json", "[]"),
            "risk_level": risk_level,
            "risk_label": s4_result.get("risk_label", ""),
            "trigger_labels_json": s4_result.get("trigger_labels_json", "[]"),
            "trigger_details_json": s4_result.get("trigger_details_json", "[]"),
            "test_total_count": s5_result.get("test_total_count", 0),
            "test_summary": s5_result.get("test_summary", ""),
            "safety_blocked": s5_result.get("safety_blocked", False),
            "safety_detail": s5_result.get("safety_detail", ""),
            "non_standard": s5_result.get("non_standard", ""),
            "pricing_total": s6_result.get("total", 0),
            "pricing_cycle": s6_result.get("cycle", ""),
            "is_priced": s6_result.get("is_priced", False),
            "pricing_notes": s6_result.get("notes", ""),
        })
        result.stages["S7"] = s7_result

        result.success = True
        result.markdown_report = s7_result.get("markdown_report", "")
        result.summary_json = s7_result.get("summary_json", "{}")

    except Exception as e:
        result.error = f"流水线执行异常: {str(e)}"

    return result


async def _run_node(module_name: str, params: dict) -> dict:
    """加载 Code Node 模块并调用 main(args)，返回结果 dict。

    使用 importlib 动态导入，确保从 _CODE_NODES_DIR 加载。
    每个模块通过 async def main(args) -> dict 接收 Coze 标准参数。
    """
    try:
        mod = importlib.import_module(module_name)
        args = MockArgs(params)
        result = await mod.main(args)
        return result
    except ImportError as e:
        return {"error": f"{module_name} 导入失败: {str(e)} (检查文件是否存在于 {_CODE_NODES_DIR})"}
    except Exception as e:
        import traceback
        return {
            "error": f"{module_name} 执行失败: {str(e)}",
            "_traceback": traceback.format_exc()[-500:],
        }
