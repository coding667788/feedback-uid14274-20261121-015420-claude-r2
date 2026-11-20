"""输入结构与语义校验。

任何问题都抛 :class:`~solution.errors.InputError`，带错误码与字段位置
（位置使用 ``$`` 开头的 JSON Path 风格，可直接定位到出错元素）。
"""

from .errors import (
    E_DUPLICATE, E_MISSING, E_REFERENCE, E_SEMANTIC, E_TYPE,
    E_UNKNOWN, E_VALUE, InputError,
)
from .model import Case, IncidentRequirement, MutexGroup, Quota, Record, Reviewer

_ALLOWED_TOP = {
    "case_id", "departments", "risk_levels", "records", "reviewers",
    "quotas", "mutex_groups", "incident_requirements",
}
_ALLOWED_RECORD = {"id", "department", "risk", "priority", "incidents"}
_ALLOWED_REVIEWER = {"id", "department", "qualifications", "weekly_capacity"}
_ALLOWED_QUOTA = {"dimension", "label", "lower", "upper"}
_ALLOWED_MUTEX = {"id", "records"}
_ALLOWED_INCIDENT = {"incident", "min_records", "distinct_departments"}


def _is_int(x):
    # bool 是 int 的子类，必须显式排除
    return isinstance(x, int) and not isinstance(x, bool)


def _require(obj, key, path, typ=None):
    if not isinstance(obj, dict):
        raise InputError(E_TYPE, path, f"期望对象，实际为 {type(obj).__name__}")
    if key not in obj:
        raise InputError(E_MISSING, f"{path}.{key}", f"缺少必填字段 {key!r}")
    val = obj[key]
    if typ is not None and not isinstance(val, typ):
        want = typ.__name__ if isinstance(typ, type) else str(typ)
        raise InputError(
            E_TYPE, f"{path}.{key}",
            f"字段 {key!r} 期望 {want}，实际为 {type(val).__name__}",
        )
    return val


def _check_unknown(obj, allowed, path):
    extra = set(obj) - allowed
    if extra:
        bad = sorted(extra)[0]
        raise InputError(E_UNKNOWN, f"{path}.{bad}", f"未声明的字段 {bad!r}")


def _nonempty_str(val, path):
    if not isinstance(val, str):
        raise InputError(E_TYPE, path, f"期望字符串，实际为 {type(val).__name__}")
    if not val.strip():
        raise InputError(E_VALUE, path, "字符串不能为空")
    return val


def _id_list(values, path, kind):
    seen = set()
    result = []
    for i, v in enumerate(values):
        p = f"{path}[{i}]"
        s = _nonempty_str(v, p)
        if s in seen:
            raise InputError(E_DUPLICATE, p, f"{kind} ID {s!r} 重复")
        seen.add(s)
        result.append(s)
    return result


def validate(raw) -> Case:
    """校验原始 JSON 对象并返回规范化 :class:`Case`。"""
    if not isinstance(raw, dict):
        raise InputError(E_TYPE, "$", f"根节点期望对象，实际为 {type(raw).__name__}")
    _check_unknown(raw, _ALLOWED_TOP, "$")

    case_id = raw.get("case_id", "case")
    _nonempty_str(case_id, "$.case_id")

    departments = _require(raw, "departments", "$", list)
    if not departments:
        raise InputError(E_VALUE, "$.departments", "至少需要一个部门")
    departments = _id_list(departments, "$.departments", "部门")

    risk_levels = _require(raw, "risk_levels", "$", list)
    if not risk_levels:
        raise InputError(E_VALUE, "$.risk_levels", "至少需要一个风险层级")
    risk_levels = _id_list(risk_levels, "$.risk_levels", "风险层级")

    dept_set, risk_set = set(departments), set(risk_levels)

    # ---------- 记录 ----------
    raw_records = _require(raw, "records", "$", list)
    if not raw_records:
        raise InputError(E_VALUE, "$.records", "至少需要一条记录")
    records, rec_ids = [], set()
    for i, item in enumerate(raw_records):
        p = f"$.records[{i}]"
        if not isinstance(item, dict):
            raise InputError(E_TYPE, p, "记录必须是对象")
        _check_unknown(item, _ALLOWED_RECORD, p)
        rid = _nonempty_str(_require(item, "id", p), f"{p}.id")
        if rid in rec_ids:
            raise InputError(E_DUPLICATE, f"{p}.id", f"记录 ID {rid!r} 重复")
        dept = _nonempty_str(_require(item, "department", p), f"{p}.department")
        if dept not in dept_set:
            raise InputError(
                E_REFERENCE, f"{p}.department",
                f"记录 {rid!r} 引用了未声明部门 {dept!r}",
            )
        risk = _nonempty_str(_require(item, "risk", p), f"{p}.risk")
        if risk not in risk_set:
            raise InputError(
                E_REFERENCE, f"{p}.risk",
                f"记录 {rid!r} 引用了未声明风险层级 {risk!r}",
            )
        priority = _require(item, "priority", p)
        if not _is_int(priority) or priority <= 0:
            raise InputError(
                E_VALUE, f"{p}.priority", "优先级必须是正整数",
            )
        inc_raw = _require(item, "incidents", p, list)
        incs, seen_inc = [], set()
        for j, inc in enumerate(inc_raw):
            ip = f"{p}.incidents[{j}]"
            s = _nonempty_str(inc, ip)
            if s not in seen_inc:
                seen_inc.add(s)
                incs.append(s)
        records.append(Record(rid, dept, risk, priority, tuple(incs)))
        rec_ids.add(rid)
    records.sort(key=lambda r: r.id)

    # ---------- 审查员 ----------
    raw_reviewers = _require(raw, "reviewers", "$", list)
    if not raw_reviewers:
        raise InputError(E_VALUE, "$.reviewers", "至少需要一名审查员")
    reviewers, rev_ids = [], set()
    for i, item in enumerate(raw_reviewers):
        p = f"$.reviewers[{i}]"
        if not isinstance(item, dict):
            raise InputError(E_TYPE, p, "审查员必须是对象")
        _check_unknown(item, _ALLOWED_REVIEWER, p)
        vid = _nonempty_str(_require(item, "id", p), f"{p}.id")
        if vid in rev_ids:
            raise InputError(E_DUPLICATE, f"{p}.id", f"审查员 ID {vid!r} 重复")
        dept = _nonempty_str(_require(item, "department", p), f"{p}.department")
        if dept not in dept_set:
            raise InputError(
                E_REFERENCE, f"{p}.department",
                f"审查员 {vid!r} 引用了未声明部门 {dept!r}",
            )
        quals = _require(item, "qualifications", p, list)
        qset = set()
        for j, q in enumerate(quals):
            qp = f"{p}.qualifications[{j}]"
            s = _nonempty_str(q, qp)
            if s not in risk_set:
                raise InputError(
                    E_REFERENCE, qp,
                    f"审查员 {vid!r} 拥有未声明风险层级资格 {s!r}",
                )
            qset.add(s)
        cap = _require(item, "weekly_capacity", p)
        if not _is_int(cap) or cap <= 0:
            raise InputError(E_VALUE, f"{p}.weekly_capacity", "容量必须是正整数")
        reviewers.append(Reviewer(vid, dept, frozenset(qset), cap))
        rev_ids.add(vid)
    reviewers.sort(key=lambda v: v.id)

    # ---------- 配额（可诊断约束） ----------
    raw_quotas = _require(raw, "quotas", "$", list)
    quotas, quota_keys = [], set()
    seen_dim_labels = {"department": set(), "risk": set()}
    for i, item in enumerate(raw_quotas):
        p = f"$.quotas[{i}]"
        if not isinstance(item, dict):
            raise InputError(E_TYPE, p, "配额必须是对象")
        _check_unknown(item, _ALLOWED_QUOTA, p)
        dim = _nonempty_str(_require(item, "dimension", p), f"{p}.dimension")
        if dim not in ("department", "risk"):
            raise InputError(
                E_VALUE, f"{p}.dimension",
                "dimension 只能是 'department' 或 'risk'",
            )
        label = _nonempty_str(_require(item, "label", p), f"{p}.label")
        valid_labels = dept_set if dim == "department" else risk_set
        if label not in valid_labels:
            raise InputError(
                E_REFERENCE, f"{p}.label",
                f"配额引用了未声明的{dim}标签 {label!r}",
            )
        lower = _require(item, "lower", p)
        upper = _require(item, "upper", p)
        if not _is_int(lower) or lower < 0:
            raise InputError(E_VALUE, f"{p}.lower", "下界必须是非负整数")
        if not _is_int(upper) or upper < 0:
            raise InputError(E_VALUE, f"{p}.upper", "上界必须是非负整数")
        if lower > upper:
            raise InputError(
                E_VALUE, f"{p}.lower", f"下界 {lower} 不能大于上界 {upper}",
            )
        key = (dim, label)
        if key in quota_keys:
            raise InputError(E_DUPLICATE, p, f"{dim}:{label} 的配额重复声明")
        quota_keys.add(key)
        seen_dim_labels[dim].add(label)
        quotas.append(Quota(dim, label, lower, upper))
    # 每个维度标签必须有配额（保证“分别对每个标签计数”有明确上下界）
    for dim, labels in (("department", dept_set), ("risk", risk_set)):
        missing = sorted(labels - seen_dim_labels[dim])
        if missing:
            raise InputError(
                E_MISSING, "$.quotas",
                f"维度 {dim} 缺少标签 {missing} 的配额",
            )

    # ---------- 互斥组（硬约束，允许重叠） ----------
    raw_mutex = _require(raw, "mutex_groups", "$", list)
    mutex_groups, mutex_ids = [], set()
    for i, item in enumerate(raw_mutex):
        p = f"$.mutex_groups[{i}]"
        if not isinstance(item, dict):
            raise InputError(E_TYPE, p, "互斥组必须是对象")
        _check_unknown(item, _ALLOWED_MUTEX, p)
        gid = _nonempty_str(_require(item, "id", p), f"{p}.id")
        if gid in mutex_ids:
            raise InputError(E_DUPLICATE, f"{p}.id", f"互斥组 ID {gid!r} 重复")
        members = _require(item, "records", p, list)
        if len(members) < 2:
            raise InputError(
                E_VALUE, f"{p}.records", "互斥组至少包含两条记录",
            )
        ms = _id_list(members, f"{p}.records", "互斥组记录")
        for m in ms:
            if m not in rec_ids:
                raise InputError(
                    E_REFERENCE, f"{p}.records",
                    f"互斥组 {gid!r} 引用了不存在的记录 {m!r}",
                )
        mutex_groups.append(MutexGroup(gid, tuple(ms)))
        mutex_ids.add(gid)
    mutex_groups.sort(key=lambda g: g.id)

    # ---------- 事故覆盖要求（可诊断约束） ----------
    raw_inc = _require(raw, "incident_requirements", "$", list)
    incidents, inc_ids = [], set()
    # 事故 -> 关联记录索引，用于验证“至少两个不同部门”在结构上有可能
    incident_to_depts = {}
    for rec in records:
        for s in rec.incidents:
            incident_to_depts.setdefault(s, set()).add(rec.department)
    for i, item in enumerate(raw_inc):
        p = f"$.incident_requirements[{i}]"
        if not isinstance(item, dict):
            raise InputError(E_TYPE, p, "事故要求必须是对象")
        _check_unknown(item, _ALLOWED_INCIDENT, p)
        iid = _nonempty_str(_require(item, "incident", p), f"{p}.incident")
        if iid in inc_ids:
            raise InputError(E_DUPLICATE, f"{p}.incident", f"事故 {iid!r} 要求重复")
        min_records = _require(item, "min_records", p)
        distinct_depts = _require(item, "distinct_departments", p)
        if not _is_int(min_records) or min_records < 2:
            raise InputError(
                E_VALUE, f"{p}.min_records", "min_records 必须是 >=2 的整数",
            )
        if not _is_int(distinct_depts) or distinct_depts < 2:
            raise InputError(
                E_VALUE, f"{p}.distinct_departments",
                "distinct_departments 必须是 >=2 的整数",
            )
        if distinct_depts > min_records:
            raise InputError(
                E_VALUE, f"{p}.distinct_departments",
                "distinct_departments 不能大于 min_records",
            )
        if distinct_depts > len(departments):
            raise InputError(
                E_VALUE, f"{p}.distinct_departments",
                "distinct_departments 超过声明的部门总数",
            )
        depts = incident_to_depts.get(iid, set())
        if len(depts) < distinct_depts:
            raise InputError(
                E_SEMANTIC, f"{p}.incident",
                f"事故 {iid!r} 仅在 {sorted(depts) or ['无记录']} 这些部门的记录中出现，"
                f"结构上不可能满足 {distinct_depts} 个不同部门",
            )
        incidents.append(IncidentRequirement(iid, min_records, distinct_depts))
        inc_ids.add(iid)
    incidents.sort(key=lambda x: x.incident)

    return Case(
        departments=departments,
        risk_levels=risk_levels,
        records=records,
        reviewers=reviewers,
        quotas=quotas,
        mutex_groups=mutex_groups,
        incidents=incidents,
        raw=raw,
    )
