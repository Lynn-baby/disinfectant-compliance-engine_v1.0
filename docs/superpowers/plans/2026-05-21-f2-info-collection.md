# F2 信息采集模块 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Coze 平台上搭建消字号合规预审引擎的 S0→S1 信息采集模块，支持双入口（快速报价/先聊再定），完成 6 必采 + 4 选采字段的 NLU 抽取、Gate 校验和追问机制。

**Architecture:** 基于 Coze Workflow 实现。S0 开场白用 LLM Node 做二选一分支，通道 A 输出结构化引导模板，通道 B 跑自由对话。每轮用户输入经 LLM Node（GLM-4-flash）做 NLU 实体抽取，抽取结果写入 Bot 变量。Gate 用 Code Node（JavaScript）校验 6 必采字段完整性，缺则按 P0→P5 优先级追问。

**Tech Stack:** Coze Bot（Workflow + 变量 + Code Node + 快捷回复），GLM-4-flash 用于 NLU 抽取，主模型用于对话生成。

---

## 文件结构

本次全部工作在 Coze 控制台完成，不产生本地代码文件。涉及以下 Coze 组件：

| 组件 | 类型 | 职责 |
|------|------|------|
| Bot 变量池 | Variables | 存储 10 个字段值 + 2 个状态标记 |
| S0_开场白 | LLM Node | 问候 + 二选一分支 |
| S0_路由 | If-Else Node | 判断用户选择 A/B |
| S1A_引导模板 | LLM Node | 通道 A 结构化模板输出 |
| S1A_NLU抽取 | LLM Node | 通道 A 用户提交后抽取字段 |
| S1B_自由对话 | LLM Node | 通道 B 自由咨询回复 |
| S1B_NLU静默抽取 | LLM Node | 通道 B 后台抽取（不暴露给用户） |
| Gate_校验 | Code Node | 6 必采字段完整性 + 冲突检测 |
| Gate_追问 | LLM Node | 按优先级追问缺失字段 |
| 快捷回复 | Quick Reply | "暂时无需报价，先跳过"按钮 |

---

### Task 1: 创建 Bot 变量池

**操作路径:** Coze 控制台 → Bot 设置 → 变量

- [ ] **Step 1: 创建 6 个必采字段变量**

在 Bot 变量面板新增以下变量（类型均为 String，默认值空字符串）：

```
变量名                 类型     默认值   说明
product_name          String   ""       产品名称
dosage_form           String   ""       剂型（液体/片剂/粉剂/凝胶/喷雾/湿巾/其他）
main_ingredients      String   ""       核心成分（INCI 名，逗号分隔）
target_claims         String   ""       宣称功效
domestic_or_imported  String   ""       国产/进口
customer_type         String   ""       品牌方/代工厂/中介/其他
```

- [ ] **Step 2: 创建 4 个选采字段变量**

```
变量名                 类型     默认值   说明
usage_scenarios       String   ""       使用场景
existing_reports      String   ""       是否已有检测报告
historical_rejection  String   ""       是否有退单历史
urgency_level         String   ""       紧急程度（普通/加急）
```

- [ ] **Step 3: 创建 2 个状态标记变量**

```
变量名              类型     默认值   说明
current_channel     String   ""       当前通道：A / B
partial_info        Boolean  false    是否缺字段标记
round_count         Number   0        当前追问轮数
```

- [ ] **Step 4: 截图保存变量面板**

Coze 变量面板完整截图，保存到 `coze_workflow/screenshots/variables.png`。

---

### Task 2: S0 开场白节点（LLM Node）

**操作路径:** Coze 控制台 → Workflow → 新建 → 添加大模型节点

- [ ] **Step 1: 创建 S0 开场白节点**

新建 LLM Node，命名为 `S0_开场白`。

**System Prompt:**

```
你是消字号合规预审助手。用户首次进入时，输出以下开场白（严格按此模板）：

---
您好，我是消字号合规预审助手。您想：

📋 **A. 直接出预审报告** — 提供产品信息，我 2 分钟内输出检测清单和报价区间
💬 **B. 先了解流程** — 聊聊备案要求、检测项目、法规标准

请选择 A 或 B。
---

如果用户之前已在对话中，不要重复输出开场白。检查 Bot 变量 current_channel，若已设置则跳过本节点。
```

**输出变量:** 无需提取变量，直接输出文本。

- [ ] **Step 2: 设置快捷回复选项**

在 Bot 设置 → 快捷回复中，添加两个选项：

```
选项 1: "A. 直接出预审报告"  → 设置变量 current_channel = "A"
选项 2: "B. 先了解流程"     → 设置变量 current_channel = "B"
```

- [ ] **Step 3: 测试 S0 开场白**

在 Coze 预览窗口输入 "你好"，验证：
- 输出符合模板格式
- 显示 A/B 两个快捷回复按钮
- 重复发送 "你好" 时不再重复开场白

---

### Task 3: S0 路由节点（If-Else Node）

**操作路径:** Coze 控制台 → Workflow → 添加条件判断节点

- [ ] **Step 1: 创建路由节点**

在 Workflow 中添加 If-Else Node，命名为 `S0_路由`。

**判断条件:**

```
条件 1: {{current_channel}} == "A"  → 跳转 S1A_引导模板
条件 2: {{current_channel}} == "B"  → 跳转 S1B_自由对话
默认（变量为空）                    → 回到 S0_开场白（用户还没选）
```

- [ ] **Step 2: 测试路由**

在预览窗口分别点击 A 和 B，验证后续流程正确跳转。

---

### Task 4: 通道 A 引导模板节点（LLM Node）

- [ ] **Step 1: 创建 S1A_引导模板节点**

新建 LLM Node，命名为 `S1A_引导模板`。

**System Prompt:**

```
用户选择了快速报价通道。输出以下引导模板（严格按格式，不可省略字段）：

---
好的，请提供以下信息。您可以直接粘贴成分表，我来提取：

▸ 产品名称：
▸ 剂型（液体 / 片剂 / 粉剂 / 凝胶 / 喷雾 / 湿巾 / 其他）：
▸ 核心成分（INCI 名，多个用逗号分隔）：
▸ 宣称功效（消毒 / 抗菌 / 抑菌 / 清洁 / 其他）：
▸ 国产还是进口：
▸ 您的角色（品牌方 / 代工厂 / 中介 / 其他）：

[暂时无需报价，先跳过]
---

底部"[暂时无需报价，先跳过]"是一个快捷回复按钮。
```

- [ ] **Step 2: 配置快捷回复**

添加快捷回复按钮：

```
按钮文字: "暂时无需报价，先跳过"
触发动作: 设置 current_channel = "B"，跳转 S1B_自由对话
```

- [ ] **Step 3: 测试引导模板**

在预览窗口选择 A，验证：
- 输出与模板格式一致
- 剂型枚举包含全部 7 项（液体/片剂/粉剂/凝胶/喷雾/湿巾/其他）
- 底部显示"暂时无需报价，先跳过"按钮
- 点击跳过按钮后正确切换到通道 B

---

### Task 5: NLU 实体抽取节点（LLM Node）

- [ ] **Step 1: 创建 NLU 抽取节点**

新建 LLM Node，模型选择 GLM-4-flash（降低 Token 成本），命名为 `NLU_抽取`。

**System Prompt:**

```
从用户输入中提取消字号产品信息字段。只输出 JSON，不要任何解释。

字段定义：
- product_name: 产品名称
- dosage_form: 剂型，必须是以下之一：液体、片剂、粉剂、凝胶、喷雾、湿巾、其他。禁止输出"栓剂""皂剂"
- main_ingredients: 核心成分列表（INCI 名或 CAS 号），多个用逗号分隔
- target_claims: 宣称功效，必须是以下之一：消毒、抗菌、抑菌、清洁、其他
- domestic_or_imported: 国产 或 进口
- customer_type: 品牌方 或 代工厂 或 中介 或 其他
- usage_scenarios: 使用场景（选填）
- existing_reports: 是否已有检测报告（选填）
- historical_rejection: 是否有退单历史（选填）
- urgency_level: 紧急程度（选填）

规则：
1. 只提取用户明确提到的字段，未提及的输出 ""
2. dosage_form 如果用户说了不在枚举中的值，仍提取原文（Gate 会校验拦截）
3. main_ingredients 中如出现"三氯生""苯扎氯铵""次氯酸"等化学名，原样保留
4. target_claims 如果用户说"杀菌"，输出"消毒"；说"灭菌"，输出"消毒"
5. domestic_or_imported 如果用户说"国外的""进口的""韩国的"等，输出"进口"

输出 JSON 格式：
{
  "product_name": "...",
  "dosage_form": "...",
  "main_ingredients": "...",
  "target_claims": "...",
  "domestic_or_imported": "...",
  "customer_type": "...",
  "usage_scenarios": "...",
  "existing_reports": "...",
  "historical_rejection": "...",
  "urgency_level": "..."
}

用户输入：{{user_input}}
```

- [ ] **Step 2: 编写 NLU 结果写入变量的 Code Node**

新建 Code Node（JavaScript），命名为 `NLU_写入变量`。

```javascript
function main({ nlu_output }) {
  const data = JSON.parse(nlu_output);
  const updates = {};
  const changedFields = [];

  for (const [key, value] of Object.entries(data)) {
    if (value && value !== "" && value !== bot_vars[key]) {
      if (bot_vars[key] && bot_vars[key] !== "") {
        // 字段有旧值且与新值不同 → 记录冲突
        changedFields.push(key);
      }
      updates[key] = value;
    }
  }

  return {
    updated_vars: updates,
    has_conflict: changedFields.length > 0,
    conflict_fields: changedFields,
    extracted_any: Object.keys(updates).length > 0
  };
}
```

- [ ] **Step 3: 测试 NLU 抽取**

测试用例：

| 输入 | 期望抽取 |
|------|---------|
| "洗手液，液体的，成分是苯扎氯铵，想做抑菌" | dosage_form=液体, main_ingredients=苯扎氯铵, target_claims=抑菌 |
| "进口的消毒喷雾，成分三氯生 0.3%" | domestic_or_imported=进口, dosage_form=喷雾, main_ingredients=三氯生, target_claims=消毒 |
| "湿巾，主要就是清洁用的" | dosage_form=湿巾, target_claims=清洁 |
| "我是代工厂，客户让我来问问" | customer_type=代工厂 |
| "你好，请问备案要多久" | 全部字段为 "" |

---

### Task 6: Gate 校验节点（Code Node）

- [ ] **Step 1: 创建 Gate 校验节点**

新建 Code Node（JavaScript），命名为 `Gate_校验`。

```javascript
function main({ bot_vars }) {
  // 6 个必采字段
  const required = [
    { key: 'main_ingredients', priority: 0, label: '核心成分', hint: '请提供产品的主要成分（INCI名）' },
    { key: 'dosage_form', priority: 1, label: '剂型', hint: '液体/片剂/粉剂/凝胶/喷雾/湿巾/其他' },
    { key: 'domestic_or_imported', priority: 2, label: '国产/进口', hint: '您的产品是国产还是进口？' },
    { key: 'target_claims', priority: 3, label: '宣称功效', hint: '产品宣称什么功效？（消毒/抗菌/抑菌/清洁/其他）' },
    { key: 'product_name', priority: 4, label: '产品名称', hint: '请问产品名称是什么？' },
    { key: 'customer_type', priority: 5, label: '您的角色', hint: '您是品牌方、代工厂还是中介？' }
  ];

  const missing = [];
  const illegal = [];

  // 检查非法剂型
  if (bot_vars.dosage_form && ['栓剂', '皂剂'].includes(bot_vars.dosage_form)) {
    illegal.push({
      field: 'dosage_form',
      value: bot_vars.dosage_form,
      message: '栓剂和皂剂不在消字号备案范围内，请确认剂型'
    });
  }

  // 检查必采字段
  for (const field of required) {
    if (!bot_vars[field.key] || bot_vars[field.key] === '') {
      missing.push(field);
    }
  }

  // P0-P2 为硬阻断字段
  const hardGate = ['main_ingredients', 'dosage_form', 'domestic_or_imported'];
  const missingHardGate = missing.filter(f => hardGate.includes(f.key));

  // 追问轮数检查
  const roundCount = bot_vars.round_count || 0;

  return {
    all_complete: missing.length === 0 && illegal.length === 0,
    hard_gate_pass: missingHardGate.length === 0 && illegal.length === 0,
    missing_fields: missing,
    missing_hard_gate: missingHardGate,
    illegal_fields: illegal,
    next_question: missing.length > 0 ? missing[0] : null,
    round_count: roundCount,
    exceeded_max_rounds: roundCount >= 3,
    partial_info: missing.length > 0 && roundCount >= 3
  };
}
```

- [ ] **Step 2: 校验逻辑验证**

测试 Gate 校验结果：

| 场景 | 期望 gate_result |
|------|-----------------|
| 6 字段全有值 | all_complete=true, hard_gate_pass=true |
| 缺 product_name 但 P0-P2 全有 | hard_gate_pass=true, missing.length=1 |
| 缺 main_ingredients | hard_gate_pass=false, missing_hard_gate 含 main_ingredients |
| dosage_form=栓剂 | illegal 含一条，hard_gate_pass=false |
| round_count=3, 仍有缺 | exceeded_max_rounds=true, partial_info=true |

---

### Task 7: Gate 追问节点（LLM Node）

- [ ] **Step 1: 创建追问节点**

新建 LLM Node，命名为 `Gate_追问`，接收 Gate_校验 的输出。

**System Prompt:**

```
你是消字号合规预审助手。用户提交的信息缺少以下关键字段。

{{gate_result}}

当前已提供的信息：
- 产品名称：{{product_name}}
- 剂型：{{dosage_form}}
- 核心成分：{{main_ingredients}}
- 宣称功效：{{target_claims}}
- 国产/进口：{{domestic_or_imported}}
- 角色：{{customer_type}}

追问规则：
1. 每次只追问一个字段，从最高优先级开始
2. 追问话术模板："好的，您提到了 XXX。还缺一个关键信息：**[字段说明]**（[选项]）"
3. 如果超过 3 轮仍有缺（{{exceeded_max_rounds}}为 true），输出：
   "好的，我先基于已提供的信息进行分析。请注意：以下分析基于部分信息，完整预审需要补充 [缺失字段列表]。"
   然后标记 partial_info = true，继续推进到 S2。
4. 如果有非法值（{{illegal_fields}}），先纠正非法值再追问其他缺失字段
5. 如果用户本轮修改了之前已填的字段（{{has_conflict}}为 true），确认："您将 [旧值] 修改为 [新值]，这会影响之前的分析结果，确认修改吗？"
```

- [ ] **Step 2: 更新追问计数器**

在追问节点后添加 Code Node，`round_count += 1`。

```javascript
function main({ bot_vars }) {
  return { round_count: (bot_vars.round_count || 0) + 1 };
}
```

- [ ] **Step 3: 测试追问流程**

| 输入 | 期望追问 |
|------|---------|
| 只给了产品名和剂型（通道A提交后） | 追问 main_ingredients（P0 最高优先级） |
| 只缺 customer_type，第 3 轮 | 追问一轮后若仍缺，标记 partial_info=true |
| 用户说"我的剂型是栓剂" | 先纠正非法值，再追问其他 |

---

### Task 8: 通道 B 自由对话 + 静默抽取

- [ ] **Step 1: 创建通道 B 对话节点**

新建 LLM Node，命名为 `S1B_自由对话`。

**System Prompt:**

```
你是消字号合规预审顾问。用户当前处于咨询模式（通道 B），想先了解流程和法规。

回复规则：
1. 正常回答用户的合规、检测、备案问题，基于知识库检索
2. 不要催促用户提供产品信息，不要主动推进到报价阶段
3. 语气专业友好，像真人销售顾问
4. 如果不知道，坦诚说明而不是编造
5. 每次回复末尾给出一个自然的下一步建议（如了解其他法规、询问产品类型）

用户输入：{{user_input}}
知识库检索：{{kb_result}}
```

- [ ] **Step 2: 通道 B 后台 NLU 抽取**

在 `S1B_自由对话` 之后串联 `NLU_抽取` 节点（复用 Task 5 的节点），但抽取结果**不展示给用户**，仅静默写入 Bot 变量。

关键区别：通道 B 的 NLU 抽取后**不经过 Gate 追问**，直接结束本轮。

- [ ] **Step 3: 字段集齐提醒逻辑**

在 NLU_写入变量 之后添加判断——新建 If-Else Node，命名为 `B_集齐判断`：

```
条件：Gate_校验.all_complete == true  → 追加提示语
条件：Gate_校验.all_complete == false → 无操作，继续通道B
```

追加提示语（追加到本轮回复末尾）：

```
"对了，这段时间您提供了不少产品信息，我现在可以帮您出一份完整的预审报告和报价区间，需要吗？"
```

同时配置快捷回复按钮 "好的，出报告吧" → 设置 current_channel = "A"，跳转 Gate_校验。

- [ ] **Step 4: 测试通道 B**

| 输入 | 期望行为 |
|------|---------|
| "消字号备案一般要多久？" | 正常回答周期问题，不追问字段 |
| "我的洗手液成分是苯扎氯铵" | 静默抽取 dosage_form范围相关+ main_ingredients=苯扎氯铵 |
| 连续 5 轮闲聊，无意中填满 6 字段 | 第 5 轮末尾出现"需要我出报告吗？" |
| 用户点"好的，出报告吧" | 切换到 Gate_校验，复述已集齐字段请确认 |

---

### Task 9: 通道 A 完整提交 → Gate 校验 → S2 衔接

- [ ] **Step 1: 通道 A 提交流程串接**

通道 A 用户提交信息后的完整链路：

```
S1A_引导模板
  → 用户输入
  → NLU_抽取
  → NLU_写入变量
  → Gate_校验
  → all_complete == true  → 跳转 S2（下一个模块，暂用占位）
  → all_complete == false → Gate_追问 → 用户回复 → NLU_抽取（循环，最多3轮）
  → partial_info == true  → 跳转 S2（带 partial_info 标记）
```

- [ ] **Step 2: S2 占位节点**

新建 LLM Node，命名为 `S2_品类判定_占位`（本次不实现，留接口）：

```markdown
【S2 品类判定 - 待实现】
当前已采集字段：
- 产品名称：{{product_name}}
- 剂型：{{dosage_form}}
- 核心成分：{{main_ingredients}}
- 宣称功效：{{target_claims}}
- 国产/进口：{{domestic_or_imported}}
- 角色：{{customer_type}}
- 部分信息标记：{{partial_info}}

信息采集完成，品类判定模块待接入。
```

- [ ] **Step 3: 端到端测试（通道 A 完整流程）**

```markdown
测试用例 1: 用户一次性提供全部信息
输入: "我是品牌方，产品是抑菌洗手液，液体的，成分苯扎氯铵 0.1%，国产的"
期望: Gate 校验通过，进入 S2_占位

测试用例 2: 用户分两轮提供信息
第1轮: "洗手液，抑菌的，国产"
第2轮: "液体，成分苯扎氯铵，我们自己是品牌方"
期望: 第1轮追问缺的成分和剂型，第2轮补齐后进入 S2

测试用例 3: 用户提供不全，三轮后标记 partial_info
第1轮: "洗手液"
第2轮: "液体的"
第3轮: "国产"
期望: 第3轮追问后 main_ingredients 仍缺 → partial_info=true → 进入 S2_占位

测试用例 4: 剂型为非法值
输入: "栓剂，成分三氯生，消毒用"
期望: Gate 纠错 → 追问剂型 → 用户纠正后继续
```

---

### Task 10: 通道切换与状态保持

- [ ] **Step 1: 中途切换逻辑**

用户在通道 A 中途点击"先跳过" → current_channel = "B"，保留已采集字段值。
用户在通道 B 说"给我报价吧" → 意图识别到"报价"，current_channel = "A"，Gate_校验 当前已集齐字段。

在 Bot 级别 System Prompt 中加入：

```
当用户表达以下意图时，切换通道：
- "给我报价""帮我出报告""直接出结果" → 切换到通道 A
- "先跳过""先了解""先不问报价" → 切换到通道 B
切换通道时保留已采集的全部字段。
```

- [ ] **Step 2: 用户要求清空重来**

当用户说"重新开始""清空""换一个产品"时：
- 重置所有 10 个字段变量为 ""
- 重置 round_count = 0
- 重置 partial_info = false
- 回到 S0_开场白

在 Bot System Prompt 中添加意图识别规则。

- [ ] **Step 3: 测试通道切换**

| 场景 | 期望 |
|------|------|
| A 填了 3 个字段 → 点跳过 → B 聊天 → 说"给我报价" | 回到 A，Gate 校验已有的 3 个字段，追问剩余的 |
| B 静默集齐 5 个字段 → 用户拒绝报价 → 继续聊第 6 个 | 第 6 个集齐后再次提示 |
| 用户说"换一个产品" | 全部重置，回到 S0 |

---

## 部署检查清单

- [ ] Bot 变量面板：10 个字段变量 + 3 个状态变量已创建
- [ ] S0 开场白正确输出模板 + A/B 快捷回复
- [ ] 通道 A 引导模板格式完整，剂型枚举含 7 项
- [ ] NLU 抽取 10 项测试全部通过
- [ ] Gate 校验：完整/缺字段/非法值/三轮上限 均正确
- [ ] 通道 B 静默抽取不打断对话
- [ ] 字段集齐提醒正确触发
- [ ] 通道切换保留字段值
- [ ] 端到端 4 条测试用例全部通过
- [ ] Workflow 截图保存至 `coze_workflow/screenshots/`
