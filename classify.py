"""
售前对话分类脚本 —— 专为语音转文字(ASR)的噪声文本设计
依赖：pip install openai pandas
用法：python classify.py
"""

import os
import json
import time
import pandas as pd
from pathlib import Path
from openai import OpenAI

# ══════════════════════════════════════════════
# ① 配置（只需改这里）
# ══════════════════════════════════════════════

CONV_FOLDER   = "convs"          # 你的 txt 文件夹路径
OUTPUT_FILE   = "result.csv"     # 输出文件名
YOUR_PRODUCT  = "清洗剂/日化产品"  # 填你自己的产品类别，让模型理解背景
DELAY_SECONDS = 0.8              # 每次请求间隔（避免限速）

# DeepSeek API 配置（兼容 OpenAI SDK）
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY", "在这里直接填你的key也行"),
    base_url="https://api.deepseek.com"
)
MODEL = "deepseek-chat"   # DeepSeek V3；如用 R1 推理版改为 "deepseek-reasoner"


# ══════════════════════════════════════════════
# ② Prompt（针对 ASR 噪声文本优化）
# ══════════════════════════════════════════════

SYSTEM = f"""你是资深销售分析师，专门分析{YOUR_PRODUCT}行业的售前对话。
输入文本是语音识别(ASR)转录的，存在口语噪声、识别错误、断句不准。
你需要理解语义再分类，不要被错别字或断句干扰。
只输出JSON，不加任何解释或markdown。"""

def make_prompt(text: str) -> str:
    return f"""分析以下售前对话（ASR转录文本），输出JSON：

【对话内容】
{text}

【输出格式】（所有字段必填，严格按此结构）
{{
  "cleaned_summary": "用2-3句话总结对话核心内容（忽略ASR噪声，提取真实意图）",
  "main_intent": "从以下选一个 → 询价报价|功能咨询|资质政策|竞品对比|采购合作|售后服务|建厂生产|品牌代工|闲聊无意向|其他",
  "sub_intent": "10字以内的具体子意图",
  "customer_type": "从以下选一个 → 品牌商|经销商|工厂|个人创业者|不明确",
  "customer_stage": "认知期|考虑期|决策期",
  "sentiment": "积极|中性|消极|混合",
  "key_concerns": ["最多3个核心关切，每个不超过10字"],
  "asr_quality": "ASR质量评估：清晰|一般|噪声严重",
  "needs_human": true或false,
  "human_reason": "需要人工的原因，不需要填null",
  "golden_sample": true或false（是否适合作为Agent训练示例）,
  "golden_reason": "是优质样本的原因，不是则填null",
  "tags": ["最多4个标签，如：价格敏感、建厂咨询、资质询问、大客户等"]
}}"""


# ══════════════════════════════════════════════
# ③ 核心分类函数
# ══════════════════════════════════════════════

def classify(text: str, filename: str, idx: int) -> dict:
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user",   "content": make_prompt(text)}
            ],
            temperature=0.1,   # 低温度，保证分类稳定性
            max_tokens=800,
        )
        raw = resp.choices[0].message.content.strip()

        # 容错：去掉可能的 ```json ``` 包裹
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw.strip())
        result.update({"_id": idx, "_file": filename, "_status": "✓"})

        # 打印进度
        print(f"[{idx:02d}] ✓ {filename:<25} 意图:{result.get('main_intent'):<10} 情绪:{result.get('sentiment')}")
        return result

    except json.JSONDecodeError:
        print(f"[{idx:02d}] ✗ {filename} → JSON解析失败，原始输出已记录")
        return {"_id": idx, "_file": filename, "_status": "JSON错误", "_raw": raw}
    except Exception as e:
        print(f"[{idx:02d}] ✗ {filename} → 错误: {e}")
        return {"_id": idx, "_file": filename, "_status": f"错误:{e}"}


# ══════════════════════════════════════════════
# ④ 主程序
# ══════════════════════════════════════════════

def main():
    folder = Path(CONV_FOLDER)
    if not folder.exists():
        print(f"❌ 找不到文件夹：{CONV_FOLDER}")
        print(f"   请先创建文件夹并放入 txt 文件：mkdir {CONV_FOLDER}")
        return

    txt_files = sorted(folder.glob("*.txt"))
    if not txt_files:
        print(f"❌ {CONV_FOLDER}/ 里没有 .txt 文件")
        return

    print(f"\n📂 找到 {len(txt_files)} 个对话文件，开始分析...\n")
    print("-" * 65)

    results = []
    for i, fp in enumerate(txt_files, 1):
        # 自动检测编码（支持 UTF-8 和 GBK）
        for enc in ["utf-8", "gbk", "utf-8-sig"]:
            try:
                text = fp.read_text(encoding=enc).strip()
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"[{i:02d}] ✗ {fp.name} → 编码识别失败，跳过")
            continue

        if not text:
            print(f"[{i:02d}] - {fp.name} → 空文件，跳过")
            continue

        result = classify(text, fp.name, i)
        results.append(result)
        time.sleep(DELAY_SECONDS)

    print("-" * 65)

    # 保存结果
    df = pd.DataFrame(results)

    # 把列表字段展开成字符串（方便Excel查看）
    for col in ["key_concerns", "tags"]:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: " | ".join(x) if isinstance(x, list) else str(x)
            )

    # utf-8-sig 编码：Windows Excel 打开不乱码
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    # ── 打印摘要 ──
    ok = df[df["_status"] == "✓"]
    print(f"\n📊 完成 {len(ok)}/{len(df)} 条\n")

    if len(ok):
        print("🎯 意图分布：")
        for intent, n in ok["main_intent"].value_counts().items():
            print(f"   {'█' * n}  {intent}（{n}条）")

        print("\n⭐ 黄金训练样本：")
        golden = ok[ok["golden_sample"] == True]
        if len(golden):
            for _, r in golden.iterrows():
                print(f"   → {r['_file']}：{r.get('golden_reason','')}")
        else:
            print("   暂无（可降低筛选标准）")

        print("\n🚨 建议人工介入的场景：")
        human = ok[ok["needs_human"] == True]
        if len(human):
            for _, r in human.iterrows():
                print(f"   → {r['_file']}：{r.get('human_reason','')}")
        else:
            print("   暂无")

    print(f"\n✅ 结果已保存：{OUTPUT_FILE}（可用 Excel 直接打开）\n")


if __name__ == "__main__":
    main()
