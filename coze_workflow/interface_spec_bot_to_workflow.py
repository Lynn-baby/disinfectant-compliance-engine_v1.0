"""
Bot ↔ Workflow 接口契约 v2.0 — 变量传参 + 模板兜底。

架构：主路径用 Coze 原生变量传参（无需 NLU 解析），
      兜底路径用 Markdown 模板（Bot 生成 → NLU 解析）。
      两路数据在 Workflow 入口 Code Node 合并。

======================================================================
  调用模型
======================================================================

Bot 对话采集 6 必采字段 → 调用 Workflow，传入两类参数：

  A 路（主路径）: 7 个独立变量 → 如果全部非空且合法，跳过 NLU
  B 路（兜底）  : structured_text → A 路有缺时 NLU 从这里补

Workflow 入口 Code Node 第一时间做合并决策。

======================================================================
  A 路：独立字段变量（主路径，Bot 尽力填充）
======================================================================

变量名                类型      必填    值域 / 格式
─────────────────────────────────────────────────────────────
product_name          String    是      自由文本
dosage_form           String    是      液体|凝胶|喷雾|湿巾|片剂|粉剂|膏霜|气雾
main_ingredients      String    是      顿号或逗号分隔，如「酒精（75%）、甘油」
target_claims         String    是      顿号或逗号分隔，如「消毒、抑菌」
domestic_or_imported  String    是      "国产" | "进口"
customer_type         String    是      品牌方|代工厂|中介|贸易商|其他
urgency_level         String    否      "普通" | "加急"（默认"普通"）

======================================================================
  B 路：结构化文本兜底（兜底路径，始终传入）
======================================================================

变量名                类型      必填    格式
─────────────────────────────────────────────────────────────
structured_text       String    是      Markdown 模板（格式见下方）

模板格式（Bot 始终生成此文本，不管 A 路是否完整）：

  【产品信息采集结果】

  产品名称：{用户确认的产品名}
  剂型：{归一化后的剂型}
  核心成分：{成分1}、{成分2}、...
  宣称功效：{功效1}、{功效2}、...
  产地：{国产 或 进口}
  客户类型：{品牌方/代工厂/中介/贸易商/其他}

  使用场景：{用户提供的场景，未提供填「未提供」}
  已有检测报告：{有/没有/部分有，未确认填「未提供」}
  退单历史：{用户提供的信息，未提及填「未提供」}
  紧急程度：{普通 或 加急，未提及默认「普通」}

======================================================================
  Workflow 入口 Code Node：合并决策
======================================================================

Workflow 的第一个节点（安全扫描之后）负责合并两路数据：

  def main(args):
      # 1. 检查 A 路是否完整
      required = ["product_name", "dosage_form", "main_ingredients",
                  "target_claims", "domestic_or_imported", "customer_type"]
      a_complete = all(
          args.params.get(f) and str(args.params.get(f)).strip()
          for f in required
      )

      if a_complete and validate_fields(args.params):
          # 快路径：A 路完整且合法，直接使用
          return build_output_from_a(args.params)

      # 2. A 路不全 → 走 B 路兜底
      if not args.params.get("structured_text"):
          return {"ready": False, "error": "A 路不全且 B 路缺失——这是 Bot 的 bug"}

      # 3. B 路 NLU 解析（调 LLM Node 或内置规则）
      parsed = parse_structured_text(args.params["structured_text"])

      # 4. 合并：A 路有值的优先用，缺的从 B 路补
      merged = {}
      for f in required + ["urgency_level"]:
          a_val = args.params.get(f)
          merged[f] = a_val if (a_val and str(a_val).strip()) else parsed.get(f)

      # 5. Gate 检查合并结果
      still_missing = [f for f in required if not merged.get(f)]
      if still_missing:
          return {"ready": False, "missing": still_missing}

      return build_output(merged)

======================================================================
  三条路径的触发场景
======================================================================

路径              触发条件                          NLU 调用    典型场景
──────────────────────────────────────────────────────────────────────
快路径            A 路 6 字段完整 + 合法             0 次        Bot 正常采集完成
兜底路径          A 路不完整，B 路可解析              1 次        Bot 漏填某字段但模板正确
致命失败          A 路不完整 + B 路也解析不出         N/A         Bot 的 Persona Prompt 需要修

======================================================================
  设计优势
======================================================================

- 90%+ 的正常对话走快路径，零额外 LLM 调用
- Bot 填变量出错时有 B 路兜底，不会让用户察觉问题
- 调试时看 A 路变量就知 Bot 提取质量，看 structured_text 就知 Bot 理解是否准确
- 两条路径的差异可以作为监控指标：A 路命中率 < 80% → 需要优化 Bot Prompt

======================================================================
  完整示例：Bot 调用 Workflow
======================================================================

用户通过 4 轮对话提供完所有信息后，Bot 调用 Workflow：

  Workflow 输入:
    product_name        = "维达免洗洗手液"
    dosage_form         = "凝胶"
    main_ingredients    = "酒精（75%）、甘油、卡波姆、纯化水"
    target_claims       = "消毒、抑菌"
    domestic_or_imported = "国产"
    customer_type       = "品牌方"
    urgency_level       = "普通"
    structured_text     = """
      【产品信息采集结果】

      产品名称：维达免洗洗手液
      剂型：凝胶
      核心成分：酒精（75%）、甘油、卡波姆、纯化水
      宣称功效：消毒、抑菌
      产地：国产
      客户类型：品牌方

      使用场景：家庭、医院
      已有检测报告：没有
      退单历史：没有
      紧急程度：普通
      """

  → 快路径：A 路 6 字段全部非空且合法，直接用，0 次 NLU

======================================================================
  示例：兜底路径触发
======================================================================

Bot 在某种边界情况下只填了 4 个变量（漏了 customer_type 和 target_claims）：

  Workflow 输入:
    product_name        = "次氯酸消毒液"
    dosage_form         = "液体"
    main_ingredients    = "次氯酸钠（5%）"
    target_claims       = ""           ← 漏了
    domestic_or_imported = "国产"
    customer_type       = ""           ← 漏了
    structured_text     = """          ← 但模板里是完整的
      【产品信息采集结果】
      ...
      宣称功效：消毒
      ...
      客户类型：品牌方
      ...
      """

  → A 路不全 → 兜底路径：NLU 解析 structured_text，补上 target_claims="消毒" 和 customer_type="品牌方"
  → 最终 merged 6 字段完整 → 快路径效果一致
"""
