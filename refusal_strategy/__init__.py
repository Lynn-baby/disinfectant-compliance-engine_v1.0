"""
消字号合规预审引擎 — F4 拒答策略模块。

统一决策引擎整合：
  - F3 安全关键词扫描（硬阻断）
  - 医疗暗示关键词检测（中断+确认）
  - 7 大业务边界场景检测（中断/警告/加速/追问）
  - Gate 变量完整性检查（追问）

使用方式：
  from refusal_strategy.refusal_engine import evaluate

  decision = evaluate(user_input, session_vars)
  if decision.decision == Decision.BLOCK:
      return decision.message
  # 否则继续流程...
"""
