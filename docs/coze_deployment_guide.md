# Coze Workflow 部署指南 — Phase 1

## 你需要在 Coze 上做什么

在 Coze 上建一个 Workflow，里面放 4 种节点，用线串起来：

```
用户输入
  │
  ▼
┌─────────────┐
│ 节点1: 代码  │  ← 安全扫描 + 拒答决策
│ (Code Node) │
└──────┬──────┘
       │ 通过
       ▼
┌─────────────┐
│ 节点2: 大模  │  ← NLU 实体抽取（小模型）
│ 型 (LLM)    │    把大白话转成结构化字段
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 节点3: 代码  │  ← Gate 检查 + 追问生成
│ (Code Node) │    字段不全就追问，全了就放行
└──────┬──────┘
       │ 字段齐全
       ▼
┌─────────────┐
│ 节点4: 大模  │  ← 合规判定 + 转述
│ 型 (LLM)    │    注入查表结果，LLM只负责说人话
└─────────────┘
       │
       ▼
    输出给用户
```

---

## 节点1：安全扫描（Code Node）

**文件来源**：`anti_hallucination/safety_keywords.py` + `refusal_strategy/refusal_engine.py`

在 Coze 新建一个 **Code Node**，语言选 Python，粘贴以下代码：

```python
# 安全关键词词库
BLOCK_KEYWORDS = {
    "规避监管": ["绕备案", "绕开备案", "不备案", "免备案", "逃避监管", "不留痕迹", "不被查到", "偷偷卖", "私下卖"],
    "虚假宣传": ["夸大效果", "夸大宣传", "虚假宣传", "擦边宣传", "夸大功效"],
    "篡改报告": ["改检测报告", "改报告", "做假报告", "伪造报告", "包过检测", "作假"],
    "虚构材料": ["虚构备案材料", "虚构材料", "假材料", "伪造材料"],
}

# 医疗暗示关键词（L1 = 中断, L2 = 警告）
MEDICAL_L1 = ["治疗湿疹", "抗病毒", "杀病毒", "抗新冠病毒", "杀灭新冠", "抑制幽门螺杆菌", "抗癌", "抗肿瘤"]
MEDICAL_L2 = ["消炎", "消肿", "止痛", "止痒", "促进愈合", "提高免疫力", "修复皮肤"]

def main(user_input: str) -> dict:
    text = user_input.lower().replace(" ", "")
    
    # 第1步：安全词扫描
    for category, keywords in BLOCK_KEYWORDS.items():
        for kw in keywords:
            if kw.lower().replace(" ", "") in text:
                return {"action": "block", "reason": category,
                        "reply": f"需要提示：涉及{category}的请求无法处理。请通过合法合规途径办理消字号备案。"}
    
    # 第2步：医疗L1检测
    for kw in MEDICAL_L1:
        if kw in text:
            return {"action": "interrupt", "reason": "medical_l1",
                    "reply": f"需要提示：消字号产品功效宣传不能涉及医疗用途（如「{kw}」）。请问您是否需要我基于消字号合规范围继续分析？"}
    
    # 第3步：医疗L2检测
    warnings = []
    for kw in MEDICAL_L2:
        if kw in text:
            warnings.append(kw)
    
    return {"action": "pass", "warnings": warnings}
```

**Coze 配置**：
- 输入变量：`user_input`（string，来自用户消息）
- 输出变量：`action`、`reason`、`reply`、`warnings`

**下游连线**：
- 如果 `action == "block"` 或 `action == "interrupt"` → 直接输出 `reply` 给用户，**不走后续节点**
- 如果 `action == "pass"` → 进入节点2

---

## 节点2：NLU 实体抽取（LLM Node）

**文件来源**：`anti_hallucination/nlu_prompt_template.py`

在 Coze 新建一个 **LLM Node**，模型选 **GLM-4-flash**（小模型就够），粘贴以下系统提示词：

```
你是一个信息提取助手。从用户输入中提取以下字段，输出 JSON。提取不到的字段填 null，不要编造。

字段说明：
- product_name: 产品名称
- dosage_form: 剂型，从以下选一个：液体、凝胶、喷雾、湿巾、片剂、粉剂、膏霜、气雾
- main_ingredients: 核心成分列表（数组）
- target_claims: 宣称功效列表（数组）
- domestic_or_imported: "国产" 或 "进口"
- customer_type: "品牌方" / "代工厂" / "中介" / "其他"

剂型识别：
- 液体/水剂 → "液体"   凝胶/啫喱 → "凝胶"   喷雾/喷剂 → "喷雾"
- 湿巾/湿纸巾 → "湿巾"   片剂/泡腾片 → "片剂"   气雾/压力罐 → "气雾"

输出格式（只输出 JSON，不要任何其他文字）：
{"product_name": "...", "dosage_form": "...", "main_ingredients": [...], "target_claims": [...], "domestic_or_imported": "...", "customer_type": "..."}

用户输入：
{{user_input}}
```

**Coze 配置**：
- 用户提示词：`{{user_input}}`
- 输出：解析后的 JSON → 存为变量 `nlu_result`

---

## 节点3：Gate 检查 + 追问（Code Node）

**文件来源**：`anti_hallucination/gate_check.py` + `info_collection/collection_engine.py`

新建 **Code Node**，粘贴：

```python
# 6 个必采字段
REQUIRED = ["product_name", "dosage_form", "main_ingredients", "target_claims", "domestic_or_imported", "customer_type"]

FIELD_LABELS = {
    "product_name": "产品名称", "dosage_form": "剂型",
    "main_ingredients": "核心成分", "target_claims": "宣称功效",
    "domestic_or_imported": "产地（国产/进口）", "customer_type": "您的角色",
}

# 当前已累积的字段（从会话变量中读）
def main(nlu_result: dict, session_filled: dict) -> dict:
    # 合并新提取的字段
    for field, value in nlu_result.items():
        if value and value != "null" and value != []:
            if isinstance(value, list):
                value = "、".join(value)
            if field not in session_filled or not session_filled.get(field):
                session_filled[field] = value
    
    # 检查缺什么
    missing = []
    for field in REQUIRED:
        val = session_filled.get(field)
        if not val or val == "" or val == []:
            missing.append(field)
    
    if not missing:
        return {"ready": True, "session_filled": session_filled,
                "reply": "信息已齐全，接下来为您进行合规预审分析。"}
    
    # 追问：最多问2个
    targets = missing[:2]
    labels = [FIELD_LABELS[f] for f in targets]
    ask_msg = "还需要确认：" + "、".join(labels) + "。"
    
    return {"ready": False, "session_filled": session_filled, "missing": missing, "reply": ask_msg}
```

**Coze 配置**：
- 输入变量：`nlu_result`（来自节点2）、`session_filled`（会话变量）
- 输出变量：`ready`、`session_filled`、`reply`

**下游连线**：
- 如果 `ready == False` → 输出 `reply` 给用户，等用户下一轮回复
- 如果 `ready == True` → 进入节点4

---

## 节点4：合规判定（LLM Node）

**文件来源**：`anti_hallucination/main_model_prompt_template.py`

新建 **LLM Node**，模型选 **GLM-4.7**（主模型，需要强推理能力），粘贴系统提示词：

```
你是消字号合规预审引擎的对外交互层。你的职责是将系统判定的结果用专业、不生硬的自然语言呈现给用户。

【角色边界——这是最重要的规则】
- 成分是否合规、风险等级——由系统查表判定，不由你判断
- 你收到的成分检查结果和风险等级是已经算好的事实，你的任务是转述
- 转述时必须引用法规编号

【永远禁止】
- 编造法规条文或标准号
- 用"应该可以""大概率能过"等模糊表述
- 给高风险产品"可以做"的暗示
- 成分状态未知时说"应该没问题"

【当前已采集信息】
产品名称：{{product_name}}
剂型：{{dosage_form}}
核心成分：{{main_ingredients}}
宣称功效：{{target_claims}}
产地：{{domestic_or_imported}}
客户类型：{{customer_type}}

【成分合规结果——由系统查表，你仅转述】
{{ingredient_results}}

【风险等级——由系统查表，你仅转述】
风险等级：{{risk_level}}
触发条件：{{risk_triggers}}

【输出模板】
【品类判定】
产品名称：...
剂型：...
判定结果：...
适用法规路径：...

【成分合规状态】
（逐项列出，每项标注 ✅允许 / ❌禁用 / ⚠️未收录 + 法规依据）

【风险评级】
风险等级：R? (?风险)
触发条件：...

【下一步】
（根据风险等级给出下一步建议）
```

**Coze 配置**：
- 用户提示词留空或放用户原始消息
- `{{变量}}` 填入前面 Code Node 算出的实际值

---

## 总结：你要做的事

| 步骤 | 做什么 | 时间估计 |
|------|--------|---------|
| 1 | 在 Coze 建 Workflow，新建上面 4 个节点 | 30 分钟 |
| 2 | 把代码粘贴进去，配置输入输出变量 | 20 分钟 |
| 3 | 用 5 条测试对话跑通 S0→S7 | 15 分钟 |
| 4 | 准备 50 条客户真实问法，测试 NLU 抽取准不准 | 10 分钟 + 逐条检查 |

**不需要做的事**：
- 不用改代码逻辑（312 条测试已验证）
- 不用自己写 Prompt（上面已经写好）
- 不用手动搭状态机（Coze 的会话变量天然就是状态机，只需存 `current_state` 和 `session_filled`）
