"""场景 3：只有某个可调度指派才能达成最高分。

构造：两条高分记录 h1、h2 都只能由同一名审查员 v* 审查（容量 1），
而一条低分记录 lo 可以由其他人审查。若忽略容量/指派，贪心会同时选
h1、h2 并在指派阶段失败；正确的最优解必须在选择阶段就通过最大流
剪枝放弃其中一条高分记录，改选可调度组合。
"""

import unittest

from helpers import make_case, quota, rec, rev, solve, plan_pairs
from solution.flow import assignment_feasible
from solution.validate import validate
from solution.solver import Solver


class TestSchedulingDrivenOptimum(unittest.TestCase):
    def setUp(self):
        # v1 是唯一有 R2 资格且跨 D1 部门的审查员，容量仅 1
        self.raw = make_case(
            records=[
                rec("h1", "D1", "R2", 100),   # 仅 v1 可审
                rec("h2", "D1", "R2", 99),    # 仅 v1 可审
                rec("lo", "D2", "R1", 10),    # v2 可审
                rec("mid", "D3", "R1", 50),   # v2/v3 可审
            ],
            reviewers=[
                rev("v1", "D2", ["R2"], cap=1),
                rev("v2", "D1", ["R1"], cap=2),
                rev("v3", "D2", ["R1"], cap=2),
            ],
            quotas=[
                quota("department", "D1", 0, 2),
                quota("department", "D2", 0, 2),
                quota("department", "D3", 0, 2),
                quota("risk", "R1", 0, 4),
                quota("risk", "R2", 0, 1),
            ],
        )

    def test_both_high_records_together_unschedulable(self):
        case = validate(self.raw)
        solver = Solver(case)
        h1 = case.record_index()["h1"]
        h2 = case.record_index()["h2"]
        ok, _ = assignment_feasible(
            [h1, h2], solver.eligible, solver.capacities)
        self.assertFalse(ok, "h1、h2 同时入选应因 v1 容量 1 而不可指派")

    def test_optimal_plan_is_schedulable_and_maximal(self):
        case, result = solve(self.raw)
        self.assertIsNotNone(result)
        chosen = {case.records[i].id for i in result["selected"]}
        # 两条高分记录不能同时出现
        self.assertLessEqual(len(chosen & {"h1", "h2"}), 1)
        # 必须保留恰好一条高分记录（h1 优先，因优先级更高）
        self.assertIn("h1", chosen)
        self.assertNotIn("h2", chosen)
        # 最优分 = h1(100) + mid(50) + lo(10) = 160
        self.assertEqual(result["total_priority"], 160)
        # 指派真实可调度
        ok, _ = assignment_feasible(
            result["selected"], Solver(case).eligible,
            Solver(case).capacities, result["assignment"],
        )
        self.assertTrue(ok)

    def test_brute_force_confirms_score(self):
        import itertools
        case = validate(self.raw)
        solver = Solver(case)
        n = len(case.records)
        best = -1
        for mask in range(1, 1 << n):
            sel = [i for i in range(n) if mask & (1 << i)]
            feasible, _ = assignment_feasible(
                sel, solver.eligible, solver.capacities)
            if not feasible:
                continue
            dept, risk = {}, {}
            for i in sel:
                r = case.records[i]
                dept[r.department] = dept.get(r.department, 0) + 1
                risk[r.risk] = risk.get(r.risk, 0) + 1
            if risk.get("R2", 0) > 1:
                continue
            best = max(best, sum(case.records[i].priority for i in sel))
        _, result = solve(self.raw)
        self.assertEqual(result["total_priority"], best)


if __name__ == "__main__":
    unittest.main()
