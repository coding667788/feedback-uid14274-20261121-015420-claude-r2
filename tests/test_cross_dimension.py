"""场景 2：部门、风险两个维度的配额各自可满足，却无法同时满足。

同一组记录在两个维度上的计数必须一致：D1 的记录全部是 R1，于是
dept:D1 下界 2 与 risk:R1 上界 1 构成跨维度矛盾（基数 2）。
"""

import unittest

from helpers import make_case, quota, rec, rev
from solution.diagnose import diagnose
from solution.solver import Solver
from solution.validate import validate


class TestCrossDimensionConflict(unittest.TestCase):
    def setUp(self):
        self.raw = make_case(
            records=[
                rec("a1", "D1", "R1"), rec("a2", "D1", "R1"),
                rec("b1", "D2", "R2"), rec("b2", "D2", "R2"),
                rec("c1", "D3", "R3"),
            ],
            reviewers=[
                rev("v1", "D2", ["R1", "R2", "R3"]),
                rev("v2", "D3", ["R1", "R2", "R3"]),
                rev("v3", "D1", ["R1", "R2", "R3"]),
            ],
            quotas=[
                quota("department", "D1", 2, 3),   # 至少选 2 条 D1
                quota("risk", "R1", 0, 1),          # 但 R1 至多 1 条
                quota("department", "D2", 0, 3),
                quota("risk", "R2", 0, 3),
                quota("department", "D3", 0, 1),
                quota("risk", "R3", 0, 1),
            ],
        )

    def test_each_dimension_alone_feasible(self):
        case = validate(self.raw)
        cids = case.all_diagnosable_cids()
        # 每个约束单独生效时都可行
        for cid in cids:
            solver = Solver(case, active_cids={cid})
            self.assertIsNotNone(
                solver.feasible_witness(),
                f"约束 {cid} 单独生效时应可行",
            )

    def test_joint_infeasible_and_diagnosed(self):
        case = validate(self.raw)
        # 全量约束下 plan 不可行
        self.assertIsNone(Solver(case).solve_plan())
        diag = diagnose(case)
        self.assertEqual(diag["status"], "contradiction_found")
        c = diag["contradiction"]
        self.assertEqual(c["cardinality"], 2)
        self.assertEqual(
            c["constraint_ids"],
            ["quota:department:D1", "quota:risk:R1"],
        )

    def test_removal_witnesses_are_feasible(self):
        case = validate(self.raw)
        diag = diagnose(case)
        c = diag["contradiction"]
        self.assertEqual(len(c["removal_witnesses"]), 2)
        for w in c["removal_witnesses"]:
            self.assertTrue(w["feasible"])
            # 见证解满足剩余全部生效约束
            report = w["satisfaction"]
            for row in report["soft_constraints"]:
                if row["active"]:
                    self.assertTrue(
                        row["satisfied"],
                        f"移除见证违反生效约束 {row['constraint_id']}",
                    )
            self.assertTrue(
                report["hard_constraints"]["all_hard_satisfied"]
            )


if __name__ == "__main__":
    unittest.main()
