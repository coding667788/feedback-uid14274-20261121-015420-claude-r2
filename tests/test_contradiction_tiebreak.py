"""场景 5：两个并列的最小矛盾集，按约束 ID 列表字典序决胜。

同时验证：矛盾集本身的无解证明，以及逐个去掉一条约束后的可行见证。
"""

import itertools
import unittest

from helpers import make_case, quota, rec, rev
from solution.diagnose import diagnose
from solution.solver import Solver
from solution.validate import validate


class TestContradictionTieBreak(unittest.TestCase):
    def setUp(self):
        # 两个基数 2 矛盾集：
        #   (dept:D1 下界2, risk:R1 上界1) —— D1 记录全是 R1
        #   (dept:D2 下界2, risk:R2 上界1) —— D2 记录全是 R2
        self.raw = make_case(
            records=[
                rec("A1", "D1", "R1"), rec("A2", "D1", "R1"),
                rec("A3", "D1", "R1"),
                rec("A4", "D2", "R2"), rec("A5", "D2", "R2"),
                rec("A6", "D2", "R2"),
                rec("A7", "D3", "R3"),
            ],
            reviewers=[
                rev("V1", "D2", ["R1", "R2", "R3"]),
                rev("V2", "D3", ["R1", "R2", "R3"]),
                rev("V3", "D1", ["R1", "R2", "R3"]),
            ],
            quotas=[
                quota("department", "D1", 2, 3),
                quota("risk", "R1", 0, 1),
                quota("department", "D2", 2, 3),
                quota("risk", "R2", 0, 1),
                quota("department", "D3", 0, 1),
                quota("risk", "R3", 0, 1),
            ],
        )
        self.case = validate(self.raw)

    def test_exactly_two_cardinality_two_contradictions(self):
        cids = self.case.all_diagnosable_cids()
        card2 = []
        for combo in itertools.combinations(cids, 2):
            solver = Solver(self.case, active_cids=set(combo))
            if solver.feasible_witness() is None:
                card2.append(list(combo))
        # 不存在基数 1 矛盾集
        for cid in cids:
            self.assertIsNotNone(
                Solver(self.case, active_cids={cid}).feasible_witness()
            )
        self.assertEqual(
            sorted(card2),
            [
                ["quota:department:D1", "quota:risk:R1"],
                ["quota:department:D2", "quota:risk:R2"],
            ],
        )

    def test_diagnose_picks_lexicographically_smallest(self):
        diag = diagnose(self.case)
        self.assertEqual(diag["status"], "contradiction_found")
        c = diag["contradiction"]
        self.assertEqual(c["cardinality"], 2)
        # 字典序："quota:department:D1" < "quota:department:D2"
        self.assertEqual(
            c["constraint_ids"],
            ["quota:department:D1", "quota:risk:R1"],
        )

    def test_infeasibility_witness_and_removal_witnesses(self):
        diag = diagnose(self.case)
        c = diag["contradiction"]
        # 无解证明：完整搜索的节点数与流调用统计存在
        proof = c["infeasibility_witness"]["proof"]
        self.assertFalse(c["infeasibility_witness"]["feasible"])
        self.assertGreaterEqual(proof["nodes_visited"], 1)

        # 逐条去掉一条后的可行见证
        self.assertEqual(len(c["removal_witnesses"]), 2)
        removed = set()
        for w in c["removal_witnesses"]:
            self.assertTrue(w["feasible"])
            removed.add(w["removed_constraint_id"])
            # 剩余约束恰好是矛盾集去掉该条
            self.assertEqual(
                sorted(w["remaining_active_constraints"]),
                sorted(set(c["constraint_ids"]) - {w["removed_constraint_id"]}),
            )
            # 见证满足剩余软约束与全部硬约束
            for row in w["satisfaction"]["soft_constraints"]:
                if row["active"]:
                    self.assertTrue(row["satisfied"])
            self.assertTrue(
                w["satisfaction"]["hard_constraints"]["all_hard_satisfied"]
            )
        self.assertEqual(removed, set(c["constraint_ids"]))

    def test_cache_and_upper_bound_reported(self):
        diag = diagnose(self.case)
        n = len(self.case.all_diagnosable_cids())
        self.assertEqual(diag["enumeration_upper_bound"], 2 ** n)
        self.assertLessEqual(
            diag["feasibility_cache_entries"], 2 ** n,
        )
        self.assertLessEqual(
            diag["checks_evaluated"], 2 ** n,
        )


if __name__ == "__main__":
    unittest.main()
