"""确定性夹具生成器（全部为本地虚构数据，无外部来源）。

运行：python tools/generate_fixtures.py
输出：examples/ 下的若干 JSON 用例。
同一份代码反复运行生成字节级一致的文件（无随机数、无时间戳）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solution.diagnose import diagnose  # noqa: E402
from solution.solver import Solver  # noqa: E402
from solution.validate import validate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "examples")


def write_case(name, raw):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def feasible_large_case():
    """28 条记录 / 10 名审查员 / 16 个可诊断约束的可行案例。

    结构：5 个部门、4 个风险层级 -> 9 个配额约束；7 个事故要求 ->
    合计 16 个可诊断约束。互斥组 6 个且刻意相互重叠。
    """
    departments = ["合规部", "零售部", "对公部", "风控部", "科技部"]
    risks = ["L1低", "L2中", "L3高", "L4重大"]

    # 记录：轮转部门与风险，优先级按确定性公式，事故按规则关联
    records = []
    incident_ids = ["INC-A", "INC-B", "INC-C", "INC-D", "INC-E", "INC-F", "INC-G"]
    for k in range(28):
        rid = f"REC{k + 1:03d}"
        dept = departments[k % 5]
        risk = risks[(k * 3) % 4]          # 确定性轮转
        priority = 5 + ((k * 7) % 46)      # 5..50
        incs = []
        # 每条事故挂在 4 条记录上，覆盖至少 3 个部门（含跨部门支撑）
        for a, inc in enumerate(incident_ids):
            if k in {a * 4, a * 4 + 1, a * 4 + 2, a * 4 + 3}:
                incs.append(inc)
        records.append({
            "id": rid, "department": dept, "risk": risk,
            "priority": priority, "incidents": incs,
        })

    # 10 名审查员：部门轮转、资格覆盖各风险层级、容量 2..5
    reviewers = []
    qual_patterns = [
        ["L1低", "L2中"],
        ["L2中", "L3高"],
        ["L3高", "L4重大"],
        ["L1低", "L2中", "L3高"],
        ["L2中", "L3高", "L4重大"],
    ]
    for k in range(10):
        reviewers.append({
            "id": f"REV{k + 1:02d}",
            "department": departments[k % 5],
            "qualifications": qual_patterns[k % 5],
            "weekly_capacity": 2 + (k % 4),   # 2..5
        })

    # 配额：每个部门/风险都给出宽松但有意义的上下界
    quotas = []
    dept_bounds = {
        "合规部": (2, 6), "零售部": (1, 6), "对公部": (1, 6),
        "风控部": (1, 6), "科技部": (0, 6),
    }
    for d in departments:
        lo, hi = dept_bounds[d]
        quotas.append({"dimension": "department", "label": d,
                       "lower": lo, "upper": hi})
    risk_bounds = {"L1低": (1, 8), "L2中": (1, 8), "L3高": (1, 8),
                   "L4重大": (0, 8)}
    for r in risks:
        lo, hi = risk_bounds[r]
        quotas.append({"dimension": "risk", "label": r,
                       "lower": lo, "upper": hi})

    # 6 个互斥组，刻意重叠（REC-005、REC-010 同时属于两个组）
    mutex_groups = [
        {"id": "MG-1", "records": ["REC001", "REC002", "REC006"]},
        {"id": "MG-2", "records": ["REC003", "REC005", "REC010"]},
        {"id": "MG-3", "records": ["REC005", "REC015", "REC020"]},
        {"id": "MG-4", "records": ["REC010", "REC011", "REC025"]},
        {"id": "MG-5", "records": ["REC007", "REC012", "REC017", "REC022"]},
        {"id": "MG-6", "records": ["REC008", "REC013", "REC018", "REC023"]},
    ]

    incident_requirements = [
        {"incident": inc, "min_records": 2, "distinct_departments": 2}
        for inc in incident_ids
    ]

    return {
        "case_id": "demo-feasible-28x10",
        "departments": departments,
        "risk_levels": risks,
        "records": records,
        "reviewers": reviewers,
        "quotas": quotas,
        "mutex_groups": mutex_groups,
        "incident_requirements": incident_requirements,
    }


def infeasible_case():
    """不可行案例：两个并列的最小（基数 2）矛盾集，验证 ID 字典序决胜。

    核心观察：同一组入选记录在“部门维度”和“风险维度”上的计数必须
    一致。令 D1 的记录全部为 R1、D2 的记录全部为 R2，则：
      - 冲突对 1：dept:D1 下界 2 与 risk:R1 上界 1 不可能同时成立；
      - 冲突对 2：dept:D2 下界 2 与 risk:R2 上界 1 不可能同时成立。
    每个约束单独都可满足，不存在基数 1 矛盾集；两个基数 2 矛盾集
    并列，按约束 ID 列表字典序决胜取
    [quota:department:D1, quota:risk:R1]。
    """
    departments = ["D1", "D2", "D3"]
    risks = ["R1", "R2", "R3"]
    records = [
        {"id": "A1", "department": "D1", "risk": "R1", "priority": 10,
         "incidents": []},
        {"id": "A2", "department": "D1", "risk": "R1", "priority": 10,
         "incidents": []},
        {"id": "A3", "department": "D1", "risk": "R1", "priority": 10,
         "incidents": []},
        {"id": "A4", "department": "D2", "risk": "R2", "priority": 10,
         "incidents": []},
        {"id": "A5", "department": "D2", "risk": "R2", "priority": 10,
         "incidents": []},
        {"id": "A6", "department": "D2", "risk": "R2", "priority": 10,
         "incidents": []},
        {"id": "A7", "department": "D3", "risk": "R3", "priority": 10,
         "incidents": []},
    ]
    reviewers = [
        {"id": "V1", "department": "D2",
         "qualifications": ["R1", "R2", "R3"], "weekly_capacity": 7},
        {"id": "V2", "department": "D3",
         "qualifications": ["R1", "R2", "R3"], "weekly_capacity": 7},
        {"id": "V3", "department": "D1",
         "qualifications": ["R1", "R2", "R3"], "weekly_capacity": 7},
    ]
    quotas = [
        {"dimension": "department", "label": "D1", "lower": 2, "upper": 3},
        {"dimension": "risk", "label": "R1", "lower": 0, "upper": 1},
        {"dimension": "department", "label": "D2", "lower": 2, "upper": 3},
        {"dimension": "risk", "label": "R2", "lower": 0, "upper": 1},
        {"dimension": "department", "label": "D3", "lower": 0, "upper": 1},
        {"dimension": "risk", "label": "R3", "lower": 0, "upper": 1},
    ]
    return {
        "case_id": "demo-infeasible-quota",
        "departments": departments,
        "risk_levels": risks,
        "records": records,
        "reviewers": reviewers,
        "quotas": quotas,
        "mutex_groups": [],
        "incident_requirements": [],
    }


def main():
    p1 = write_case("demo_feasible_28x10.json", feasible_large_case())
    raw1 = json.load(open(p1, encoding="utf-8"))
    case1 = validate(raw1)
    res = Solver(case1).solve_plan()
    assert res is not None, "可行夹具生成后必须可解"
    print(f"[ok] {os.path.basename(p1)}: 最优优先级={res['total_priority']}, "
          f"入选={res['record_count']}, 节点={res['stats']['nodes_visited']}")

    p2 = write_case("demo_infeasible_quota.json", infeasible_case())
    raw2 = json.load(open(p2, encoding="utf-8"))
    case2 = validate(raw2)
    diag = diagnose(case2)
    assert diag["status"] == "contradiction_found"
    c = diag["contradiction"]
    print(f"[ok] {os.path.basename(p2)}: 矛盾集基数={c['cardinality']}, "
          f"约束={c['constraint_ids']}, 可行性检查次数={diag['checks_evaluated']}")


if __name__ == "__main__":
    main()
