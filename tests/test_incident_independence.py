"""场景 4：同一事故由同部门多条记录支撑时，独立部门数仍为 1，不满足要求。

INC-1 要求 2 条记录、2 个不同部门。D1 下有两条关联记录（a1、a2），
D2 下有一条（b1）。只选 a1、a2 时记录数达标但部门数只有 1，必须
再选 b1（或其他部门的关联记录）才能满足。
"""

import unittest

from helpers import make_case, quota, rec, rev, incident
from solution.solver import Solver
from solution.validate import validate


def incident_report(case, selected, incident_id):
    chosen = set(selected)
    req = next(x for x in case.incidents if x.incident == incident_id)
    hit = [i for i in chosen if incident_id in case.records[i].incidents]
    depts = sorted({case.records[i].department for i in hit})
    return {
        "constraint_id": req.cid,
        "supporting_records": [case.records[i].id for i in hit],
        "support_departments": depts,
        "satisfied": (len(hit) >= req.min_records
                      and len(depts) >= req.distinct_departments),
    }


class TestIncidentDepartmentIndependence(unittest.TestCase):
    def setUp(self):
        self.raw = make_case(
            records=[
                rec("a1", "D1", "R1", 100, ["INC-1"]),
                rec("a2", "D1", "R1", 90, ["INC-1"]),
                rec("b1", "D2", "R1", 80, ["INC-1"]),
                rec("c1", "D3", "R1", 10, []),
            ],
            reviewers=[
                rev("v1", "D2", ["R1"], cap=4),
                rev("v2", "D3", ["R1"], cap=4),
                rev("v3", "D1", ["R1"], cap=4),
            ],
            quotas=[
                quota("department", "D1", 0, 4),
                quota("department", "D2", 0, 4),
                quota("department", "D3", 0, 4),
                quota("risk", "R1", 0, 4),
            ],
            incidents=[incident("INC-1", 2, 2)],
        )

    def test_same_department_pair_does_not_satisfy(self):
        """只选同部门的 a1、a2（即使加上无关的 c1）也不满足事故要求。"""
        case = validate(self.raw)
        idx = case.record_index()
        for only in (["a1", "a2"], ["a1", "a2", "c1"]):
            forced = {idx[x] for x in only}
            sub = Solver(case)
            res = sub.search(
                "feasible",
                forced_choose=forced,
                forced_skip=set(range(len(case.records))) - forced,
            )
            self.assertIsNone(
                res, f"仅 {only} 不应满足 INC-1 的两部门独立支撑要求",
            )

    def test_optimal_plan_covers_two_departments(self):
        case = validate(self.raw)
        result = Solver(case).solve_plan()
        self.assertIsNotNone(result)
        report = incident_report(case, result["selected"], "INC-1")
        self.assertTrue(report["satisfied"])
        self.assertGreaterEqual(len(report["support_departments"]), 2)
        self.assertGreaterEqual(len(report["supporting_records"]), 2)
        # 跨部门的 b1 必须入选
        chosen = {case.records[i].id for i in result["selected"]}
        self.assertIn("b1", chosen)

    def test_record_can_link_multiple_incidents(self):
        """一条记录关联多个事故时，同时为两个事故提供支撑。"""
        raw = make_case(
            records=[
                rec("x1", "D1", "R1", 10, ["I1", "I2"]),
                rec("x2", "D2", "R1", 10, ["I1"]),
                rec("x3", "D3", "R1", 10, ["I2"]),
            ],
            reviewers=[
                rev("v1", "D2", ["R1"]), rev("v2", "D3", ["R1"]),
                rev("v3", "D1", ["R1"]),
            ],
            quotas=[
                quota("department", d, 0, 3)
                for d in ["D1", "D2", "D3"]
            ] + [quota("risk", "R1", 0, 3)],
            incidents=[incident("I1", 2, 2), incident("I2", 2, 2)],
        )
        case = validate(raw)
        result = Solver(case).solve_plan()
        self.assertIsNotNone(result)
        r1 = incident_report(case, result["selected"], "I1")
        r2 = incident_report(case, result["selected"], "I2")
        self.assertTrue(r1["satisfied"])
        self.assertTrue(r2["satisfied"])
        self.assertIn("x1", r1["supporting_records"])
        self.assertIn("x1", r2["supporting_records"])


if __name__ == "__main__":
    unittest.main()
