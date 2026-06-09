#!/usr/bin/env python3
"""
DeepSeek v4 语义分析 —— 分批处理 + 汇总合成
步骤：
  1. 将所有对话分 3 批，每批提取客户疑问 & 销售阶段
  2. 汇总 3 批结果，合成 Top 10 FAQ + 销售路径
"""

import os
import json
import sys
import time
from pathlib import Path
from openai import OpenAI

# ═══════════════════════════════════════
# 配置
# ═══════════════════════════════════════
CLEANED_DIR = Path(__file__).parent / "cleaned_data"
OUTPUT_FILE = Path(__file__).parent / "analysis_result.json"
BATCH_SIZE = 12

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com"
)
MODEL = "deepseek-chat"

SYSTEM = "你是资深销售分析师。只输出JSON，不加任何解释或markdown。"

# ═══════════════════════════════════════
# 第一步：分批提取
# ═══════════════════════════════════════

EXTRACT_PROMPT = """分析以下 {count} 通售前电话对话（销售: / 客户: 格式），提取两个维度的信息：

【对话数据】
{texts}

【提取要求】

维度一 —— 客户问题提取：
逐条列出客户在对话中提出的所有问题/关切/疑虑。每条包含：
  - question: 客户问的具体内容（概括，20字内）
  - context: 客户为什么问这个（10字内）
  - verbatim: 客户原话片段（<50字）
  - stage: 出现在哪个阶段（开场/需求挖掘/方案讨论/报价/收尾）

维度二 —— 销售阶段识别：
标注每通对话中销售经历了哪些阶段（选择：开场寒暄/自报家门/挖掘需求/技术方案/报价/异议处理/逼单/加微结束），按顺序列出。

输出JSON：
{{
  "questions": [{{"question": "...", "context": "...", "verbatim": "...", "stage": "..."}}],
  "sales_stages_per_call": [
    {{"call": "文件名", "stages": ["阶段1", "阶段2", ...], "notes": "对话走向简述（30字）"}}
  ]
}}"""


def extract_batch(batch: list[dict], batch_id: int) -> dict:
    """处理一批对话，提取原始问题和阶段"""
    texts = "\n\n---\n\n".join(
        f"【文件{c['name']}】\n{c['text']}" for c in batch
    )
    count = len(batch)

    print(f"  Batch {batch_id}: 发送 {count} 个文件... ", end="", flush=True)

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": EXTRACT_PROMPT.format(count=count, texts=texts)}
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    raw = resp.choices[0].message.content.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    print(f"✓ ({len(result.get('questions', []))} 个问题)")
    return result


# ═══════════════════════════════════════
# 第二步：汇总合成
# ═══════════════════════════════════════

SYNTHESIS_PROMPT = """汇总以下 3 批分析结果（共 {total_conv} 通销售对话），做两件事：

【批次分析结果】
{batches_json}

【任务1：Top 10 FAQ】
整合所有批次中提取的客户问题，去重归类，提炼出客户最常关心的 Top 10 核心问题。
要求：
  - 同类问题合并（例如"多少钱""什么价格""费用多少"都归为价格类）
  - 每个FAQ的 frequency 是它出现的对话数/总对话数{total_conv}
  - 按频次从高到低排列

【任务2：销售路径/转化套路】
综合所有批次的 sales_stages_per_call，识别共性销售路径。
  - 定义标准的销售阶段（5-8个阶段），每个阶段包含：名称、目的、销售典型话术、客户典型反应、流失风险
  - 标注哪些话术最有效（客户给出积极回应）
  - 标注客户最容易流失/拒绝的环节

输出JSON：
{{
  "faq_top10": [
    {{
      "rank": 1,
      "question": "问题概述（15字内）",
      "frequency": 数字,
      "typical_ask": ["客户问法1", "客户问法2"],
      "stage": "此问题通常出现在哪个销售阶段"
    }}
  ],
  "sales_path": {{
    "stages": [
      {{
        "stage": "阶段名称",
        "order": 数字,
        "purpose": "阶段目的",
        "typical_scripts": ["销售典型话术"],
        "customer_signals": ["客户反应"],
        "drop_off_risk": "低/中/高",
        "effectiveness": "该阶段的转化效率评估"
      }}
    ],
    "overall_pattern": "总结性描述（50字内）",
    "key_insights": ["核心发现1（15字内）", "核心发现2", "核心发现3", "核心发现4", "核心发现5"]
  }}
}}"""


def main():
    txt_files = sorted(CLEANED_DIR.glob("*.txt"))
    if not txt_files:
        print("❌ cleaned_data/ 中没有文件")
        sys.exit(1)

    conversations = []
    total_chars = 0
    for fp in txt_files:
        text = fp.read_text(encoding="utf-8").strip()
        if text:
            conversations.append({"name": fp.stem, "text": text})
            total_chars += len(text)

    total = len(conversations)
    print(f"\n{'='*60}")
    print(f"📂 读取 {total} 个对话文件，总字符 {total_chars:,}")
    print(f"📦 分 { (total + BATCH_SIZE - 1) // BATCH_SIZE } 批处理")
    print(f"{'='*60}\n")

    # ── 分批提取 ──
    all_questions = []
    all_stages = []

    for batch_id, start in enumerate(range(0, total, BATCH_SIZE), 1):
        batch = conversations[start:start + BATCH_SIZE]
        result = extract_batch(batch, batch_id)
        all_questions.extend(result.get("questions", []))
        all_stages.extend(result.get("sales_stages_per_call", []))
        if batch_id < (total + BATCH_SIZE - 1) // BATCH_SIZE:
            time.sleep(0.5)

    print(f"\n  中间结果: {len(all_questions)} 个客户问题, {len(all_stages)} 个阶段记录\n")

    # ── 汇总合成 ──
    print("🔄 汇总合成 Top 10 FAQ + 销售路径... ", end="", flush=True)

    batches_json = json.dumps({
        "questions": all_questions,
        "sales_stages_per_call": all_stages
    }, ensure_ascii=False, indent=2)

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": SYNTHESIS_PROMPT.format(
                total_conv=total,
                batches_json=batches_json
            )}
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    raw = resp.choices[0].message.content.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    print("✓")

    # ── 保存 ──
    OUTPUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 打印 ──
    print(f"\n{'='*60}")
    print(f"🏆 Top 10 客户最常关心的问题（FAQ）\n")
    for item in result.get("faq_top10", []):
        freq_pct = item.get("frequency", 0) / total * 100
        print(f"  {item['rank']:2d}. {item['question']}")
        print(f"      频次: {item.get('frequency', '?')}/{total} ({freq_pct:.0f}%) | 阶段: {item.get('stage', '?')}")
        for ask in item.get("typical_ask", [])[:2]:
            print(f"      → \"{ask}\"")
        print()

    print(f"{'='*60}")
    print(f"🗺️  销售转化路径\n")
    sp = result.get("sales_path", {})
    print(f"  整体模式: {sp.get('overall_pattern', '')}\n")
    for stage in sp.get("stages", []):
        emoji = {"低": "🟢", "中": "🟡", "高": "🔴"}.get(stage.get("drop_off_risk", ""), "⚪")
        eff = stage.get("effectiveness", "")
        print(f"  Step {stage.get('order', '?')}: {stage.get('stage', '')}")
        print(f"    {emoji} 流失风险:{stage.get('drop_off_risk', '?')} | 转化效率: {eff}")
        print(f"    目的: {stage.get('purpose', '')}")
        for s in stage.get("typical_scripts", [])[:2]:
            print(f"    ✏️ 话术: \"{s}\"")
        for s in stage.get("customer_signals", [])[:2]:
            print(f"    👤 客户: \"{s}\"")
        print()

    print("=" * 60)
    print("💡 核心发现")
    for ins in sp.get("key_insights", []):
        print(f"  → {ins}")

    print(f"\n✅ 完整结果: {OUTPUT_FILE}\n")


if __name__ == "__main__":
    main()
