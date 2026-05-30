#!/usr/bin/env python3
"""
classfy.py —— ASR 转录文本清洗脚本
功能：
  1. 去除噪音（filler words、时间戳、无关标签）
  2. 标准化角色（统一标注为 销售: 和 客户:）
  3. 脱敏处理（手机号、姓名、地址 → 占位符）
  4. 内容合并（同一说话人的连续语句合并为一段）
输出：cleaned_data/ 文件夹，保持原文件名
"""

import re
import sys
from pathlib import Path

# ══════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════
INPUT_DIR = Path(__file__).parent / "转录文本"
OUTPUT_DIR = Path(__file__).parent / "cleaned_data"

# ---- Filler words ----
STANDALONE_FILLERS = {
    "就是说", "就是说呢", "那个", "然后呢", "这个这个",
    "嗯", "呃", "额", "啊", "哦", "噢", "嗯嗯",
    "对吧", "是吧", "对不对", "是不是", "哎", "欸",
    "嘛", "呀", "哇", "呢", "吧",
}

# ---- 强销售信号（微谱自报家门） ----
SALES_ANCHOR = [
    "微谱", "微不检测", "微弗检测", "微譜", "微普",
    "我这边是微", "我今天是微", "我们是微谱",
]

# ---- 强客户信号 ----
CUSTOMER_STRONG = [
    "请问哪位", "你是哪里", "你是哪家公司",
    "哪个公司", "你哪里", "哪家公司",
    "您是哪位", "你谁", "你是哪个",
]

# ---- 脱敏正则 ----
PHONE_RE = re.compile(r"1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}")
LANDLINE_RE = re.compile(r"0\d{2,3}[\s\-]?\d{7,8}")
NAME_RE = re.compile(
    r"(?:[A-Za-z]+[\u4e00-\u9fff]?|[\u4e00-\u9fff]{1,3})"
    r"(?:总|先生|女士|小姐|工|经理|老师|律师)"
    r"(?=\s|，|。|$|！|？|,|\.|\?|的|那|你|我|他|这|哈|是|不)"
)
WECHAT_RE = re.compile(r"(?:微信|微信号|v信|V信|wx|WX|vx|VX)[：:\s]*[a-zA-Z0-9_\-]{5,20}")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def split_segments(raw_text: str) -> list[str]:
    """拆分原始文本为语段"""
    lines = raw_text.strip().split("\n")
    segments = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        for p in line.split(" "):
            p = p.strip()
            if p:
                segments.append(p)
    return segments


def is_sales_anchor(seg: str) -> bool:
    """判断是否为销售自报家门的锚点"""
    return any(kw in seg for kw in SALES_ANCHOR)


def is_customer_anchor(seg: str) -> bool:
    """判断是否为客户的强信号"""
    return any(kw in seg for kw in CUSTOMER_STRONG)


def should_split(prev_combined: str, current: str, prev_len: int) -> bool:
    """判断是否应该在当前 segment 前切分（开始新的 speaker turn）。
    策略：仅在有可靠信号时切分，避免把同一人的连续说话切碎。"""
    # 规则1: 强销售锚点（微谱自报家门）→ 一定切分
    if is_sales_anchor(current):
        return True

    # 规则2: 强客户信号 → 切分
    if is_customer_anchor(current):
        return True

    # 规则3: 前一段以明确问句结尾 → 后面是新 turn
    if prev_combined.rstrip().endswith(("?", "？", "吗", "呢", "吧")):
        if len(current) > 3:  # 不是纯语气词
            return True

    # 规则4: 极长句后出现极短回应 → 大概率换人
    if prev_len > 40 and len(current) <= 6:
        stripped = current.strip().rstrip("，。?,!！？")
        if stripped in {
            "对", "是的", "可以", "好", "行", "对的", "对对对",
            "没错", "好的", "可以啊", "行啊", "好吧", "明白",
            "知道了", "了解", "不清楚", "不知道", "是",
        }:
            return True

    # 规则5: 明显以客户口吻提问
    if (current.startswith(("你", "您")) and len(current) < 30
            and any(kw in current for kw in ["多少", "怎么", "什么", "哪", "吗", "呢"])):
        return True

    return False


def group_segments(segments: list[str]) -> list[list[str]]:
    """
    将 segments 分组，每组是一个 speaker turn。
    策略：仅在强信号处切分，避免过度分割。后续 DeepSeek 可修正。
    """
    if not segments:
        return []

    groups = []
    current_group = [segments[0]]

    for i in range(1, len(segments)):
        prev_text = "".join(current_group)
        curr = segments[i]

        if should_split(prev_text, curr, len(prev_text)):
            groups.append(current_group)
            current_group = [curr]
        else:
            current_group.append(curr)

    groups.append(current_group)
    return groups


def label_groups(groups: list[list[str]]) -> list[str]:
    """
    标注每个组的说话人。
    策略：找到销售锚点 → 前后交替标注。
    """
    n = len(groups)
    labels = ["unknown"] * n

    # Step 1: 找销售锚点
    for i, grp in enumerate(groups):
        combined = "".join(grp)
        if is_sales_anchor(combined):
            labels[i] = "销售"
        elif is_customer_anchor(combined):
            labels[i] = "客户"

    # Step 2: 找第一个确定标签作为锚点
    anchor = None
    for i, lbl in enumerate(labels):
        if lbl != "unknown":
            anchor = i
            break

    if anchor is None:
        # 没有锚点：极短的片段，假设第一个是销售（主叫方）
        for i in range(n):
            labels[i] = "销售" if i % 2 == 0 else "客户"
        return labels

    # Step 3: 从锚点向前交替
    # 注意：锚点前通常是开场问候，大概率还是销售在说（主叫方先开口）
    for i in range(anchor - 1, -1, -1):
        if labels[i] != "unknown":
            continue
        # 如果锚点是销售，前面的组通常也是销售先打招呼
        if labels[i + 1] == "销售":
            # 看内容：短问候 → 销售；明确客户信号 → 客户
            combined = "".join(groups[i])
            if is_customer_anchor(combined):
                labels[i] = "客户"
            else:
                labels[i] = "销售"  # 主叫方在自报家门前先打招呼
        else:
            labels[i] = "客户" if labels[i + 1] == "销售" else "销售"

    # Step 4: 从锚点向后交替
    current = labels[anchor]
    for i in range(anchor + 1, n):
        if labels[i] != "unknown":
            current = labels[i]
            continue
        labels[i] = "客户" if current == "销售" else "销售"
        current = labels[i]

    # Step 5: 后处理 —— 合并相邻的同标签组
    i = 1
    while i < len(labels):
        if labels[i] == labels[i - 1] and labels[i] != "unknown":
            # 合并 groups[i] 到 groups[i-1]
            groups[i - 1].extend(groups[i])
            groups.pop(i)
            labels.pop(i)
        else:
            i += 1

    return labels


def clean_text(text: str) -> str:
    """清洗文本"""
    text = text.strip()
    if text in STANDALONE_FILLERS:
        return ""

    # 删除开头/结尾的语气词
    for f in sorted(STANDALONE_FILLERS, key=len, reverse=True):
        if text.startswith(f + " "):
            text = text[len(f) + 1:].strip()
        elif text == f:
            return ""
        if text.endswith(" " + f):
            text = text[:-(len(f) + 1)].strip()

    # 删除文中 filler
    for f in ["就是说", "就是说呢", "那个"]:
        text = re.sub(r"\s*" + re.escape(f) + r"\s*", "", text)

    # 清理多余空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


def desensitize(text: str) -> str:
    """脱敏处理"""
    text = PHONE_RE.sub("[联系方式]", text)
    text = LANDLINE_RE.sub("[座机号码]", text)
    text = NAME_RE.sub("[客户姓名]", text)
    text = WECHAT_RE.sub("[微信号]", text)
    text = EMAIL_RE.sub("[邮箱地址]", text)
    return text


def process_file(input_path: Path) -> str:
    """处理单个文件"""
    for enc in ["utf-8", "gbk", "utf-8-sig"]:
        try:
            raw_text = input_path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"无法识别编码: {input_path.name}")

    segments = split_segments(raw_text)
    segments = [s for s in segments if s.strip()]
    if not segments:
        return ""

    groups = group_segments(segments)
    labels = label_groups(groups)

    # 构建输出：每组清洗 + 脱敏
    output_lines = []
    for grp, lbl in zip(groups, labels):
        cleaned_parts = []
        for seg in grp:
            c = clean_text(seg)
            if c:
                cleaned_parts.append(c)
        if not cleaned_parts:
            continue
        combined = "，".join(cleaned_parts)
        combined = desensitize(combined)
        output_lines.append(f"{lbl}: {combined}")

    return "\n\n".join(output_lines)


def main():
    if not INPUT_DIR.exists():
        print(f"❌ 找不到输入目录：{INPUT_DIR}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)

    txt_files = sorted(INPUT_DIR.glob("*.txt"))
    if not txt_files:
        print(f"❌ {INPUT_DIR} 中没有 .txt 文件")
        sys.exit(1)

    print(f"\n📂 找到 {len(txt_files)} 个转录文件，开始清洗...\n")
    print("-" * 60)

    success = 0
    for i, fp in enumerate(txt_files, 1):
        try:
            cleaned = process_file(fp)
            out_path = OUTPUT_DIR / fp.name
            out_path.write_text(cleaned, encoding="utf-8")
            sales_count = cleaned.count("销售:")
            cust_count = cleaned.count("客户:")
            print(f"[{i:02d}] ✓ {fp.name:<40} 销售:{sales_count}轮  客户:{cust_count}轮")
            success += 1
        except Exception as e:
            print(f"[{i:02d}] ✗ {fp.name} → {e}")

    print("-" * 60)
    print(f"\n✅ 完成 {success}/{len(txt_files)} 个文件")
    print(f"📁 输出目录：{OUTPUT_DIR}\n")


if __name__ == "__main__":
    main()
