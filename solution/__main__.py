"""命令行入口：python -m solution <command> CASE.json [--db DB.sqlite]"""

import argparse
import json
import sys

from . import __version__
from .diagnose import _satisfaction_report, diagnose
from .errors import E_PARSE, InputError
from .solver import Solver
from .storage import Storage, case_hash
from .validate import validate


def _emit(obj, exit_code=0):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2,
                                sort_keys=False))
    sys.stdout.write("\n")
    raise SystemExit(exit_code)


def _load_case(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise InputError(E_PARSE, "$.file", f"文件不存在: {path}")
    except json.JSONDecodeError as e:
        raise InputError(
            E_PARSE,
            f"$.line{e.lineno}.col{e.colno}",
            f"JSON 解析失败: {e.msg}",
        )
    return raw


def _plan_result(case):
    solver = Solver(case)
    res = solver.solve_plan()
    rec_ids = [r.id for r in case.records]
    rev_ids = [v.id for v in case.reviewers]

    if res is None:
        # 不可行时委托诊断给出原因线索（不落诊断的完整见证，保持输出聚焦）
        diag = diagnose(case)
        return {
            "status": "infeasible",
            "case_id": case.raw.get("case_id"),
            "case_hash": case_hash(case.raw),
            "message": "不存在满足全部约束的抽查方案",
            "diagnosis_hint": diag,
            "optimal": False,
        }

    chosen = res["selected"]
    assignment = res["assignment"]
    pairs = [
        {"record_id": rec_ids[i], "reviewer_id": rev_ids[j]}
        for i, j in sorted(assignment.items(), key=lambda kv: rec_ids[kv[0]])
    ]
    selected_set = set(chosen)
    detail = []
    for i in chosen:
        rec = case.records[i]
        detail.append({
            "record_id": rec.id,
            "reviewer_id": rev_ids[assignment[i]],
            "department": rec.department,
            "risk": rec.risk,
            "priority": rec.priority,
            "incidents": list(rec.incidents),
        })

    dept_cnt, risk_cnt = {}, {}
    for i in chosen:
        rec = case.records[i]
        dept_cnt[rec.department] = dept_cnt.get(rec.department, 0) + 1
        risk_cnt[rec.risk] = risk_cnt.get(rec.risk, 0) + 1
    quota_report = []
    for q in case.quotas:
        cnt = dept_cnt[q.label] if q.dimension == "department" \
            else risk_cnt.get(q.label, 0)
        quota_report.append({
            "constraint_id": q.cid, "dimension": q.dimension, "label": q.label,
            "count": cnt, "lower": q.lower, "upper": q.upper,
            "satisfied": q.lower <= cnt <= q.upper,
        })

    incident_report = []
    for req in case.incidents:
        hit = [i for i in chosen if req.incident in case.records[i].incidents]
        depts = sorted({case.records[i].department for i in hit})
        incident_report.append({
            "constraint_id": req.cid, "incident": req.incident,
            "supporting_records": [rec_ids[i] for i in hit],
            "support_departments": depts,
            "min_records": req.min_records,
            "distinct_departments": req.distinct_departments,
            "satisfied": (len(hit) >= req.min_records
                          and len(depts) >= req.distinct_departments),
        })

    mutex_report = []
    for grp in case.mutex_groups:
        rec_idx = case.record_index()
        hit = [rid for rid in grp.records if rec_idx[rid] in selected_set]
        mutex_report.append({
            "group_id": grp.id, "selected": hit,
            "satisfied": len(hit) <= 1,
        })

    loads = {v.id: 0 for v in case.reviewers}
    for i, j in assignment.items():
        loads[rev_ids[j]] += 1
    load_report = [
        {"reviewer_id": v.id, "used": loads[v.id],
         "capacity": v.weekly_capacity,
         "satisfied": loads[v.id] <= v.weekly_capacity}
        for v in case.reviewers
    ]

    return {
        "status": "optimal",
        "case_id": case.raw.get("case_id"),
        "case_hash": case_hash(case.raw),
        "objective": {
            "total_priority": res["total_priority"],
            "record_count": res["record_count"],
            "tie_break_rule": (
                "按 (记录 ID, 审查员 ID) 排序列表的字典序最小者"
            ),
        },
        "assignments": pairs,
        "selected_records": detail,
        "quota_usage": quota_report,
        "incident_coverage": incident_report,
        "mutex_compliance": mutex_report,
        "reviewer_loads": load_report,
        "hard_constraints_check": _satisfaction_report(
            case, set(case.all_diagnosable_cids()), chosen, assignment,
        )["hard_constraints"],
        "solver_stats": res["stats"],
        "optimal": True,
        "approximation": False,
    }


def _validate_result(raw, case):
    return {
        "status": "valid",
        "case_id": raw.get("case_id"),
        "case_hash": case_hash(raw),
        "counts": {
            "records": len(case.records),
            "reviewers": len(case.reviewers),
            "quotas": len(case.quotas),
            "mutex_groups": len(case.mutex_groups),
            "incident_requirements": len(case.incidents),
            "diagnosable_constraints": len(case.all_diagnosable_cids()),
        },
        "diagnosable_constraint_ids": case.all_diagnosable_cids(),
    }


def build_parser():
    p = argparse.ArgumentParser(
        prog="python -m solution",
        description="合规离线抽查队列：精确优化与矛盾诊断",
    )
    p.add_argument("command", choices=["validate", "plan", "diagnose", "history"])
    p.add_argument("casefile", help="输入用例 JSON 文件路径")
    p.add_argument("--db", help="SQLite 持久化文件（plan/diagnose/history 需要）")
    p.add_argument("--version", action="version", version=__version__)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        _run(args)
    except InputError as e:
        _emit({"status": "error", "error": e.to_dict()}, exit_code=2)


def _run(args):
    if args.command == "history":
        if not args.db:
            _emit({"error": {
                "code": "E3001", "field": "$.--db",
                "message": "history 命令必须提供 --db DB.sqlite",
            }}, exit_code=2)
        store = Storage(args.db)
        try:
            _emit({"status": "ok", "runs": store.list_runs()})
        finally:
            store.close()

    raw = _load_case(args.casefile)
    case = validate(raw)

    chash = case_hash(raw)
    case_id = raw.get("case_id")

    if args.command == "validate":
        _emit(_validate_result(raw, case))

    if not args.db:
        _emit({"error": {
            "code": "E3001", "field": "$.--db",
            "message": f"{args.command} 命令涉及持久状态，必须提供 --db DB.sqlite",
        }}, exit_code=2)

    store = Storage(args.db)
    try:
        if args.command == "plan":
            result = _plan_result(case)
            seq = store.save_run(
                case_id, chash, "plan", result["status"], result,
            )
            result["run_seq"] = seq
            _emit(result)
        else:  # diagnose
            result = diagnose(case)
            result["case_id"] = case_id
            result["case_hash"] = chash
            seq = store.save_run(
                case_id, chash, "diagnose", result["status"], result,
            )
            result["run_seq"] = seq
            _emit(result)
    finally:
        store.close()


if __name__ == "__main__":
    main()
