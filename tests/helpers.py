"""测试辅助：本地虚构小型用例的构造器与通用校验。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solution.diagnose import diagnose  # noqa: E402
from solution.flow import assignment_feasible  # noqa: E402
from solution.solver import Solver  # noqa: E402
from solution.validate import validate  # noqa: E402

EXAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples",
)


def make_case(records, reviewers, quotas, mutex_groups=None,
              incidents=None, departments=None, risk_levels=None,
              case_id="t"):
    """用最小样板组装一个合法原始输入（全部字段显式给出）。"""
    departments = departments or sorted({r["department"] for r in records})
    risk_levels = risk_levels or sorted({r["risk"] for r in records})
    return {
        "case_id": case_id,
        "departments": departments,
        "risk_levels": risk_levels,
        "records": records,
        "reviewers": reviewers,
        "quotas": quotas,
        "mutex_groups": mutex_groups or [],
        "incident_requirements": incidents or [],
    }


def quota(dim, label, lower, upper):
    return {"dimension": dim, "label": label,
            "lower": lower, "upper": upper}


def rec(rid, dept, risk, priority=10, incidents=None):
    return {"id": rid, "department": dept, "risk": risk,
            "priority": priority, "incidents": incidents or []}


def rev(vid, dept, quals, cap=5):
    return {"id": vid, "department": dept,
            "qualifications": quals, "weekly_capacity": cap}


def incident(iid, min_records=2, distinct_departments=2):
    return {"incident": iid, "min_records": min_records,
            "distinct_departments": distinct_departments}


def assert_assignment_valid(test, case, selected, assignment):
    """对一个方案断言全部硬约束成立。"""
    solver = Solver(case)
    rec_by_id = {r.id: r for r in case.records}
    rev_by_id = {v.id: v for v in case.reviewers}
    test.assertEqual(len(selected), len(set(selected)), "记录重复入选")
    loads = {v.id: 0 for v in case.reviewers}
    chosen_set = set(selected)
    for pair in assignment:
        rid, vid = pair["record_id"], pair["reviewer_id"]
        r, v = rec_by_id[rid], rev_by_id[vid]
        test.assertIn(rid, chosen_set)
        test.assertIn(r.risk, v.qualifications, f"{vid} 无资格审 {rid}")
        test.assertNotEqual(r.department, v.department,
                            f"{vid} 与 {rid} 同部门")
        loads[vid] += 1
    for vid, n in loads.items():
        test.assertLessEqual(n, rev_by_id[vid].weekly_capacity,
                             f"{vid} 超容量")
    # 互斥
    for grp in case.mutex_groups:
        hit = [rid for rid in grp.records if rid in chosen_set]
        test.assertLessEqual(len(hit), 1, f"互斥组 {grp.id} 命中 {hit}")


def solve(raw):
    case = validate(raw)
    return case, Solver(case).solve_plan()


def plan_pairs(result, case):
    rec_ids = [r.id for r in case.records]
    rev_ids = [v.id for v in case.reviewers]
    return sorted(
        (rec_ids[i], rev_ids[j])
        for i, j in result["assignment"].items()
    )
