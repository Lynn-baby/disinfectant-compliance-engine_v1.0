"""
消字号合规预审引擎 — F3 反幻觉策略模块。

三层控制系统：
  Layer 1 (硬阻断): safety_keywords + gate_check
  Layer 2 (强约束): nlu_prompt_template + main_model_prompt_template
  Layer 3 (校验层): output_verifier

使用方式：
  from anti_hallucination.safety_keywords import scan_safety_keywords
  from anti_hallucination.gate_check import check_gate
  from anti_hallucination.output_verifier import verify_output
"""
