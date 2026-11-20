"""最大流模块的单元测试：容量、强制指派、跨部门资格、字典序指派。"""

import itertools
import random
import unittest

from solution.flow import assignment_feasible, min_cost_lex_assignment


class TestFlow(unittest.TestCase):
    def test_empty_selection(self):
        ok, asg = assignment_feasible([], [[0]], [1])
        self.assertTrue(ok)
        self.assertEqual(asg, {})
        self.assertEqual(min_cost_lex_assignment([], [[0]], [1]), {})

    def test_capacity_bound(self):
        # 两条记录都只能找审查员 0，容量 1 -> 不可行；容量 2 -> 可行
        eligible = [[0], [0]]
        self.assertFalse(assignment_feasible([0, 1], eligible, [1])[0])
        self.assertTrue(assignment_feasible([0, 1], eligible, [2])[0])

    def test_forced_assignment_over_capacity(self):
        eligible = [[0, 1], [0, 1]]
        ok, _ = assignment_feasible(
            [0, 1], eligible, [1, 2], forced={0: 0, 1: 0})
        self.assertFalse(ok)  # 审查员 0 容量 1 却被强制两次

    def test_forced_to_ineligible_rejected(self):
        eligible = [[0], [1]]
        ok, _ = assignment_feasible(
            [0, 1], eligible, [2, 2], forced={0: 1})
        self.assertFalse(ok)

    def test_lex_assignment_brute_force(self):
        random.seed(7)
        for _ in range(400):
            n_rec = random.randint(1, 7)
            n_rev = random.randint(1, 5)
            eligible = [
                sorted(random.sample(
                    range(n_rev), random.randint(1, n_rev)))
                for _ in range(n_rec)
            ]
            caps = [random.randint(1, 3) for _ in range(n_rev)]
            sel = list(range(n_rec))
            if not assignment_feasible(sel, eligible, caps)[0]:
                self.assertIsNone(
                    min_cost_lex_assignment(sel, eligible, caps))
                continue
            best = None
            for combo in itertools.product(*[eligible[i] for i in sel]):
                loads = [0] * n_rev
                good = True
                for vj in combo:
                    loads[vj] += 1
                    if loads[vj] > caps[vj]:
                        good = False
                        break
                if good and (best is None or combo < best):
                    best = combo
            got = min_cost_lex_assignment(sel, eligible, caps)
            self.assertEqual(tuple(got[i] for i in sel), best)

    def test_lex_needs_backtracking_not_greedy(self):
        # 经典反例：记录 0、1 可去 {0,1}，记录 2 只能去 0；容量 [1,2]。
        # 若贪心先把记录 0 放到 0，则记录 2 无处可去（0 已满），必须
        # 回溯把记录 0 改到 1；字典序最小可行解为 (1,1,0)。
        eligible = [[0, 1], [0, 1], [0]]
        caps = [1, 2]
        got = min_cost_lex_assignment([0, 1, 2], eligible, caps)
        self.assertEqual(got, {0: 1, 1: 1, 2: 0})


if __name__ == "__main__":
    unittest.main()
