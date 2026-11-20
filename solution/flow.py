"""网络流：指派可行性与字典序最小指派（Dinic 最大流）。

网络结构（容量均为整数）：

    源 S -> 记录节点 r_i（容量 1）
    记录 r_i -> 合格审查员 v_j（容量 1，仅合格且跨部门时连边）
    审查员 v_j -> 汇 T（容量 = 该审查员单周容量，已扣除强制指派）

每条入选记录需要 1 单位流；最大流等于入选记录数当且仅当存在合法指派。

字典序最小指派（按 (记录 ID, 审查员 ID) 排序）通过“逐记录字典序贪心 +
最大流可行性担保”得到：按记录 ID 顺序、审查员 ID 顺序尝试强制指派，
每次强制后重建最大流验证是否仍可补全，可行则固定。最大流担保每一步
都不会走入死胡同，故结果即字典序最优；网络规模小（记录 <= 28、
审查员 <= 10），重建开销可忽略。
"""

from collections import deque


class _Edge:
    __slots__ = ("to", "rev", "cap")

    def __init__(self, to, rev, cap):
        self.to = to
        self.rev = rev
        self.cap = cap


class Dinic:
    def __init__(self, n):
        self.n = n
        self.g = [[] for _ in range(n)]
        self.level = [-1] * n
        self.it = [0] * n

    def add_edge(self, fr, to, cap):
        fwd = _Edge(to, len(self.g[to]), cap)
        rev = _Edge(fr, len(self.g[fr]), 0)
        self.g[fr].append(fwd)
        self.g[to].append(rev)
        return fwd

    def _bfs(self, s, t):
        level = self.level
        for i in range(self.n):
            level[i] = -1
        level[s] = 0
        q = deque([s])
        g = self.g
        while q:
            v = q.popleft()
            lv = level[v] + 1
            for e in g[v]:
                if e.cap > 0 and level[e.to] < 0:
                    level[e.to] = lv
                    q.append(e.to)
        return level[t] >= 0

    def _dfs(self, v, t, f):
        if v == t:
            return f
        g = self.g
        for i in range(self.it[v], len(g[v])):
            self.it[v] = i
            e = g[v][i]
            if e.cap > 0 and self.level[e.to] == self.level[v] + 1:
                d = self._dfs(e.to, t, min(f, e.cap))
                if d > 0:
                    e.cap -= d
                    g[e.to][e.rev].cap += d
                    return d
        return 0

    def max_flow(self, s, t, limit=None):
        flow = 0
        inf = 10 ** 18 if limit is None else limit
        while self._bfs(s, t):
            self.it = [0] * self.n
            while True:
                f = self._dfs(s, t, inf - flow if limit else inf)
                if f == 0:
                    break
                flow += f
                if limit is not None and flow >= limit:
                    return flow
        return flow


def _build_network(selected, eligible, capacities, forced):
    """构建 Dinic 流网络，含强制指派。

    审查员 vj 的总容量 ``capacities[vj]`` 分成两条入汇管道：
      - 弹性管道 vj -> T，容量 = 原容量 - 强制给 vj 的记录数，供普通
        记录使用；
      - 强制记录 ri 只连一条 ri -> vj 的独占边，其流量经弹性管道之外的
        同一审查员节点汇出——实现上把审查员->汇点容量直接设为原容量，
        并在源头保证强制边数量已计入预占，普通记录可用容量相应减少。
    为避免双重计数，普通记录边的目标改为“弹性审查员节点” vj'，
    vj' -> vj 容量 = 原容量 - 强制数；强制记录直接连 vj；vj -> T
    容量 = 原容量。
    """
    forced = forced or {}
    sel = sorted(set(selected))
    n_rec, n_rev = len(eligible), len(capacities)
    # 节点：记录 [0,n_rec)；主审查员 [n_rec,n_rec+n_rev)；
    # 弹性审查员 [n_rec+n_rev, n_rec+2*n_rev)；S、T
    S = n_rec + 2 * n_rev
    T = S + 1
    net = Dinic(T + 1)

    forced_count = [0] * n_rev
    for ri, vj in forced.items():
        if ri not in sel or vj not in eligible[ri]:
            return None
        forced_count[vj] += 1
    for vj in range(n_rev):
        if forced_count[vj] > capacities[vj]:
            return None

    def main_rev(vj):
        return n_rec + vj

    def flex_rev(vj):
        return n_rec + n_rev + vj

    rec_node = {ri: i for i, ri in enumerate(sel)}
    for ri in sel:
        net.add_edge(S, rec_node[ri], 1)
    for vj in range(n_rev):
        # 主审查员 -> 汇点：完整容量（强制 + 弹性流量合计不超过它）
        net.add_edge(main_rev(vj), T, capacities[vj])
        # 弹性审查员 -> 主审查员：扣除强制后的余量
        residual = capacities[vj] - forced_count[vj]
        if residual > 0:
            net.add_edge(flex_rev(vj), main_rev(vj), residual)
    for ri in sel:
        u = rec_node[ri]
        if ri in forced:
            net.add_edge(u, main_rev(forced[ri]), 1)  # 强制：直连主节点
            continue
        for vj in eligible[ri]:
            if capacities[vj] - forced_count[vj] > 0:
                net.add_edge(u, flex_rev(vj), 1)
    return net, S, T, sel, rec_node, n_rec


def assignment_feasible(selected, eligible, capacities, forced=None):
    """判定给定入选记录集合能否完成合法指派。

    返回 ``(ok, assignment)``：不可行时 assignment 为 None；可行时为
    ``{记录索引: 审查员索引}``（恢复出的其中一个最大流指派，非字典序最优）。
    """
    selected = sorted(set(selected))
    if not selected:
        return True, {}
    built = _build_network(selected, eligible, capacities, forced)
    if built is None:
        return False, None
    din, S, T, sel, rec_node, n_rec = built
    n_rev = len(capacities)
    need = len(sel)
    if din.max_flow(S, T, limit=need) != need:
        return False, None
    assignment = dict(forced or {})
    main_lo, main_hi = n_rec, n_rec + n_rev
    flex_lo, flex_hi = n_rec + n_rev, n_rec + 2 * n_rev
    for ri in sel:
        if ri in (forced or {}):
            continue
        u = rec_node[ri]
        for e in din.g[u]:
            if main_lo <= e.to < main_hi:  # 强制记录直连主节点（理论上不在此分支）
                assignment[ri] = e.to - n_rec
                break
            if flex_lo <= e.to < flex_hi and e.cap == 0:
                # 弹性节点 -> 主审查员 -> 汇点，取弹性节点编号反推
                assignment[ri] = e.to - (n_rec + n_rev)
                break
        if ri not in assignment:  # pragma: no cover
            return False, None
    return True, assignment


def min_cost_lex_assignment(selected, eligible, capacities):
    """求入选集合的字典序最小合法指派。

    算法（逐记录字典序贪心，每步用最大流做可行性担保）：
    按记录索引顺序处理；对每条记录，按审查员索引顺序尝试把它强制指派
    给该审查员，若“已固定前缀 + 本次强制”在最大流下仍可补全，则固定。
    最大流保证每一步选择都不会走入死胡同，因此结果即字典序最小指派。
    网络规模小（记录 <= 28、审查员 <= 10），每次重建的开销可忽略。
    返回 {记录索引: 审查员索引} 或 None。
    """
    selected = sorted(set(selected))
    if not selected:
        return {}
    ok, _ = assignment_feasible(selected, eligible, capacities)
    if not ok:
        return None
    forced = {}
    for ri in selected:
        placed = False
        for vj in eligible[ri]:  # eligible 已按审查员 ID 排序
            trial = dict(forced)
            trial[ri] = vj
            ok, _ = assignment_feasible(selected, eligible, capacities, trial)
            if ok:
                forced = trial
                placed = True
                break
        if not placed:  # pragma: no cover - 整体可行性已验证
            return None
    return forced
