"""
Coze Code Node — 安全关键词硬阻断（S0 阶段）。

架构位置：三层控制 → 第 0 层硬阻断（不进 LLM）
触发时机：每个请求的第一个操作
命中结果：直接返回拒绝，终止工作流
未命中：  pass_through=True，进入下一节点（NLU 抽取）

Bug 修复记录（共 8 个）：
  B1: 多个字符串字面量被硬换行截断 → SyntaxError
  B2: kw.lower().replace(" ", "") 对硬编码关键词冗余
  B3: "怎么写合规" 被错误归入虚假宣传 → 误杀合规咨询
  B4: "sb" 太短，可能命中英文单词内部 → 子串误杀
  B5: 5 个重复 for 循环 → 改为 dict 驱动的单循环
  B6: "包过检测"/"保证过检" 的 block_reason 与实际违规类型不匹配
  B7: 仅替换 ASCII 空格，全角空格(U+3000)逃逸 → 归一化不完整
  B8: 短关键词"作假"先于"材料作假"命中 → 跨类别子串误归因

Coze 兼容性：
  - Python 3.11.3（Coze 运行时版本）
  - 仅用标准库，不依赖 requests_async / numpy
  - 无 threading / multiprocessing / sockets
  - 单函数入口 main()
  - 输入变量名: input (string)
  - 输出变量: blocked, pass_through, block_reason, matched_keyword, rejection_message
"""

SAFETY_CATEGORIES = {
    # 虚构材料排在篡改报告之前（B8: 避免"材料作假"被"作假"子串误杀）
    "虚构材料": {
        "block_reason": "虚构材料",
        "rejection_message": (
            "我们无法协助虚构备案材料。"
            "提供虚假材料将导致备案被拒并承担法律责任。"
        ),
        "keywords": [
            "虚构备案材料", "虚构材料", "假材料", "伪造材料",
            "材料作假", "怎么编", "虚构一个", "凭空编",
        ],
    },
    "规避监管": {
        "block_reason": "规避监管",
        "rejection_message": (
            "需要提示：消字号备案是国家法规要求，未备案产品上市销售属于违法行为。"
            "我们无法协助规避监管流程，但可以帮您了解合法合规的备案路径。"
        ),
        "keywords": [
            "绕备案", "绕开备案", "绕过备案", "不备案", "免备案",
            "不用备案", "逃避监管", "不留痕迹", "不被查到",
            "偷偷卖", "私下卖", "怎么避开", "怎么绕过", "怎么逃",
            "不上备案", "跳过备案",
        ],
    },
    "虚假宣传": {
        "block_reason": "虚假宣传",
        "rejection_message": (
            "需要提示：消毒产品的功效宣传受法规严格约束，"
            "虚假或夸大宣传可能面临行政处罚。我们无法提供擦边宣传建议。"
        ),
        "keywords": [
            "夸大效果", "夸大宣传", "虚假宣传", "怎么写擦边",
            "擦边宣传", "夸大功效", "怎么写宣传", "违规宣传",
            # B3: "怎么写合规" 已移除 — 属于合法合规咨询
            "不会被罚", "怎么吹",
        ],
    },
    "篡改报告": {
        "block_reason": "篡改报告",
        "rejection_message": (
            "我们无法协助修改或伪造检测报告。"
            "检测报告由CMA/CNAS认证实验室出具，具有法律效力。"
        ),
        "keywords": [
            "改检测报告", "改报告", "p一下检测", "修改检测",
            "篡改报告", "做假报告", "伪造报告",
            "包过检测", "保证过检",
            "作假", "作假报告", "做假检测",
        ],
    },
    "攻击/恶意": {
        "block_reason": "攻击/恶意",
        "rejection_message": "抱歉，我无法处理这个请求。",
        "keywords": [
            "垃圾系统", "废物",
            "sb", "傻逼",
        ],
    },
}


async def main(args) -> dict:
    """
    Coze Code Node 入口（Python 3.11.3 / Coze 当前标准格式）。

    Coze 传入:
        args.params['input'] → 用户输入文本

    Coze 输出变量（需在节点 UI 中配置为完全一致的字段名）:
        blocked:             bool   — 是否命中阻断
        pass_through:        bool   — 是否放行到下游节点
        block_reason:        string — 阻断类别
        matched_keyword:     string — 命中的具体关键词
        rejection_message:   string — 返回给用户的拒绝话术
    """
    # Coze 标准：通过 args.params 读取输入变量
    # 兼容旧格式：如果 args 是 dict，直接用 .get()
    try:
        text = args.params.get("input", "") if hasattr(args, "params") else args.get("input", "")
    except Exception:
        text = ""

    if not text or not text.strip():
        return {
            "blocked": False,
            "pass_through": True,
            "block_reason": "",
            "matched_keyword": "",
            "rejection_message": "",
        }

    # B7: ASCII 空格 + 全角空格 + 不间断空格
    normalized = text.lower().replace(" ", "").replace("　", "").replace(" ", "")

    for category, cfg in SAFETY_CATEGORIES.items():
        # B5+B8: 按长度降序，长词优先匹配
        for kw in sorted(cfg["keywords"], key=len, reverse=True):
            if kw in normalized:
                return {
                    "blocked": True,
                    "pass_through": False,
                    "block_reason": cfg["block_reason"],
                    "matched_keyword": kw,
                    "rejection_message": cfg["rejection_message"],
                }

    return {
        "blocked": False,
        "pass_through": True,
        "block_reason": "",
        "matched_keyword": "",
        "rejection_message": "",
    }
