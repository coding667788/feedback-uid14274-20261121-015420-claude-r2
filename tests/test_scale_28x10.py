"""28 记录 / 10 审查员 / 16 可诊断约束的规模与上界、缓存说明测试。"""

import json
import os
import time
import unittest

from helpers import EXAMPLES, assert_assignment_valid
from solution.diagnose import diagnose
from solution.solver import Solver
from solution.validate import validate


class TestScale28x10(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(EXAMPLES, "demo_feasible_28x10.json")
        cls.raw = json.load(open(path, encoding="utf-8"))
        cls.case = validate(cls.raw)

    def test_dimensions(self):
        self.assertEqual(len(self.case.records), 28)
        self.assertEqual(len(self.case.reviewers), 10)
        self.assertEqual(len(self.case.all_diagnosable_cids()), 16)
        # 互斥组确实重叠
        member_sets = [set(g.records) for g in self.case.mutex_groups]
        overlaps = [
            (a, b) for i, a in enumerate(member_sets)
            for b in member_sets[i + 1:] if a & b
        ]
        self.assertTrue(overlaps, "夹具应包含相互重叠的互斥组")

    def test_plan_runs_fast_and_reports_bounds(self):
        t0 = time.perf_counter()
        result = Solver(self.case).solve_plan()
        elapsed = time.perf_counter() - t0
        self.assertIsNotNone(result)
        self.assertLess(elapsed, 10.0, "28x10 用例应在 10 秒内完成")
        stats = result["stats"]
        # 缓存与上界：流缓存条目数受叶子数约束，上界 2^28 个选择子集
        self.assertGreaterEqual(stats["flow_cache_size"], 1)
        self.assertLessEqual(stats["flow_cache_size"], 2 ** 28)
        self.assertEqual(
            stats["optimality"],
            "exhaustive_branch_and_bound_proven_optimal",
        )
        pairs = [
            {"record_id": self.case.records[i].id,
             "reviewer_id": self.case.reviewers[j].id}
            for i, j in result["assignment"].items()
        ]
        assert_assignment_valid(
            self, self.case,
            [self.case.records[i].id for i in result["selected"]],
            pairs,
        )

    def test_quota_counts_per_label_independently(self):
        result = Solver(self.case).solve_plan()
        chosen = result["selected"]
        dept_cnt, risk_cnt = {}, {}
        for i in chosen:
            r = self.case.records[i]
            dept_cnt[r.department] = dept_cnt.get(r.department, 0) + 1
            risk_cnt[r.risk] = risk_cnt.get(r.risk, 0) + 1
        for q in self.case.quotas:
            cnt = dept_cnt.get(q.label, 0) if q.dimension == "department" \
                else risk_cnt.get(q.label, 0)
            self.assertGreaterEqual(cnt, q.lower)
            self.assertLessEqual(cnt, q.upper)

    def test_diagnose_on_feasible_case(self):
        diag = diagnose(self.case)
        self.assertEqual(diag["status"], "feasible")
        self.assertIsNone(diag["contradiction"])
        # 16 个可诊断约束 -> 枚举上界 2^16
        self.assertEqual(diag["enumeration_upper_bound"], 2 ** 16)


if __name__ == "__main__":
    unittest.main()
