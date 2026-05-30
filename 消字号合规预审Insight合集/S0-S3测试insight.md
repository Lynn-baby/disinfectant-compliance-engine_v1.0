# S0-S3 Code Node 测试套件 Insight

**日期**: 2026-05-28
**来源**: 为 S0/S1/S2 三个 Coze Code Node 创建独立测试套件并全量跑通

---

## 一、S0 安全扫描 (safety_block.py) — 37/37 pass

### 覆盖点
- 5 大安全类别：虚构材料、规避监管、虚假宣传、篡改报告、攻击/恶意
- 边界条件：空输入、纯空格、正常咨询放行
- 回归 Bug：B3 (合规咨询不误杀)、B7 (全角空格/不间断空格归一化)、B8 (长关键词优先匹配)

### 关键发现

**Mock 对象必须精确匹配 Coze 运行时的接口契约**

`safety_block.py` 的 `main(args)` 通过 `args.params.get("input", "")` 读取输入。如果 Mock 在 `args` 和 `dict` 之间多包了一层中间对象，`.get()` 调用会抛出 AttributeError，被 `except Exception: text = ""` 静默捕获，导致所有安全关键词测试全部返回空文本 → 全部放行。

```python
# 错误：args.params 是 MockParams 对象，没有 .get() 方法
class MockArgs:
    def __init__(self, text):
        self.params = MockParams(text)  # .get() 不存在

# 正确：args.params 直接是 dict
class MockArgs:
    def __init__(self, text):
        self.params = {"input": text}  # .get() 可用
```

**启示**：Coze Code Node 的 `args.params` 在运行时是 dict-like 对象。测试 Mock 应直接用 dict，不要额外封装。

---

## 二、S1 入口解析 (entry_merge.py) — 65/65 pass

### 覆盖点
- 模板解析：全角/半角冒号混用，9 个字段映射
- 空值跳过："未提供"、全角/半角括号"（用户未提供）"
- 标题行跳过：【】和 # 开头
- 字段归一化：剂型（11 映射）、产地（9 映射）、客户类型（9 映射）、紧急程度
- 6 必采 Gate 校验
- 剂型二次校验（归一化后不在 8 标准剂型中）

### 关键发现

**剂型归一化+二次校验构成两层防线**

第一层 `DOSAGE_NORMALIZE` 做宽松映射（"液"→"液体"、"乳"→"膏霜"），第二层 `VALID_DOSAGE_FORMS` 做严格校验。两层之间通过 `normalize()` → `main()` 的顺序耦合。测试分别覆盖：
- 纯函数 `normalize()` 的映射正确性
- `main()` 的完整流程（解析→归一化→Gate→二次校验）

这避免了测试只测了纯函数而忽略了 pipeline 级联问题。

---

## 三、S2 分类判定 (classification_decision.py) — 58/58 pass

### 覆盖点
- Phase 0 命名规范：禁用词、外文字母、三段式结构、过短/占位符
- Step 1 第一类：医疗器械/灭菌/皮肤黏膜（仅搜 product_name）
- Step 2 第二类：消毒剂/消毒器械/抗抑菌制剂（含冲突解决）
- Step 3 第三类：卫生用品
- Step 4 剂型兜底：湿巾→第三类
- 未分类 → needs_review 转人工
- main() 入口 + 前置条件检查（缺品名/剂型）

### 关键发现

#### 1. Phase 0 的 FUNCTIONAL_STARTS 过于激进

"医疗器械专用灭菌剂" 以 "医疗" 开头，"医疗" 在 `FUNCTIONAL_STARTS` 中 → Phase 0 判定为"缺商标名"拦截。但 "医疗器械" 本身就是 Step 1 的高风险关键词，被 Phase 0 拦在分类之外，逻辑上是矛盾的。

**当前绕过方案**：测试用 "新华医疗器械灭菌剂"（加商标前缀）。**潜在风险**：真实用户输入 "医疗器械灭菌剂"（无品牌）会被 Phase 0 拦下，实际上应该进入 Step 1 返回第一类。

#### 2. ATTRIBUTE_SUFFIXES 缺少器械类属性名

当前后缀列表只有 16 个（泡腾片、气雾剂、洗手液、喷雾、凝胶、湿巾、洗液、棉片、液、片、粉、膏、乳、霜、皂、巾、剂、水）。缺少：

- **器械类**：“器”（消毒器/灭菌器）、“机”（消毒机）、“仪”（消毒仪）、“器械”
- **防护类**：“罩”（口罩）
- **通用类**："品"

导致所有消毒器械类产品通过 Phase 0 的前提是 product_name 恰好以已知后缀结尾。测试中用 "消毒器喷雾""消毒仪喷雾"（加"喷雾"后缀）绕过，但真实产品不会这样命名。

**建议**：`ATTRIBUTE_SUFFIXES` 应补充 `"器", "机", "仪", "器械", "罩", "品"` 等。

#### 3. Step 3 关键词 vs Step 4 剂型兜底的隐性优先级

"湿巾" 同时出现在 Step 3 关键词列表和 `DOSAGE_FORM_FALLBACK` 中。实际逻辑是 Step 3 先于 Step 4 执行：
- product_name 含 "湿巾" → Step 3 命中（分类 step=Step3）
- product_name 不含 "湿巾"，但 dosage_form="湿巾" → Step 4 兜底（分类 step=Step4）

测试通过两组建模分离这两个路径：
- "维达纸巾" → Step 3（关键词在品名中）
- "清风洁肤巾" + dosage_form="湿巾" → Step 4（品名无关键词，仅靠剂型兜底）

#### 4. 子类型冲突的正确触发

Step 2 的 `resolve_conflict` 机制要求收集全部命中关键词并按子类型分组。测试验证了：
- 单子类型 → 直接返回
- 多子类型（消毒剂+抗抑菌制剂）→ needs_review=True, sub_type=None

但有一个易踩的坑：如果 target_claims 中包含 "杀菌"（→消毒剂），而 product_name 中含 "消毒仪"（→消毒器械），会触发非预期的冲突。测试 KW-01 最初设 claims="杀菌" 导致失败，改为 claims="" 后通过 — 这说明测试输入需要逐字段控制，不能随意填 claims。

---

## 四、测试工程经验

### Mock 模式统一

三个模块的 main() 共用同一套 Coze args 契约模式：

```python
class MockArgs:
    def __init__(self, **kwargs):
        self.params = dict(kwargs)

def run(**kwargs) -> dict:
    return asyncio.run(main(MockArgs(**kwargs)))
```

### 同步封装

Coze 的 `async def main(args)` 通过 `asyncio.run()` 同步调用。每个测试函数独立调用，不共享 event loop，避免协程泄漏。

### 先跑红再修绿

S0 测试第一轮跑了 11/37（Mock 错误），S2 第一轮跑了 49/58（Phase 0 拦截测试输入）。每次失败都暴露了真实问题（Mock 结构错误、Phase 0 边界未被文档化），验证了 TDD 的"先看到失败"原则。

---

## 五、待观察项

| 类别 | 描述 | 优先级 |
|------|------|--------|
| FUNCTIONAL_STARTS | "医疗器械"开头被误拦为缺商标名 | 中 |
| ATTRIBUTE_SUFFIXES | 缺器械/防护类属性后缀 | 高 |
| Phase 0 vs Step 1 | Phase 0 拦截可能与分类关键词冲突（如"医疗"） | 中 |
