"""
消字号合规预审引擎 — F2 信息采集模块。

管理 6 必采 + 4 选采字段的多轮采集流程：
- field_definitions: 字段 Schema、校验规则
- collection_engine: 采集编排引擎（初始化→合并→校验→追问）

使用方式：
  from info_collection.collection_engine import init_collection, process_turn

  state = init_collection()
  turn = process_turn(user_input, state, newly_extracted=nlu_result)
  if turn.ready_to_advance:
      # 进入 S2 品类判定
"""
