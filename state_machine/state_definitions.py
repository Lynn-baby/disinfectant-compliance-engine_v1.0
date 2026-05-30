"""
F6 状态机 — 状态定义与迁移规则。

8 状态线性流转 + 回退机制。
每个状态定义了：前置条件、可迁移至、禁止行为、输出要求。
"""

from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    S0 = "S0"  # 初始接待
    S1 = "S1"  # 信息采集
    S2 = "S2"  # 品类判定
    S3 = "S3"  # 成分合规
    S4 = "S4"  # 风险分级
    S5 = "S5"  # 检测方案
    S6 = "S6"  # 报价预估
    S7 = "S7"  # 预审摘要


# ── 状态迁移表 ──
# 对应 PRD 4.2

@dataclass
class StateSpec:
    state: State
    label: str                      # 中文名
    description: str                # 状态描述
    forward: list[State]            # 可迁移至（正向）
    backward: list[State]           # 可回退至
    preconditions: list[str]        # 前置条件（进入此状态前必须满足）
    forbidden: list[str]            # 禁止行为
    required_outputs: list[str]     # 此状态必须产出的内容


STATE_TABLE: dict[State, StateSpec] = {
    State.S0: StateSpec(
        state=State.S0,
        label="初始接待",
        description="用户首次进入，问候并引导至 S1",
        forward=[State.S1],
        backward=[],
        preconditions=[],
        forbidden=["禁止直接回答合规问题", "禁止跳过信息采集"],
        required_outputs=["问候语", "引导进入S1"],
    ),
    State.S1: StateSpec(
        state=State.S1,
        label="信息采集",
        description="采集 6 必采字段，每轮最多追问 2 个",
        forward=[State.S2],
        backward=[State.S0],
        preconditions=[],
        forbidden=[
            "禁止在 6 必采字段未完整时进入 S3 及以后",
            "禁止一次性追问超过 2 个字段",
            "禁止接受模糊成分描述而不追问",
        ],
        required_outputs=["已确认信息摘要", "缺失字段追问"],
    ),
    State.S2: StateSpec(
        state=State.S2,
        label="品类判定",
        description="判定产品品类和适用法规路径",
        forward=[State.S3],
        backward=[State.S1],
        preconditions=[
            "product_name 已采集",
            "dosage_form 已采集",
        ],
        forbidden=[
            "禁止在品类不确定时猜测",
            "禁止混淆消毒产品与非消毒产品的备案路径",
        ],
        required_outputs=["品类标签", "适用法规路径", "判定依据"],
    ),
    State.S3: StateSpec(
        state=State.S3,
        label="成分合规",
        description="逐项核查成分在法规目录中的状态",
        forward=[State.S4],
        backward=[State.S1],
        preconditions=[
            "品类判定完成",
            "main_ingredients 已采集",
        ],
        forbidden=[
            "禁止在知识库无命中时推断成分合规状态",
            "禁止将 unknown 描述为'应该没问题'",
        ],
        required_outputs=["成分合规逐项列表", "法规引用"],
    ),
    State.S4: StateSpec(
        state=State.S4,
        label="风险分级",
        description="综合多维度判定 R1/R2/R3",
        forward=[State.S5, State.S7],  # R3 时可跳至 S7 输出摘要后转人工
        backward=[],
        preconditions=[
            "成分合规检查完成",
        ],
        forbidden=[
            "禁止对 R3 产品给出可备案暗示",
            "禁止在 R3 时进入 S6 报价",
        ],
        required_outputs=["风险等级", "触发条件列表", "引擎行为说明"],
    ),
    State.S5: StateSpec(
        state=State.S5,
        label="检测方案",
        description="生成检测项目清单",
        forward=[State.S6],
        backward=[],
        preconditions=[
            "风险等级为 R1 或 R2",
            "品类已判定",
        ],
        forbidden=[
            "禁止无 KB 依据时新增检测项目",
            "禁止对禁用宣称生成检测方案",
        ],
        required_outputs=["检测项目表格", "参考标准", "样品数量"],
    ),
    State.S6: StateSpec(
        state=State.S6,
        label="报价预估",
        description="计算检测费用和参考周期",
        forward=[State.S7],
        backward=[],
        preconditions=[
            "检测方案已生成",
            "风险等级为 R1 或 R2",
        ],
        forbidden=[
            "禁止对定价表外项目给价格",
            "禁止对 R3 产品进行报价",
        ],
        required_outputs=["费用明细表格", "折后总计含税", "参考周期"],
    ),
    State.S7: StateSpec(
        state=State.S7,
        label="预审摘要",
        description="生成全链路预审摘要报告",
        forward=[],
        backward=[],
        preconditions=["前面各阶段已完成"],
        forbidden=["禁止超出预审范围给出承诺"],
        required_outputs=["预审摘要报告", "声明", "下一步建议"],
    ),
}


# ── 状态→字段依赖映射（用于回退时的级联 stale）──
# 对应 PRD 4.2.1 B 节

FIELD_STATE_DEPENDENCY: dict[str, list[State]] = {
    "product_name":          [],                          # 仅元数据，不触发回退
    "dosage_form":           [State.S2, State.S5, State.S6],
    "main_ingredients":      [State.S3, State.S4, State.S5, State.S6],
    "target_claims":         [State.S4, State.S5, State.S6],
    "domestic_or_imported":  [State.S2, State.S3, State.S4, State.S5, State.S6],
    "customer_type":         [State.S6],
    "urgency_level":         [State.S6],
    "historical_rejection":  [State.S4, State.S5, State.S6],
}


def get_rollback_target(changed_fields: list[str]) -> State:
    """
    根据变更字段计算回退目标状态。
    取所有字段依赖链上的最上游状态。

    例：改 main_ingredients → S3；改 main_ingredients + dosage_form → S2
    """
    all_states: set[State] = set()
    for field in changed_fields:
        deps = FIELD_STATE_DEPENDENCY.get(field, [])
        all_states.update(deps)

    if not all_states:
        return State.S1  # 无依赖的字段变更 → 回退到 S1

    # 找 S 编号最小的（最上游）
    ordered = sorted(all_states, key=lambda s: int(s.value[1]))
    return ordered[0]


def get_stale_states(changed_fields: list[str]) -> set[State]:
    """获取变更字段关联的所有下游状态（需标记 stale）"""
    stale: set[State] = set()
    for field in changed_fields:
        deps = FIELD_STATE_DEPENDENCY.get(field, [])
        stale.update(deps)
    return stale
