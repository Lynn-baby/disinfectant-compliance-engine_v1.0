"""
消字号合规预审引擎 — F6 状态机模块。

8 状态线性流转 + 回退 + 级联 stale + 安全阀。
使用方式：
  from state_machine.state_engine import StateEngine
  from state_machine.state_definitions import State

  engine = StateEngine()
  ctx = engine.init_session()
  result = engine.transition(ctx, State.S1)
"""
