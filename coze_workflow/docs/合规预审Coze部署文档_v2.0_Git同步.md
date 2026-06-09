# 消字号合规预审引擎 — GitHub 同步 & Coze 部署指南 v2.0

本指南把项目从本地电脑同步到 GitHub，再通过 Coze 的 Git 服务部署到扣子编程平台。面向非技术用户，每一步都配有说明。

---

## 目录

1. [准备工作：清理项目，保护敏感信息](#1-准备工作清理项目保护敏感信息)
2. [本地电脑 → GitHub：首次上传](#2-本地电脑--github首次上传)
3. [Coze 绑定 GitHub 仓库](#3-coze-绑定-github-仓库)
4. [日常使用：Push / Pull / 冲突处理](#4-日常使用push--pull--冲突处理)
5. [Code Node 部署对照表](#5-code-node-部署对照表)
6. [部署后验证](#6-部署后验证)
7. [常见问题](#7-常见问题)

---

## 1. 准备工作：清理项目，保护敏感信息

### 1.1 已经做好的保护

项目根目录的 `.gitignore` 文件已经配置好，以下内容**不会被上传**到 GitHub：

| 被排除的内容 | 原因 |
|-------------|------|
| `__pycache__/` 和 `*.pyc` | Python 自动生成的缓存文件，不需要备份 |
| `.DS_Store` | Mac 系统文件 |
| `.env` | **含 API 密钥**（DeepSeek Key），绝对不能公开 |
| `node_modules/` | 第三方依赖包，体积大，可通过 `package.json` 重新安装 |
| `cleaned_data/` 和 `转录文本/` | 通话记录含电话号码等隐私数据 |
| `*.xlsx`、`*.numbers`、`*.xmind` | 大型数据文件和脑图 |
| `ocr_output/`、`analysis_result.json` | 临时分析数据 |

### 1.2 你需要检查的

打开终端（Terminal），进入项目目录，运行：

```bash
cd ~/Desktop/ai_sale_agent001
git status
```

如果看到任何你觉得不该上传的文件出现在列表里，告诉我，我帮你加到 `.gitignore`。

---

## 2. 本地电脑 → GitHub：首次上传

### 2.1 在 GitHub 创建新仓库

1. 打开 [github.com](https://github.com)，登录你的账号
2. 点击右上角头像旁边的 **+** → **New repository**
3. 填写仓库信息：

| 字段 | 填写内容 |
|------|---------|
| Repository name | `disinfectant-compliance-engine`（或你喜欢的名字） |
| Description | 消字号合规预审引擎 — AI 驱动的第三方检测机构售前预审系统 |
| Public / Private | 建议选 **Private**（私有仓库，只有你能看到代码） |
| Initialize this repository | **不要勾选任何选项**（README / .gitignore / License 都不选） |

4. 点击 **Create repository**

> **为什么选空仓库？** 如果 GitHub 帮你生成了 README 等文件，会和本地代码冲突。空仓库最干净。

5. 创建后你会看到一个页面，标题是 "…or push an existing repository from the command line"。**保留这个页面**，下一步要用到上面的命令。

### 2.2 在本地初始化 Git 并上传

打开终端，逐条执行以下命令（复制粘贴，按回车）：

```bash
# 1. 进入项目目录
cd ~/Desktop/ai_sale_agent001

# 2. 初始化 Git 仓库
git init

# 3. 将所有代码加入暂存区
git add .

# 4. 创建第一次提交
git commit -m "首次提交：消字号合规预审引擎 v1.0 — S0-S7 全链路"

# 5. 关联 GitHub 远程仓库（把下面这行里的 YOUR_USERNAME 换成你的 GitHub 用户名）
git remote add origin https://github.com/YOUR_USERNAME/disinfectant-compliance-engine.git

# 6. 推送到 GitHub
git push -u origin main
```

> 如果第 5 步的 URL 不知道是什么，回到 GitHub 刚才那个页面，复制它显示的 `git remote add origin ...` 那行即可。

推送成功后，刷新 GitHub 页面，你应该看到所有代码文件出现在仓库里。

---

## 3. Coze 绑定 GitHub 仓库

### 3.1 给 Coze 授权 GitHub

这是在 Coze 工作空间级别做一次就行，所有项目都能共用这个授权。

1. 登录 [扣子编程](https://www.coze.cn)
2. 左下角确认你在正确的工作空间（免费版只有一个默认个人空间）
3. 左侧导航栏 → **集成管理**
4. 找到 **Git 服务** 标签页 → GitHub → 点击 **配置**
5. 按页面提示登录 GitHub 并授权

授权成功后，GitHub 一栏显示 **"已配置"**。

### 3.2 在 AI 编程项目中绑定仓库

1. 左侧导航栏 → **项目管理** → 打开你的 AI 编程项目
2. 右侧新建标签页，选择 **版本控制**
3. 点击 **绑定仓库**

   ![绑定仓库按钮](https://p9-aiop-sign.byteimg.com/tos-cn-i-ho4ivd66cl/4e78a3a5c4c84c6e9d1c3a5f7b2d8e1a~tplv-ho4ivd66cl-image.png)

4. 选择 **已有仓库**，搜索你刚才创建的 `disinfectant-compliance-engine`
5. 确认绑定

### 3.3 首次 Push（从 Coze 到 GitHub）

绑定成功后，页面会提示 **"有未推送的更改"**。

1. 点击 **Push** 按钮
2. 确认要同步的 Commit 列表
3. 点击 **Push** 执行

完成后页面显示 **"已同步"**，版本列表会出现一条记录，标记为来自扣子编程。

---

## 4. 日常使用：Push / Pull / 冲突处理

### 4.1 什么时候用 Push？

当你或 AI 编程在 Coze 上修改了代码，想把改动同步到 GitHub：

1. 打开项目 → **版本控制** 标签
2. 如果有提示 **"有未推送的更改"**，点 **Push**
3. 确认后完成同步

### 4.2 什么时候用 Pull？

当 GitHub 仓库有新的提交（比如你和同事合修改了代码，他们的改动先推到了 GitHub），想把改动拉到 Coze：

1. 打开项目 → **版本控制** 标签
2. 如果有提示 **"远程有更新"**，点 **Pull**
3. 确认后完成同步

### 4.3 Push 或 Pull 时冲突了怎么办？

不同来源的代码改了同一个地方会导致冲突。Coze 会提示你选择：

| 选项 | 含义 | 什么时候选 |
|------|------|-----------|
| **全部保留我的版本** | 放弃远程的修改，只用 Coze 上的代码 | 你确定 Coze 上的代码是最新的，远程的那些改动不要了 |
| **全部使用远程版本** | 用 GitHub 上的代码覆盖 Coze 的 | GitHub 上的代码更新、更正确，你想用那个版本 |

> **建议**：不确定时告诉我，我帮你判断。

### 4.4 日常使用流程图

```
你在本地/Coze 改代码 → Push → GitHub
同事在 GitHub 改代码 → Pull → Coze
你本地改了，GitHub 也改了 → Push 或 Pull 时冲突 → 选择保留谁的版本
```

---

## 5. Code Node 部署对照表

以下 7 个文件需要部署到 Coze Code Node。**文件名就是节点标识。**

### 5.1 节点速查表

| 节点 | 文件名 | 作用 | 关键输入 | 关键输出 |
|------|--------|------|---------|---------|
| S0 | `safety_block.py` | 安全扫描 | `input`（用户文本） | `is_safe`, `block_reason` |
| S1 | `entry_merge.py` | 入口解析 | `structured_text` | `product_name`, `dosage_form`, `main_ingredients` 等 10 字段 |
| S2 | `classification_decision.py` | 分类判定 | `product_name`, `target_claims`, `dosage_form` | `product_category`, `sub_type`, `is_classified` |
| S3 | `ingredient_compliance.py` | 成分合规 | `main_ingredients`, `product_category`, `sub_type` | `results_json`, `overall_status` |
| S4 | `risk_engine.py` | 风险分级 | `results_json`, `target_claims`, `domestic_or_imported` + 布尔标志 | `risk_level` (R1/R2/R3), `can_quote` |
| S5 | `test_plan_generator.py` | 检测方案 | `product_category`, `sub_type`, `dosage_form`, `target_claims`, `risk_level` | `test_items_json`, `test_total_count` |
| S6 | `s6_pricing.py` | 报价预估 | `test_items_json`, `risk_level`, `customer_type`, `urgency_level` | `pricing_table`, `total`, `cycle` |
| S7 | `summary_generator.py` | 预审摘要 | 18 个字段（全链路汇总） | `markdown_report`, `summary_json` |

### 5.2 数据流总览

```
S1 (entry_merge)
  ├── product_name, target_claims, dosage_form → S2 (classification_decision)
  ├── main_ingredients → S3 (ingredient_compliance)
  ├── domestic_or_imported, target_claims → S4 (risk_engine)
  ├── dosage_form, target_claims → S5 (test_plan_generator)
  └── customer_type, urgency_level → S6 (s6_pricing)

S2 ── product_category, sub_type → S3, S5
S3 ── results_json → S4
S4 ── risk_level → S5, S6
S5 ── test_items_json, test_total_count → S6
S6 ── total, cycle, notes → S7

S7 收集 S1-S6 全部输出 → Markdown 报告 + 结构化 JSON
```

### 5.3 关键约定（避免字段名对不上）

| 约定 | 说明 |
|------|------|
| `product_category` | S2 输出的品类字段名，**不是** `category` |
| `test_total_count` | S5 输出的检测项数字段名，**不是** `total_count` |
| `test_summary` | S5 输出的摘要字段名，**不是** `summary` |
| JSON 字段 | S3 `results_json`、S5 `test_items_json`、S6 `unknown_items_json` 都是 **JSON 字符串**，不是对象 |
| 布尔值 | S4 的 `medical_keyword_hit`、`historical_rejection` 等支持 `true`/`false` 字符串或布尔值 |
| R3 三层防御 | S4 判定 R3 → S5 内部阻断方案生成 → S6 内部阻断报价，三重保险 |

### 5.4 Coze Code Node 配置模板

每个节点在 Coze 中创建时，按以下步骤操作：

1. **添加代码节点** → 命名（如 `S1-入口解析`）
2. **代码语言** → Python 3
3. **粘贴代码** → 打开对应 `.py` 文件，全选复制粘贴
4. **输入变量** → 按上述表格添加（变量名必须和代码中 `args.params['xxx']` 完全一致）
5. **输出变量** → 按返回字典的 key 名称添加

---

## 6. 部署后验证

### 6.1 单元测试（每个节点单独验证）

在 Coze 工作流中逐个运行每个节点，用测试数据验证输入/输出。

### 6.2 集成测试（全链路串联验证）

如果你在本地有 Python 环境：

```bash
cd ~/Desktop/ai_sale_agent001/coze_workflow/code_nodes
python3 test_integration_pipeline.py
```

应该看到：**64 PASS / 0 FAIL**。

### 6.3 Coze 工作流端到端测试

用以下测试数据在工作流中跑一遍：

```
产品名称：维达免洗洗手液
剂型：凝胶
核心成分：酒精（75%）、甘油、卡波姆
宣称功效：消毒、抑菌
产地：国产
您的角色：品牌方
紧急程度：普通
```

预期结果链：
- S1: `ready=True`
- S2: `product_category="第二类"`, `is_classified=True`
- S3: 3 个成分均识别
- S4: `risk_level` 为 R1 或 R2
- S5: 15 项检测方案，`safety_blocked=False`
- S6: 品牌方 85 折，含税总价约 ¥35,000
- S7: 完整 Markdown 报告含「费用预估」章节

---

## 7. 常见问题

### Q1: 只支持 main 分支，我想用其他分支怎么办？

Coze Git 服务目前只支持 **main** 分支。所有代码都推到 main 即可，这对小团队足够了。

### Q2: 可以把项目绑定到已有代码的旧仓库吗？

**不推荐**。旧仓库的代码和 Coze 上的代码会产生冲突，给管理带来麻烦。建议绑定一个**全新的空仓库**。

### Q3: 如何更换绑定的 GitHub 仓库？

在版本控制页面，点击解绑图标 → **解绑仓库** → 重新绑一个新仓库。

### Q4: 如何更换授权的 GitHub 账号？

1. 集成管理 → Git 服务 → **取消配置**
2. 登录另一个 GitHub 账号
3. 集成管理 → Git 服务 → **配置**，用新账号授权

注意：取消授权后，所有已绑定的仓库会自动解绑，需要重新绑定。

### Q5: 我的 API Key 会不会被上传到 GitHub？

**不会**。`.env` 文件已在 `.gitignore` 中排除，GitHub 不会看到它。如果你在 Coze 的 Code Node 中硬编码了 Key（不推荐），那也不会进入仓库。

### Q6: Coze 上改了代码，本地没更新怎么办？

Coze Push 到 GitHub 后，在本地终端执行：

```bash
cd ~/Desktop/ai_sale_agent001
git pull origin main
```

### Q7: 本地改了代码，Coze 没更新怎么办？

本地 Push 到 GitHub 后，在 Coze 版本控制页面点击 **Pull**。

---

## 附录：当前测试状态（2026-05-30）

| 模块 | 文件 | 测试数 | 状态 |
|------|------|--------|------|
| S1 入口解析 | `entry_merge.py` | 65/65 | ✅ |
| S2 分类判定 | `classification_decision.py` | 58/58 | ✅ |
| S3 成分合规 | `ingredient_compliance.py` | 42/42 | ✅ |
| S4 风险分级 | `risk_engine.py` | 91/91 | ✅ |
| S5 检测方案 | `test_plan_generator.py` | 64/64 | ✅ |
| S6 报价预估 | `s6_pricing.py` | 56/56 | ✅ |
| S7 预审摘要 | `summary_generator.py` | 109/109 | ✅ |
| **全链路集成** | `test_integration_pipeline.py` | **64/64** | ✅ |

**独立测试总计: 485 PASS** | **集成测试: 64 PASS**

---

> 文档版本: v2.0 | 更新日期: 2026-05-30 | 维护者: @ml
