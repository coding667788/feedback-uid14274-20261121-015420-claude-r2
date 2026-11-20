"""规范化后的输入模型（校验通过后构建，求解器只依赖本模块的数据类）。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Record:
    id: str
    department: str
    risk: str                 # 风险层级标签
    priority: int             # 正整数
    incidents: tuple          # 关联事故 ID（可多个，去重保序）


@dataclass(frozen=True)
class Reviewer:
    id: str
    department: str
    qualifications: frozenset  # 可审的风险层级标签
    weekly_capacity: int       # 单周容量（正整数）


@dataclass(frozen=True)
class Quota:
    """单维度单标签的入选计数上下界。"""
    dimension: str            # "department" | "risk"
    label: str
    lower: int
    upper: int

    @property
    def cid(self) -> str:
        return f"quota:{self.dimension}:{self.label}"


@dataclass(frozen=True)
class MutexGroup:
    id: str
    records: tuple            # 组内记录 ID（至少两条）


@dataclass(frozen=True)
class IncidentRequirement:
    """同一事故至少由两条分属不同部门的入选记录支撑。"""
    incident: str
    min_records: int          # 固定为 2
    distinct_departments: int  # 固定为 2

    @property
    def cid(self) -> str:
        return f"incident:{self.incident}"


@dataclass
class Case:
    departments: list
    risk_levels: list
    records: list             # list[Record]，按 id 排序
    reviewers: list           # list[Reviewer]，按 id 排序
    quotas: list              # list[Quota]
    mutex_groups: list        # list[MutexGroup]
    incidents: list           # list[IncidentRequirement]，按事故 id 排序
    raw: dict = field(repr=False, default_factory=dict)

    # ---- 便捷索引 ----
    def record_index(self) -> dict:
        return {r.id: i for i, r in enumerate(self.records)}

    def reviewer_index(self) -> dict:
        return {v.id: i for i, v in enumerate(self.reviewers)}

    def quotas_by_cid(self) -> dict:
        return {q.cid: q for q in self.quotas}

    def incidents_by_cid(self) -> dict:
        return {i.cid: i for i in self.incidents}

    def all_diagnosable_cids(self) -> list:
        """全部可诊断约束 ID，按字典序排序（诊断枚举与决胜顺序）。"""
        cids = [q.cid for q in self.quotas] + [i.cid for i in self.incidents]
        return sorted(cids)


def cid_sort_key(cid: str):
    """约束 ID 决胜键：先按前缀（incident < quota），再按标签。

    直接用字符串字典序即可保证完全确定的全序；单独封装以便文档引用。
    """
    return cid
