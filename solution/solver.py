"""分支定界求解器。

决策变量：每条记录 选/不选（按记录 ID 排序后逐个分支，选支优先，
天然让搜索遇到的第一个最优解具有“尽量选小编号记录”的倾向）。

硬约束（任何模式都必须满足，不参与矛盾集诊断）：
  H1 每条记录至多选一次；
  H2 入选记录必须存在合格且跨部门的审查员，并通过最大流完成容量指派；
  H3 每个互斥组至多选一条（组可重叠）。

软约束（可诊断，由 active_cids 决定哪些生效）：
  S1 部门配额：每个部门标签的入选计数落在 [lower, upper]；
  S2 风险配额：每个风险标签的入选计数落在 [lower, upper]；
  S3 事故要求：每个事故由 >=min_records 条、来自 >=distinct_departments
     个不同部门的入选记录支撑（同部门多条只算一个独立部门）。

字典序目标（plan 命令，三阶段精确优化，不使用任何近似）：
  1. 最大化入选记录优先级总和；
  2. 在最高分中最小化入选数；
  3. 按 (记录 ID, 审查员 ID) 排序列表做字典序决胜。
"""

from .flow import assignment_feasible, min_cost_lex_assignment


class Infeasible(Exception):
    """硬约束本身不可行（如存在完全没有合格审查员的记录被强制选择）。"""


class Solver:
    def __init__(self, case, active_cids=None):
        self.case = case
        self.records = case.records
        self.reviewers = case.reviewers
        self.n = len(case.records)
        self.m = len(case.reviewers)

        rec_idx = case.record_index()

        # 合格且跨部门的审查员（按审查员 ID 排序）
        self.eligible = [[] for _ in self.records]
        for i, rec in enumerate(self.records):
            ids = []
            for j, rev in enumerate(self.reviewers):
                if rec.risk in rev.qualifications and rev.department != rec.department:
                    ids.append(j)
            self.eligible[i] = ids
        self.capacities = [v.weekly_capacity for v in self.reviewers]

        # 记录 -> 维度标签 / 优先级
        self.rec_dept = [r.department for r in self.records]
        self.rec_risk = [r.risk for r in self.records]
        self.priority = [r.priority for r in self.records]
        # 后缀优先级和：sum(priority[k:])，用于最大和上界剪枝
        self.suffix_pri = [0] * (self.n + 1)
        for k in range(self.n - 1, -1, -1):
            self.suffix_pri[k] = self.suffix_pri[k + 1] + self.priority[k]

        # 每个标签在位置 k..n-1 内的记录数（仅用于初始化未定计数器）
        self._suffix_by_label = {"department": {}, "risk": {}}
        for dim, attr in (("department", "department"), ("risk", "risk")):
            labels = case.departments if dim == "department" else case.risk_levels
            for lab in labels:
                suffix = [0] * (self.n + 1)
                for k in range(self.n - 1, -1, -1):
                    suffix[k] = suffix[k + 1] + (
                        1 if getattr(self.records[k], attr) == lab else 0
                    )
                self._suffix_by_label[dim][lab] = suffix

        # 生效的软约束
        all_cids = set(case.all_diagnosable_cids())
        if active_cids is None:
            self.active = set(all_cids)
        else:
            unknown = sorted(set(active_cids) - all_cids)
            if unknown:  # pragma: no cover - 调用方负责过滤
                raise ValueError(f"未知约束 ID: {unknown}")
            self.active = set(active_cids)

        self.quota_cids = {q.cid: q for q in case.quotas if q.cid in self.active}
        self.inc_cids = {
            x.cid: x for x in case.incidents if x.cid in self.active
        }

        # 事故 -> 关联记录索引（按记录 ID 排序）；记录 -> 生效事故 cid
        self.inc_records = {}
        for cid, req in self.inc_cids.items():
            self.inc_records[cid] = [
                i for i, r in enumerate(self.records)
                if req.incident in r.incidents
            ]
        self.rec_incidents = [[] for _ in self.records]
        for cid, ids in self.inc_records.items():
            for i in ids:
                self.rec_incidents[i].append(cid)

        # 互斥组 -> 记录索引；记录 -> 组索引
        self.mutex = []
        self.rec_groups = [[] for _ in self.records]
        for g, grp in enumerate(case.mutex_groups):
            idxs = tuple(sorted(rec_idx[r] for r in grp.records))
            self.mutex.append(idxs)
            for i in idxs:
                self.rec_groups[i].append(g)

        # 最大流缓存：(选中元组, 强制指派元组) -> bool
        self._flow_cache = {}
        self.flow_calls = 0
        self.flow_cache_hits = 0
        self.nodes_visited = 0
        self.precheck_rejections = 0

        # 廉价容量必要条件：按风险层级汇总跨部门审查员容量
        self._total_capacity = sum(self.capacities)
        self._risk_capacity = {r: 0 for r in case.risk_levels}
        for j, rev in enumerate(self.reviewers):
            for q in rev.qualifications:
                self._risk_capacity[q] += rev.weekly_capacity

    # ------------------------------------------------------------------
    # 最大流（带缓存）
    # ------------------------------------------------------------------
    def flow_precheck(self, selected):
        """最大流之前的 O(n) 必要条件检查，拦截绝大多数不可行叶子。

        1. 每条入选记录至少有一名合格且跨部门的审查员；
        2. 入选总数不超过审查员总容量；
        3. 每个风险层级的入选数不超过具备该资格的审查员总容量。
        任一失败则一定不可指派；全部通过仍需最大流做充分性判定。
        """
        if len(selected) > self._total_capacity:
            return False
        risk_need = {}
        for i in selected:
            if not self.eligible[i]:
                return False
            r = self.rec_risk[i]
            risk_need[r] = risk_need.get(r, 0) + 1
        for r, need in risk_need.items():
            if need > self._risk_capacity.get(r, 0):
                return False
        return True

    def flow_ok(self, selected, forced=None):
        key = (tuple(selected), tuple(sorted(forced.items())) if forced else ())
        cached = self._flow_cache.get(key)
        if cached is not None:
            self.flow_cache_hits += 1
            return cached
        if not self.flow_precheck(selected):
            self.precheck_rejections += 1
            self._flow_cache[key] = False
            return False
        self.flow_calls += 1
        ok, _ = assignment_feasible(
            selected, self.eligible, self.capacities, forced,
        )
        self._flow_cache[key] = ok
        return ok

    # ------------------------------------------------------------------
    # 主搜索
    # ------------------------------------------------------------------
    def search(self, mode, forced_choose=None, forced_skip=None,
               target_sum=None):
        """执行一次完整 DFS。

        mode:
          "feasible"  任意可行解即返回（返回选中索引列表或 None）；
          "maxsum"    最大化优先级和，再最小化数量；返回 (sel, sum) 或 None；
          "mincount"  给定 target_sum，在和 == target_sum 的解中最小化数量，
                      返回 (sel, sum, count) 或 None。

        forced_choose / forced_skip: 固定选 / 固定不选的记录索引集合。
        """
        forced_choose = set(forced_choose or ())
        forced_skip = set(forced_skip or ())
        if forced_choose & forced_skip:
            return None

        n = self.n
        state = [0] * n            # 0 未定, 1 选, -1 不选
        dept_cnt = {d: 0 for d in self.case.departments}
        risk_cnt = {r: 0 for r in self.case.risk_levels}
        group_taken = [None] * len(self.mutex)   # 组内已选记录索引
        inc_dept_sets = {cid: set() for cid in self.inc_cids}
        selected = []

        # 各标签“尚未决定”的记录数（精确计数，随分支递减、回溯恢复）
        undecided_dept = {
            d: self._suffix_by_label["department"][d][0]
            for d in self.case.departments
        }
        undecided_risk = {
            r: self._suffix_by_label["risk"][r][0]
            for r in self.case.risk_levels
        }

        # 强制项先落地（互斥冲突 / 无资格直接无解）
        for i in sorted(forced_choose):
            state[i] = 1
        for i in sorted(forced_skip):
            state[i] = -1
        for i in sorted(forced_choose):
            if not self.eligible[i]:
                return None
            for g in self.rec_groups[i]:
                if group_taken[g] is not None:
                    return None
                group_taken[g] = i
            selected.append(i)
            dept_cnt[self.rec_dept[i]] += 1
            risk_cnt[self.rec_risk[i]] += 1
            for cid in self.rec_incidents[i]:
                inc_dept_sets[cid].add(self.rec_dept[i])
        for i in sorted(forced_choose | forced_skip):
            undecided_dept[self.rec_dept[i]] -= 1
            undecided_risk[self.rec_risk[i]] -= 1
        selected.sort()

        best = {"sel": None, "sum": None, "count": None}
        cur_sum0 = sum(self.priority[i] for i in selected)

        def quota_upper_ok():
            for cid, q in self.quota_cids.items():
                cnt = dept_cnt[q.label] if q.dimension == "department" \
                    else risk_cnt[q.label]
                if cnt > q.upper:
                    return False
            return True

        def quota_lower_possible():
            for cid, q in self.quota_cids.items():
                if q.dimension == "department":
                    cur, rest = dept_cnt[q.label], undecided_dept[q.label]
                else:
                    cur, rest = risk_cnt[q.label], undecided_risk[q.label]
                if cur + rest < q.lower:
                    return False
            return True

        def incidents_possible(k):
            # 事故部门集合只能由“当前已选”或“位置 >=k 的未定关联记录”扩展
            for cid, req in self.inc_cids.items():
                depts = inc_dept_sets[cid]
                if len(depts) >= req.distinct_departments:
                    continue
                remaining = set(depts)
                for i in self.inc_records[cid]:
                    if i >= k and state[i] == 0:
                        remaining.add(self.rec_dept[i])
                if len(remaining) < req.distinct_departments:
                    return False
            return True

        def dfs(k, cur_sum):
            self.nodes_visited += 1

            if k == n:
                # 叶子：配额下界与事故终态校验（防御性，剪枝应已覆盖）
                for cid, q in self.quota_cids.items():
                    cur = dept_cnt[q.label] if q.dimension == "department" \
                        else risk_cnt[q.label]
                    if not (q.lower <= cur <= q.upper):
                        return
                for cid, req in self.inc_cids.items():
                    depts = inc_dept_sets[cid]
                    if len(depts) < req.distinct_departments:
                        return
                    chosen = sum(
                        1 for i in self.inc_records[cid] if state[i] == 1
                    )
                    if chosen < req.min_records:
                        return
                if not self.flow_ok(selected):
                    return
                self._accept(selected, cur_sum, best, mode, target_sum)
                return

            if state[k] != 0:
                # 强制记录：未定计数在初始化时已扣除，直接下钻
                dfs(k + 1, cur_sum)
                return

            rec = self.records[k]
            # 决定记录 k 之前，先从两个维度的未定计数中扣除
            undecided_dept[rec.department] -= 1
            undecided_risk[rec.risk] -= 1

            # ---- 选支 ----
            can_choose = bool(self.eligible[k])
            if can_choose:
                for g in self.rec_groups[k]:
                    if group_taken[g] is not None:
                        can_choose = False
                        break
            if can_choose:
                state[k] = 1
                selected.append(k)
                dept_cnt[rec.department] += 1
                risk_cnt[rec.risk] += 1
                for g in self.rec_groups[k]:
                    group_taken[g] = k
                added_inc = []
                for cid in self.rec_incidents[k]:
                    before = len(inc_dept_sets[cid])
                    inc_dept_sets[cid].add(rec.department)
                    if len(inc_dept_sets[cid]) != before:
                        added_inc.append(cid)

                # maxsum 上界剪枝：当前和 + 剩余未定优先级和 <=  incumbent 时无希望
                bound_ok = True
                if mode == "maxsum" and best["sel"] is not None:
                    if cur_sum + rec.priority + self.suffix_pri[k + 1] \
                            <= best["sum"]:
                        bound_ok = False
                # 廉价容量必要条件（完整最大流只在叶子调用）
                pre_ok = self.flow_precheck(selected)
                if (bound_ok and pre_ok and quota_upper_ok()
                        and incidents_possible(k + 1)):
                    dfs(k + 1, cur_sum + rec.priority)

                # 回滚
                selected.pop()
                dept_cnt[rec.department] -= 1
                risk_cnt[rec.risk] -= 1
                for g in self.rec_groups[k]:
                    group_taken[g] = None
                for cid in added_inc:
                    inc_dept_sets[cid].discard(rec.department)
                state[k] = 0

            if best["sel"] is not None and mode == "feasible":
                # 提前返回前恢复未定计数
                undecided_dept[rec.department] += 1
                undecided_risk[rec.risk] += 1
                return

            # ---- 不选支 ----
            state[k] = -1
            # mincount：超过 incumbent 数量的分支不再考虑
            count_ok = True
            if mode == "mincount" and best["sel"] is not None:
                if len(selected) >= best["count"]:
                    count_ok = False
            # mincount：剩余记录即便全选也凑不够 target_sum
            sum_possible = True
            if mode == "mincount":
                if cur_sum + self.suffix_pri[k + 1] < target_sum:
                    sum_possible = False
            if (count_ok and sum_possible and quota_lower_possible()
                    and incidents_possible(k + 1)):
                dfs(k + 1, cur_sum)
            state[k] = 0

            undecided_dept[rec.department] += 1
            undecided_risk[rec.risk] += 1

        dfs(0, cur_sum0)
        if best["sel"] is None:
            return None
        if mode == "maxsum":
            return best["sel"], best["sum"]
        if mode == "mincount":
            return best["sel"], best["sum"], best["count"]
        return best["sel"]

    @staticmethod
    def _accept(selected, cur_sum, best, mode, target_sum):
        sel = list(selected)
        if mode == "feasible":
            if best["sel"] is None:
                best["sel"] = sel
            return
        if mode == "maxsum":
            better = (
                best["sel"] is None
                or cur_sum > best["sum"]
                or (cur_sum == best["sum"] and len(sel) < best["count"])
            )
            if better:
                best["sel"], best["sum"], best["count"] = (
                    sel, cur_sum, len(sel),
                )
            return
        if mode == "mincount":
            if cur_sum != target_sum:
                return
            if best["sel"] is None or len(sel) < best["count"]:
                best["sel"], best["sum"], best["count"] = (
                    sel, cur_sum, len(sel),
                )
            return
        raise ValueError(f"未知 mode: {mode}")  # pragma: no cover

    # ------------------------------------------------------------------
    # plan 的三阶段精确求解
    # ------------------------------------------------------------------
    def solve_plan(self):
        """返回字典序最优方案，或 None 表示不可行。"""
        nodes0, calls0, hits0 = (
            self.nodes_visited, self.flow_calls, self.flow_cache_hits,
        )
        lex_nodes = lex_calls = lex_hits = 0

        # 阶段 0+1：可行性 + 最大优先级和（同分中取较小数量）
        res = self.search("maxsum")
        if res is None:
            return None
        sel_max, max_sum = res

        # 阶段 2：在分数 == max_sum 的所有解中最小化入选数
        res2 = self.search("mincount", target_sum=max_sum)
        if res2 is None:  # pragma: no cover - maxsum 已证明可行
            return None
        _, _, min_count = res2

        # 阶段 3a：字典序最小的入选记录集合
        lex_sel, lex_stats = self._lexicographic_selection(max_sum, min_count)
        lex_nodes += lex_stats["nodes_visited"]
        lex_calls += lex_stats["flow_calls"]
        lex_hits += lex_stats["flow_cache_hits"]

        # 阶段 3b：字典序最小的 (记录 ID, 审查员 ID) 指派
        assignment = self._lexicographic_assignment(lex_sel)

        stats = {
            "nodes_visited": self.nodes_visited - nodes0 + lex_nodes,
            "flow_calls": self.flow_calls - calls0 + lex_calls,
            "flow_cache_hits": self.flow_cache_hits - hits0 + lex_hits,
            "flow_cache_size": len(self._flow_cache),
            "optimality": "exhaustive_branch_and_bound_proven_optimal",
        }
        return {
            "selected": lex_sel,
            "assignment": assignment,
            "total_priority": max_sum,
            "record_count": min_count,
            "stats": stats,
        }

    def _lexicographic_selection(self, max_sum, min_count):
        """在保持最高分、最小数量的前提下，使入选记录 ID 集合字典序最小。

        按记录 ID 顺序逐位尝试“强制选当前记录”，仍存在同等最优解则保留强制。
        """
        forced_choose, forced_skip = set(), set()
        agg_nodes = agg_calls = agg_hits = 0
        for k in range(self.n):
            # 独立实例：资格/容量视图相同但搜索状态独立；流缓存仅在同一
            # 实例内共享（键不含实例配置，严禁跨实例复用）
            trial = Solver(self.case, active_cids=self.active)
            res = trial.search(
                "mincount",
                forced_choose=forced_choose | {k},
                forced_skip=forced_skip,
                target_sum=max_sum,
            )
            agg_nodes += trial.nodes_visited
            agg_calls += trial.flow_calls
            agg_hits += trial.flow_cache_hits
            if res is not None:
                _, _, count = res
                if count == min_count:
                    forced_choose.add(k)
                    continue
            forced_skip.add(k)
        return sorted(forced_choose), {
            "nodes_visited": agg_nodes,
            "flow_calls": agg_calls,
            "flow_cache_hits": agg_hits,
        }

    def _lexicographic_assignment(self, selected):
        """对给定入选集合，求按 (记录 ID, 审查员 ID) 字典序最小的指派。

        委托最小费用流：记录->审查员边费用 = 审查员索引 * BIG + 记录索引，
        最小费用满流与字典序比较 (记录 ID, 审查员 ID) 序列等价，一次建网。
        """
        assignment = min_cost_lex_assignment(
            selected, self.eligible, self.capacities,
        )
        if assignment is None:  # pragma: no cover - 入选集合已被证明可指派
            raise Infeasible(
                f"记录集合无法完成指派: "
                f"{[self.records[i].id for i in sorted(selected)]}"
            )
        return assignment

    # ------------------------------------------------------------------
    # 诊断用：任意可行见证（不优化目标），并附字典序最小指派
    # ------------------------------------------------------------------
    def feasible_witness(self):
        sel = self.search("feasible")
        if sel is None:
            return None
        assignment = self._lexicographic_assignment(sel)
        return {"selected": sorted(sel), "assignment": assignment}
