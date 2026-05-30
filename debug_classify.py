#!/usr/bin/env python3
"""Debug: 展示 classfy.py 的分类推理过程"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from clean_transcript import (
    split_segments, group_segments, label_groups,
    is_sales_anchor, is_customer_anchor, should_split,
    clean_text, desensitize,
)

def debug_file(filepath, max_groups=30):
    print(f"\n{'='*70}")
    print(f"📄 {filepath.name}")
    print(f"{'='*70}")

    raw = filepath.read_text(encoding="utf-8")
    segments = split_segments(raw)
    segments = [s for s in segments if s.strip()]
    print(f"原始 segments 数: {len(segments)}")

    groups = group_segments(segments)

    # 详细展示分组过程
    print(f"\n--- 分组过程（前 {max_groups} 组）---\n")
    current_group = [segments[0]]
    group_idx = 0

    for i in range(1, len(segments)):
        prev_text = "".join(current_group)
        curr = segments[i]
        split_flag = should_split(prev_text, curr, len(prev_text))

        if split_flag or i == len(segments) - 1:
            if not split_flag:
                current_group.append(curr)

            group_idx += 1
            if group_idx <= max_groups:
                combined = "".join(current_group)
                # 找出触发切分的原因
                reasons = []
                if is_sales_anchor(curr if split_flag else ""):
                    reasons.append("🎯 销售锚点(微谱)")
                if is_customer_anchor(curr if split_flag else ""):
                    reasons.append("🎯 客户锚点(请问哪位/哪家公司)")
                if split_flag and prev_text.rstrip().endswith(("?", "？","吗","呢","吧")):
                    reasons.append("📝 前段以问句结尾")
                if split_flag and len(prev_text) > 40 and len(curr) <= 6:
                    reasons.append("📏 极长→极短回应")
                if split_flag and curr.startswith(("你","您")) and len(curr) < 30:
                    if any(k in curr for k in ["多少","怎么","什么","哪","吗","呢"]):
                        reasons.append("❓ 客户口吻提问")

                reason_str = f"  ← {', '.join(reasons)}" if reasons else "  ← (默认：内容连贯/弱信号合并)"
                print(f"[组{group_idx:02d}] {combined[:100]}...{reason_str}")

            current_group = [curr] if split_flag else []
        else:
            current_group.append(curr)

    # 最终标注
    labels = label_groups(groups)
    print(f"\n--- 最终标注（前 {max_groups} 组）---\n")
    for i, (grp, lbl) in enumerate(zip(groups[:max_groups], labels[:max_groups])):
        combined = "".join(grp)
        cleaned = clean_text(combined) if len(combined) < 30 else clean_text(combined[:30]) + "..."
        # 显示分组原因
        anchor_info = ""
        for seg in grp:
            if is_sales_anchor(seg):
                anchor_info = f" ← 含销售锚点: \"{seg[:30]}\""
                break
            if is_customer_anchor(seg):
                anchor_info = f" ← 含客户锚点: \"{seg[:30]}\""
                break
        if not anchor_info:
            anchor_info = " ← (交替推断)"
        print(f"[{lbl}] {cleaned}{anchor_info}")

    print(f"\n总组数: {len(groups)}, 销售: {labels.count('销售')}, 客户: {labels.count('客户')}")


if __name__ == "__main__":
    base = Path(__file__).parent / "转录文本"
    # 3 个样本：短通话 / 中等 / 长通话
    samples = [
        "通话录音@18606222589(18606222589)_20220218133448.txt",  # 最短
        "134 1096 1780_20220425103455.txt",                       # 中等
        "138 2360 5460_20220421143025.txt",                       # 最长
    ]
    for s in samples:
        fp = base / s
        if fp.exists():
            debug_file(fp, max_groups=15)
