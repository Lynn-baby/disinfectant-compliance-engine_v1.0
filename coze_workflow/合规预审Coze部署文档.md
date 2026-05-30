# 消字号合规预审引擎 — Coze 部署文档

## 概述

将 S1-S3 三个 Code Node 部署到 Coze 工作流，实现从"产品信息输入"到"成分合规判定"的自动化链路。

- **S1 入口解析**：用户填写的模板文本 → 结构化字段（6 必采 + 剂型归一化）
- **S2 分类判定**：产品名 + 剂型 + 宣称 → 消字号品类（第一/二/三类）
- **S3 成分合规**：成分列表 + 品类 → 逐成分查表 + 合规结论

---

## 前置准备

- [ ] Coze 账号已登录
- [ ] 本地测试全部通过（165/165）：
  ```bash
  cd coze_workflow/code_nodes
  python3 test_entry_merge.py           # 65/65
  python3 test_classification_decision.py  # 58/58
  python3 test_ingredient_compliance.py    # 42/42
  ```

---

## 第一步：创建 Coze 工作流

1. Coze 控制台 → **工作流** → **新建工作流**
2. 命名：`消字号合规预审-S1S3`
3. 描述：`S1入口解析 → S2分类判定 → S3成分合规`
4. 添加**开始节点**（Start Node），这是工作流的入口，接收 Bot 传入的 `structured_text`

---

## 第二步：S1 入口解析

### 2.1 添加代码节点

| 配置项 | 值 |
|--------|-----|
| 节点名称 | `S1-入口解析` |
| 代码语言 | Python 3 |
| 代码内容 | 粘贴 `coze_workflow/code_nodes/entry_merge.py` 全部内容 |

### 2.2 输入变量

在节点 UI 中添加输入变量（**变量名必须和代码中 `args.params['xxx']` 完全一致**）：

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `structured_text` | String | `开始节点.structured_text` | 用户填写的模板文本 |

### 2.3 输出变量

在节点 UI 中声明以下输出变量（**变量名必须和代码 return dict 的 key 完全一致**）：

| 变量名 | 类型 |
|--------|------|
| `ready` | Boolean |
| `product_name` | String |
| `dosage_form` | String |
| `main_ingredients` | String |
| `target_claims` | String |
| `domestic_or_imported` | String |
| `customer_type` | String |
| `urgency_level` | String |
| `error_message` | String |

### 2.4 验证

保存后，用以下测试输入手动执行一次：

```
【产品信息采集结果】

产品名称：维达免洗洗手液
剂型：凝胶
核心成分：酒精（75%）、甘油、卡波姆、纯化水
宣称功效：消毒、抑菌
产地：国产
您的角色：品牌方
```

期望输出 `ready: true`，`product_name: 维达免洗洗手液`，`dosage_form: 凝胶`。

---

## 第三步：S2 分类判定

### 3.1 添加代码节点

| 配置项 | 值 |
|--------|-----|
| 节点名称 | `S2-分类判定` |
| 代码语言 | Python 3 |
| 代码内容 | 粘贴 `coze_workflow/code_nodes/classification_decision.py` 全部内容 |

### 3.2 输入变量

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `product_name` | String | `S1-入口解析.product_name` | 产品名称 |
| `dosage_form` | String | `S1-入口解析.dosage_form` | 剂型（已归一化） |
| `target_claims` | String | `S1-入口解析.target_claims` | 宣称功效 |

### 3.3 输出变量

| 变量名 | 类型 |
|--------|------|
| `category` | String |
| `sub_type` | String |
| `is_classified` | Boolean |
| `needs_review` | Boolean |
| `matched_keywords` | String |
| `classification_step` | String |
| `basis` | String |
| `error_message` | String |

### 3.4 验证

输入 `product_name: 维达免洗洗手液, dosage_form: 凝胶, target_claims: 消毒、抑菌`，期望输出 `is_classified: true, category: 第二类, sub_type: 抗抑菌制剂`。

---

## 第四步：S3 成分合规

### 4.1 添加代码节点

| 配置项 | 值 |
|--------|-----|
| 节点名称 | `S3-成分合规` |
| 代码语言 | Python 3 |
| 代码内容 | 粘贴 `coze_workflow/code_nodes/ingredient_compliance.py` 全部内容 |

### 4.2 输入变量

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `main_ingredients` | String | `S1-入口解析.main_ingredients` | "、"分隔的成分列表 |
| `product_category` | String | `S2-分类判定.category` | 产品类别（如"第二类"） |
| `sub_type` | String | `S2-分类判定.sub_type` | 子类型（可选） |

> 注意：S3 输入中的 `product_category` 来自 S2 的 `category` 输出，不是同名的另一个变量。Coze UI 连线时看清楚。

### 4.3 输出变量

| 变量名 | 类型 |
|--------|------|
| `overall_status` | String |
| `ingredient_count` | Integer |
| `summary` | String |
| `results_json` | String |
| `compliance_basis` | String |

### 4.4 验证

输入 `main_ingredients: 酒精（75%）、甘油、卡波姆、纯化水, product_category: 第二类`，期望输出 `overall_status: all_allowed`，`ingredient_count: 4`。

---

## 第五步：连线

```
开始节点 ──structured_text──▶ S1-入口解析
                                   │
          ┌────────────────────────┼────────────────────────┐
          │ product_name           │ dosage_form            │ target_claims
          ▼                        ▼                        ▼
     S2-分类判定 ◀───────────────────────────────────────────
          │
          ├── category ──────────▶ S3-成分合规 (product_category)
          ├── sub_type ──────────▶ S3-成分合规 (sub_type)
          │
          │   S1-入口解析.main_ingredients ──▶ S3-成分合规 (main_ingredients)
```

连线要点：
- S2 的 3 个输入全部来自 S1
- S3 的 `main_ingredients` 来自 S1，`product_category` 和 `sub_type` 来自 S2
- S3 的 `product_category` 连到 S2 的 `category`（不是同名变量）

---

## 第六步：端到端测试

### 测试用例 1：标准合规产品

输入（开始节点 `structured_text`）：

```
【产品信息采集结果】

产品名称：维达免洗洗手液
剂型：凝胶
核心成分：酒精（75%）、甘油、卡波姆、纯化水
宣称功效：消毒、抑菌
产地：国产
您的角色：品牌方
```

期望链路：
- S1 → `ready: true`, `product_name: 维达免洗洗手液`, `dosage_form: 凝胶`
- S2 → `is_classified: true`, `category: 第二类`, `sub_type: 抗抑菌制剂`
- S3 → `overall_status: all_allowed`, `ingredient_count: 4`

### 测试用例 2：含未知成分

`core_ingredients` 改为：`酒精（75%）、纳米银、植物提取物`

期望 S3 → `overall_status: has_unknown`

### 测试用例 3：缺必采字段

删除模板中的"产品名称"行。

期望 S1 → `ready: false`，`error_message` 提示缺失产品名称。

---

## 常见问题

### Q1: 节点报错 "变量未定义"

检查输入变量名拼写是否和代码中 `args.params['xxx']` 完全一致（区分大小写）。

### Q2: 输出变量取不到值

检查输出变量名拼写是否和代码 return dict 的 key 完全一致。**Coze 不会报类型错误，变量名不匹配时静默取到空值。**

### Q3: S3 拿不到 product_category

确认 S3 的 `product_category` 输入连到的是 S2 的 `category` 输出（不是连到 S1 的某个字段）。

### Q4: 代码太长粘贴后报错

Coze 对单个节点代码有长度限制。`ingredient_compliance.py` 约 800 行（含完整 GB 38850 成分字典），如果在 Coze 里报长度超限，检查是否超过了平台限制（通常 5000 行以内 OK）。

### Q5: 本地测试通过但 Coze 跑不动

Coze Code Node 运行时是 Python 3.11.3，仅支持标准库。检查代码是否用了标准库外的依赖（三个文件已确认仅用标准库）。

---

## 附录：本地测试命令

```bash
# 进入代码目录
cd /Users/ml/Desktop/ai_sale_agent001/coze_workflow/code_nodes

# 逐个跑
python3 test_entry_merge.py            # S1: 65/65
python3 test_classification_decision.py  # S2: 58/58
python3 test_ingredient_compliance.py    # S3: 42/42

# 一键全跑
python3 test_entry_merge.py && python3 test_classification_decision.py && python3 test_ingredient_compliance.py
```

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-05-29 | 初版，S1-S3 部署文档，165/165 测试通过 |
