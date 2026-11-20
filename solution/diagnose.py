"""最小基数矛盾集诊断。

可诊断约束仅包括配额（``quota:<dimension>:<label>``）与事故要求
（``incident:<id>``）；资格、审查员容量、互斥组始终是硬性约束，不参与
矛盾集，也不允许通过“去掉约束”来满足。

定义
----
对约束子集 S，``feasible(S)`` 表示：在全部硬约束 + S 中软约束下是否存在
合法方案。矛盾集 C 满足 ``feasible(C) = False``；最小基数矛盾集是所有
矛盾集中基数最小者，再按约束 ID 列表的字典序决胜。

实现
----
按基数 k=1,2,... 枚举 C(n,k) 个候选（n <= 16），同基数内按约束 ID 的
字典序生成（``itertools.combinations`` 作用于有序 ID 列表）。每个子集的
可行性判定结果缓存，至多 2^n 个不同子集；找到第一个不可行候选即返回，
因此实际计算量通常远小于 2^n。
"""

import itertools

from .solver import Solver


def _witness_payload(case, solver, selected, assignment):
    """把见证解转成对外 JSON 结构（记录/审查员用原始 ID）。"""
    rec_ids = [r.id for r in case.records]
    rev_ids = [v.id for v in case.reviewers]
    pairs = [
        {"record_id": rec_ids[i], "reviewer_id": rev_ids[j]}
        for i, j in sorted(assignment.items(), key=lambda kv: rec_ids[kv[0]])
    ]
    return {
        "selected_record_ids": [rec_ids[i] for i in sorted(selected)],
        "assignments": pairs,
        "record_count": len(selected),
    }


def _satisfaction_report(case, active_cids, chosen, assignment):
    """列出见证解对软/硬约束的逐条满足情况，便于人工复核。

    chosen: 入选记录索引列表；assignment: {记录索引: 审查员索引}。
    """
    chosen = sorted(chosen)
    dept_cnt, risk_cnt = {}, {}
    for i in chosen:
        rec = case.records[i]
        dept_cnt[rec.department] = dept_cnt.get(rec.department, 0) + 1
        risk_cnt[rec.risk] = risk_cnt.get(rec.risk, 0) + 1

    rows = []
    for q in case.quotas:
        cnt = dept_cnt.get(q.label, 0) if q.dimension == "department" \
            else risk_cnt.get(q.label, 0)
        rows.append({
            "constraint_id": q.cid,
            "kind": "quota",
            "active": q.cid in active_cids,
            "count": cnt,
            "lower": q.lower,
            "upper": q.upper,
            "satisfied": (not q.cid in active_cids) or (q.lower <= cnt <= q.upper),
        })
    for req in case.incidents:
        cid = req.cid
        hit = [i for i in chosen if req.incident in case.records[i].incidents]
        depts = sorted({case.records[i].department for i in hit})
        rows.append({
            "constraint_id": cid,
            "kind": "incident",
            "active": cid in active_cids,
            "supporting_records": [case.records[i].id for i in hit],
            "support_departments": depts,
            "min_records": req.min_records,
            "distinct_departments": req.distinct_departments,
            "satisfied": (cid not in active_cids) or (
                len(hit) >= req.min_records
                and len(depts) >= req.distinct_departments
            ),
        })
    # 硬约束复核
    hard_rows = []
    rev_by_id = {v.id: v for v in case.reviewers}
    rec_by_id = {r.id: r for r in case.records}
    loads = {v.id: 0 for v in case.reviewers}
    hard_ok = True
    chosen_set = set(chosen)
    for i in chosen:
        rid = case.records[i].id
        vid = case.reviewers[assignment[i]].id
        rec, rev = rec_by_id[rid], rev_by_id[vid]
        qualified = rec.risk in rev.qualifications
        cross_dept = rec.department != rev.department
        loads[vid] += 1
        hard_ok &= qualified and cross_dept
        hard_rows.append({
            "record_id": rid, "reviewer_id": vid,
            "qualified": qualified, "cross_department": cross_dept,
        })
    capacity_ok = all(loads[v.id] <= v.weekly_capacity for v in case.reviewers)
    hard_ok &= capacity_ok
    mutex_ok = True
    mutex_detail = []
    for grp in case.mutex_groups:
        hit = [rid for rid in grp.records
               if case.record_index()[rid] in chosen_set]
        mutex_detail.append({"group_id": grp.id, "selected": hit,
                             "satisfied": len(hit) <= 1})
        mutex_ok &= len(hit) <= 1
    hard_ok &= mutex_ok
    return {
        "soft_constraints": rows,
        "hard_constraints": {
            "eligibility_and_cross_department": hard_rows,
            "reviewer_loads": [
                {"reviewer_id": v.id, "used": loads[v.id],
                 "capacity": v.weekly_capacity,
                 "satisfied": loads[v.id] <= v.weekly_capacity}
                for v in case.reviewers
            ],
            "capacity_satisfied": capacity_ok,
            "mutex_groups": mutex_detail,
            "mutex_satisfied": mutex_ok,
            "all_hard_satisfied": hard_ok,
        },
    }


def diagnose(case):
    """执行完整诊断，返回可直接序列化的结果 dict。"""
    all_cids = case.all_diagnosable_cids()
    n = len(all_cids)

    # 可行性缓存：tuple(sorted(cids)) -> (bool, solver_used)
    feasibility_cache = {}
    solver_cache = {}
    checks = 0

    def check(subset_tuple):
        if subset_tuple in feasibility_cache:
            return feasibility_cache[subset_tuple]
        nonlocal checks
        checks += 1
        solver = Solver(case, active_cids=set(subset_tuple))
        witness = solver.feasible_witness()
        ok = witness is not None
        feasibility_cache[subset_tuple] = ok
        solver_cache[subset_tuple] = (solver, witness)
        return ok

    # 1) 硬约束单独是否可行（空软约束集）
    hard_feasible = check(())
    if not hard_feasible:
        return {
            "status": "hard_infeasible",
            "message": "仅硬约束（资格/容量/互斥）即不可行，矛盾不在可诊断约束内",
            "diagnosable_constraint_ids": all_cids,
            "checks_evaluated": checks,
            "feasibility_cache_entries": len(feasibility_cache),
            "enumeration_upper_bound": 2 ** n,
            "contradiction": None,
        }

    # 2) 全量约束若可行，则不存在矛盾集
    full_tuple = tuple(all_cids)
    if check(full_tuple):
        return {
            "status": "feasible",
            "message": "全部约束同时可行，无矛盾集",
            "diagnosable_constraint_ids": all_cids,
            "checks_evaluated": checks,
            "feasibility_cache_entries": len(feasibility_cache),
            "enumeration_upper_bound": 2 ** n,
            "contradiction": None,
        }

    # 3) 按基数升序、ID 字典序枚举最小矛盾集
    contradiction = None
    for k in range(1, n + 1):
        for combo in itertools.combinations(all_cids, k):
            if not check(combo):
                contradiction = list(combo)
                break
        if contradiction is not None:
            break

    # 4) 见证生成
    c_tuple = tuple(contradiction)
    inf_solver, _ = solver_cache[c_tuple]
    infeasible_witness = {
        "subset": contradiction,
        "feasible": False,
        "proof": {
            "method": "exhaustive_branch_and_bound",
            "nodes_visited": inf_solver.nodes_visited,
            "flow_calls": inf_solver.flow_calls,
            "flow_cache_hits": inf_solver.flow_cache_hits,
            "flow_cache_size": len(inf_solver._flow_cache),
            "explanation": (
                "分支定界在硬约束与该子集软约束下遍历完整搜索树，"
                "所有叶子均被配额/事故/互斥/容量剪枝或最大流否决，"
                "不存在任何合法选择与指派"
            ),
        },
    }

    removal_witnesses = []
    for drop in contradiction:
        remaining = tuple(c for c in c_tuple if c != drop)
        ok = check(remaining)
        assert ok, f"最小矛盾集去掉 {drop} 后应可行"  # 最小性保证
        solver, witness = solver_cache[remaining]
        payload = _witness_payload(
            case, solver, witness["selected"], witness["assignment"],
        )
        removal_witnesses.append({
            "removed_constraint_id": drop,
            "remaining_active_constraints": list(remaining),
            "feasible": True,
            "witness": payload,
            "satisfaction": _satisfaction_report(
                case, set(remaining), witness["selected"],
                witness["assignment"],
            ),
            "proof": {
                "method": "branch_and_bound_first_solution",
                "nodes_visited": solver.nodes_visited,
            },
        })

    return {
        "status": "contradiction_found",
        "diagnosable_constraint_ids": all_cids,
        "checks_evaluated": checks,
        "feasibility_cache_entries": len(feasibility_cache),
        "enumeration_upper_bound": 2 ** n,
        "contradiction": {
            "cardinality": len(contradiction),
            "constraint_ids": contradiction,
            "tie_break_rule": (
                "同基数矛盾集按约束 ID 列表的字典序取最小"
            ),
            "infeasibility_witness": infeasible_witness,
            "removal_witnesses": removal_witnesses,
        },
    }
