"""确定性：同一逻辑输入反复求解，字节级结果一致；目标三阶段顺序正确。"""

import json
import os
import unittest

from helpers import EXAMPLES, make_case, quota, rec, rev
from solution.solver import Solver
from solution.storage import case_hash
from solution.validate import validate


class TestDeterminismAndObjectives(unittest.TestCase):
    def test_repeated_runs_identical(self):
        path = os.path.join(EXAMPLES, "demo_feasible_28x10.json")
        raw = json.load(open(path, encoding="utf-8"))
        case = validate(raw)
        outputs = []
        for _ in range(3):
            r = Solver(case).solve_plan()
            outputs.append(json.dumps(r, ensure_ascii=False, sort_keys=True))
        self.assertEqual(len(set(outputs)), 1)

    def test_case_hash_stable(self):
        raw1 = {"b": 1, "a": [2, 3]}
        raw2 = {"a": [2, 3], "b": 1}
        self.assertEqual(case_hash(raw1), case_hash(raw2))

    def test_objective_priority_then_count(self):
        # 高优先级组合与低优先级多记录组合竞争：先最大化分数，
        # 同分时再最小化数量
        raw = make_case(
            records=[
                rec("hi1", "D1", "R1", 100),
                rec("hi2", "D2", "R1", 100),
                rec("lo1", "D1", "R1", 1),
                rec("lo2", "D2", "R1", 1),
            ],
            reviewers=[
                rev("v1", "D2", ["R1"], cap=4),
                rev("v2", "D1", ["R1"], cap=4),
            ],
            quotas=[
                quota("department", "D1", 0, 4),
                quota("department", "D2", 0, 4),
                quota("risk", "R1", 0, 2),   # 至多 2 条
            ],
        )
        case = validate(raw)
        r = Solver(case).solve_plan()
        # 上界 2 决定只能选 2 条；选两条高分 -> 200
        self.assertEqual(r["record_count"], 2)
        self.assertEqual(r["total_priority"], 200)
        chosen = {case.records[i].id for i in r["selected"]}
        self.assertEqual(chosen, {"hi1", "hi2"})

    def test_tie_break_by_sorted_pairs(self):
        # 同分同数量的多个方案，决胜取 (记录 ID, 审查员 ID) 字典序最小
        raw = make_case(
            records=[
                rec("r1", "D1", "R1", 10),
                rec("r2", "D2", "R1", 10),
            ],
            reviewers=[
                rev("v1", "D2", ["R1"], cap=2),
                rev("v2", "D3", ["R1"], cap=2),
                rev("v3", "D1", ["R1"], cap=2),
            ],
            quotas=[
                quota("department", "D1", 1, 1),
                quota("department", "D2", 1, 1),
                quota("department", "D3", 0, 1),
                quota("risk", "R1", 2, 2),
            ],
            departments=["D1", "D2", "D3"],
        )
        case = validate(raw)
        r = Solver(case).solve_plan()
        rec_ids = [x.id for x in case.records]
        rev_ids = [x.id for x in case.reviewers]
        pairs = sorted(
            (rec_ids[i], rev_ids[j]) for i, j in r["assignment"].items()
        )
        # r1(D1) 只能由 D2/D3 的 v1/v2 审查，字典序最小为 v1；
        # r2(D2) 可由 D1/D3 的 v3/v2 审查，字典序最小为 v2
        self.assertEqual(pairs, [("r1", "v1"), ("r2", "v2")])

    def test_original_records_not_mutated(self):
        path = os.path.join(EXAMPLES, "demo_feasible_28x10.json")
        raw_before = json.dumps(
            json.load(open(path, encoding="utf-8")), sort_keys=True)
        raw = json.load(open(path, encoding="utf-8"))
        case = validate(raw)
        Solver(case).solve_plan()
        raw_after = json.dumps(raw, sort_keys=True)
        self.assertEqual(raw_before, raw_after)


if __name__ == "__main__":
    unittest.main()
