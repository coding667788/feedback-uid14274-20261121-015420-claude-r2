"""场景 1：相互重叠的互斥组，每组至多选一条。"""

import unittest

from helpers import make_case, quota, rec, rev, solve, plan_pairs
from solution.validate import validate
from solution.solver import Solver


class TestOverlappingMutex(unittest.TestCase):
    def setUp(self):
        # r3 同时属于 g1 与 g2（组重叠）；g1={r1,r2,r3}, g2={r3,r4,r5}
        self.raw = make_case(
            records=[
                rec("r1", "D1", "R1", 100),
                rec("r2", "D1", "R2", 90),
                rec("r3", "D2", "R1", 80),
                rec("r4", "D2", "R2", 70),
                rec("r5", "D3", "R1", 60),
                rec("r6", "D3", "R2", 50),
            ],
            reviewers=[
                rev("v1", "D2", ["R1", "R2"]),
                rev("v2", "D3", ["R1", "R2"]),
                rev("v3", "D1", ["R1", "R2"]),
            ],
            quotas=[
                quota("department", "D1", 0, 3),
                quota("department", "D2", 0, 3),
                quota("department", "D3", 0, 3),
                quota("risk", "R1", 0, 4),
                quota("risk", "R2", 0, 4),
            ],
            mutex_groups=[
                {"id": "g1", "records": ["r1", "r2", "r3"]},
                {"id": "g2", "records": ["r3", "r4", "r5"]},
            ],
        )

    def test_mutex_enforced_and_overlap_handled(self):
        case, result = solve(self.raw)
        self.assertIsNotNone(result)
        chosen = {case.records[i].id for i in result["selected"]}
        # 每个互斥组至多一条
        self.assertLessEqual(len(chosen & {"r1", "r2", "r3"}), 1)
        self.assertLessEqual(len(chosen & {"r3", "r4", "r5"}), 1)
        # 重叠成员 r3 若入选，则两组其余成员都不能入选
        if "r3" in chosen:
            self.assertFalse(chosen & {"r1", "r2", "r4", "r5"})

    def test_brute_force_optimality_with_mutex(self):
        """与 2^n 暴力枚举对照，确认优先级总分严格最优。"""
        import itertools
        case = validate(self.raw)
        solver = Solver(case)
        _, result = solve(self.raw)
        n = len(case.records)
        best_sum = -1
        for mask in range(1, 1 << n):
            sel = [i for i in range(n) if mask & (1 << i)]
            ids = [case.records[i].id for i in sel]
            if len(set(ids) & {"r1", "r2", "r3"}) > 1:
                continue
            if len(set(ids) & {"r3", "r4", "r5"}) > 1:
                continue
            ok, _ = solver.flow_precheck(sel), None
            from solution.flow import assignment_feasible
            feasible, _ = assignment_feasible(
                sel, solver.eligible, solver.capacities)
            if not feasible:
                continue
            # 配额（下界 0，只查上界）
            dept, risk = {}, {}
            for i in sel:
                r = case.records[i]
                dept[r.department] = dept.get(r.department, 0) + 1
                risk[r.risk] = risk.get(r.risk, 0) + 1
            if any(dept.get(d, 0) > 3 for d in case.departments):
                continue
            if any(risk.get(x, 0) > 4 for x in case.risk_levels):
                continue
            best_sum = max(best_sum, sum(case.records[i].priority
                                         for i in sel))
        self.assertEqual(result["total_priority"], best_sum)


if __name__ == "__main__":
    unittest.main()
