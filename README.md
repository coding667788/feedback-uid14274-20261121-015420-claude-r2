# 合规团队离线抽查队列

精确求解合规抽查的选择与审查员指派问题，并在无解时给出**最小基数矛盾集**
诊断。仅使用 Python 3.12 标准库，CPU 运行，无第三方依赖。

## 1. 问题定义

给定：

- 待审记录：每条含 ID、所属部门、风险层级、优先级、关联历史事故 ID 列表；
- 部门集合与风险层级集合；
- 每个部门标签、每个风险层级标签的抽查数量上下界（配额）；
- 互斥样本组：组内至多选一条，组与组允许相互重叠；
- 审查员：所属部门、可审风险层级资格、单周容量。

规则：

1. 每条记录至多入选一次，审核不修改原记录；
2. 入选记录必须指派给**具备对应风险资格且不来自该记录部门**的审查员；
3. 同一审查员收到的指派数不超过其单周容量；
4. 每个互斥组至多一条入选；
5. 部门配额与风险配额分别对两个维度的**每个标签独立计数**，而非只校验
   交叉分组；
6. 每个必须覆盖的事故，至少由 `min_records` 条入选记录支撑，且这些记录
   来自至少 `distinct_departments` 个不同部门（同一部门的多条记录只算
   一个独立部门）；一条记录可关联多个事故。

优化目标（字典序，三阶段严格按序）：

1. 最大化入选记录优先级总分；
2. 在最高分方案中最小化入选记录数；
3. 仍并列时，取按记录 ID 排序的 `(记录 ID, 审查员 ID)` 列表字典序最小者。

## 2. 命令

```
python -m solution <command> CASE.json [--db DB.sqlite]
```

| 命令 | 需要 --db | 作用 |
|---|---|---|
| `validate` | 否 | 仅做结构与语义校验 |
| `plan` | 是 | 求字典序最优抽查方案；无解时返回 `infeasible` 并附诊断线索 |
| `diagnose` | 是 | 求最小基数矛盾集与逐条移除的可行见证 |
| `history` | 是 | 列出该库中所有历史运行 |

标准输出为 UTF-8 JSON；成功退出码 0，输入错误退出码 2。同一逻辑输入
（规范化 SHA-256 哈希）产生同一结果。

## 3. 输入格式（CASE.json）

```json
{
  "case_id": "demo-feasible-28x10",
  "departments": ["合规部", "零售部"],
  "risk_levels": ["L1低", "L2中"],
  "records": [
    {
      "id": "REC001",
      "department": "合规部",
      "risk": "L1低",
      "priority": 12,
      "incidents": ["INC-A"]
    }
  ],
  "reviewers": [
    {
      "id": "REV01",
      "department": "零售部",
      "qualifications": ["L1低", "L2中"],
      "weekly_capacity": 3
    }
  ],
  "quotas": [
    {"dimension": "department", "label": "合规部", "lower": 2, "upper": 6},
    {"dimension": "risk", "label": "L1低", "lower": 1, "upper": 8}
  ],
  "mutex_groups": [
    {"id": "MG-1", "records": ["REC001", "REC002"]}
  ],
  "incident_requirements": [
    {"incident": "INC-A", "min_records": 2, "distinct_departments": 2}
  ]
}
```

字段约束：

- 所有 ID 为非空字符串且在各自命名空间内唯一；
- `priority`、`weekly_capacity` 为正整数（布尔值不接受）；
- 配额 `0 <= lower <= upper`，每个部门/风险标签都必须有配额；
- 互斥组至少含两条记录，引用必须存在，组可重叠；
- `min_records >= 2`、`distinct_departments >= 2` 且不超过部门总数；
- 事故关联记录所在部门数少于 `distinct_departments` 时直接结构报错。

## 4. 输出格式

### 4.1 plan（有解）

```json
{
  "status": "optimal",
  "case_id": "...",
  "case_hash": "018300781338e4ca",
  "objective": {
    "total_priority": 508,
    "record_count": 16,
    "tie_break_rule": "按 (记录 ID, 审查员 ID) 排序列表的字典序最小者"
  },
  "assignments": [
    {"record_id": "REC003", "reviewer_id": "REV02"}
  ],
  "selected_records": [ {"record_id": "...", "reviewer_id": "...", "...": "..."} ],
  "quota_usage": [
    {"constraint_id": "quota:department:合规部", "dimension": "department",
     "label": "合规部", "count": 5, "lower": 2, "upper": 6, "satisfied": true}
  ],
  "incident_coverage": [
    {"constraint_id": "incident:INC-A", "incident": "INC-A",
     "supporting_records": ["REC003", "REC004"],
     "support_departments": ["对公部", "风控部"],
     "min_records": 2, "distinct_departments": 2, "satisfied": true}
  ],
  "mutex_compliance": [ {"group_id": "MG-1", "selected": [], "satisfied": true} ],
  "reviewer_loads": [ {"reviewer_id": "REV01", "used": 2, "capacity": 3, "satisfied": true} ],
  "hard_constraints_check": {
    "eligibility_and_cross_department": [ {"record_id": "...", "reviewer_id": "...", "qualified": true, "cross_department": true} ],
    "reviewer_loads": [],
    "capacity_satisfied": true,
    "mutex_groups": [],
    "mutex_satisfied": true,
    "all_hard_satisfied": true
  },
  "solver_stats": {
    "nodes_visited": 3773,
    "flow_calls": 24,
    "flow_cache_hits": 1,
    "flow_cache_size": 8,
    "optimality": "exhaustive_branch_and_bound_proven_optimal"
  },
  "optimal": true,
  "approximation": false,
  "run_seq": 1
}
```

`"approximation": false` 与 `optimality` 字段明确声明这是穷举证明的
最优解，绝不是可行近似解。无解时 `status` 为 `"infeasible"`、
`optimal` 为 `false`，并附带 `diagnosis_hint`。

### 4.2 diagnose

```json
{
  "status": "contradiction_found",
  "diagnosable_constraint_ids": ["incident:INC-1", "quota:department:D1"],
  "checks_evaluated": 11,
  "feasibility_cache_entries": 11,
  "enumeration_upper_bound": 64,
  "contradiction": {
    "cardinality": 2,
    "constraint_ids": ["quota:department:D1", "quota:risk:R1"],
    "tie_break_rule": "同基数矛盾集按约束 ID 列表的字典序取最小",
    "infeasibility_witness": {
      "subset": ["quota:department:D1", "quota:risk:R1"],
      "feasible": false,
      "proof": {
        "method": "exhaustive_branch_and_bound",
        "nodes_visited": 5,
        "flow_calls": 0,
        "flow_cache_hits": 0,
        "flow_cache_size": 0,
        "explanation": "分支定界在硬约束与该子集软约束下遍历完整搜索树……"
      }
    },
    "removal_witnesses": [
      {
        "removed_constraint_id": "quota:department:D1",
        "remaining_active_constraints": ["quota:risk:R1"],
        "feasible": true,
        "witness": {
          "selected_record_ids": ["A1", "A4"],
          "assignments": [ {"record_id": "A1", "reviewer_id": "V2"} ],
          "record_count": 2
        },
        "satisfaction": { "soft_constraints": [], "hard_constraints": {} },
        "proof": {"method": "branch_and_bound_first_solution", "nodes_visited": 9}
      }
    ]
  }
}
```

约束 ID 命名：配额为 `quota:<department|risk>:<标签>`，事故为
`incident:<事故 ID>`。资格、容量、互斥始终是硬约束，不参与矛盾集。

### 4.3 结构错误

```json
{
  "status": "error",
  "error": {"code": "E1006", "field": "$.records[0].department",
            "message": "记录 'x' 引用了未声明部门 'GHOST'"}
}
```

| 错误码 | 含义 |
|---|---|
| E1001 | 缺少必填字段 / 标签缺配额 |
| E1002 | 类型不符 |
| E1003 | 取值越界或枚举非法 |
| E1004 | 未声明字段 |
| E1005 | ID 重复 |
| E1006 | 引用不存在 |
| E1007 | 语义结构冲突 |
| E2001 | 文件或 JSON 解析失败（field 含行列号） |
| E3001 | 持久化命令缺少 `--db` |

## 5. 算法、上界与缓存

### 5.1 选择问题：分支定界

记录按 ID 排序后逐条二分支（选/不选，选支优先），完整遍历搜索树，
因此任何返回解都经过穷举证明。剪枝包括：

- 互斥组冲突、配额上界即时回滚；
- 未定记录计数不足以补足配额下界；
- 事故剩余可及部门数不可能达标；
- 最大优先级后缀和不超过当前 incumbent（maxsum）；
- 超过 incumbent 入选数（mincount）。

**理论上界**：选择子问题最多访问 `2^R` 个节点（R = 记录数，题目规模
R <= 28，即 2^28 ≈ 2.68 亿）；实际 28 记录夹具仅访问 3,773 个节点。

### 5.2 指派问题：Dinic 最大流

网络为 `源 -> 记录(容量1) -> 合格跨部门审查员 -> 汇(容量=周容量)`，
含强制指派时使用主/弹性双层审查员节点精确预占容量。最大流等于入选
数当且仅当可指派。指派可行性在叶子节点判定，并有 O(n) 廉价预检查
（资格、总容量、按风险层级的容量必要条件）先行拦截。

### 5.3 字典序决胜

- 入选集合：逐记录尝试强制选择，每次重新求解 mincount 验证仍存在
  同等最优解，等价带回溯的字典序构造；
- 指派：逐记录、逐审查员尝试强制指派，每次用最大流验证前缀可补全，
  最大流担保不会走入贪心死胡同。

### 5.4 诊断：最小基数矛盾集

可诊断约束数 C <= 16。按基数 k=1..C、约束 ID 字典序枚举所有
C(C,k) 个子集，第一个不可行子集即最小基数矛盾集（并列时字典序
最小）。每个子集的可行性结果缓存，**枚举上界 2^C**（C=16 时
65,536），输出中的 `enumeration_upper_bound`、`checks_evaluated`、
`feasibility_cache_entries` 如实给出实际值与上界。矛盾集给出完整
无解证明（穷举统计），并对“逐个去掉一条”的每个子集给出可行见证
及逐条约束满足情况。

## 6. 复现命令

```bash
# 1. 生成夹具（确定性，重复运行字节一致）
python tools/generate_fixtures.py

# 2. 校验
python -m solution validate examples/demo_feasible_28x10.json

# 3. 最优方案（持久化到 SQLite）
python -m solution plan examples/demo_feasible_28x10.json --db runs.sqlite

# 4. 矛盾诊断
python -m solution diagnose examples/demo_infeasible_quota.json --db runs.sqlite

# 5. 历史运行
python -m solution history examples/demo_feasible_28x10.json --db runs.sqlite

# 6. 全部断言测试（50 个）
python -m unittest discover -s tests -v
```

## 7. 目录结构

```
solution/            主包（标准库实现）
  errors.py          结构化错误码
  model.py           规范化数据类
  validate.py        输入校验
  flow.py            Dinic 最大流与字典序指派
  solver.py          分支定界求解器
  diagnose.py        最小基数矛盾集诊断
  storage.py         SQLite 持久化
  __main__.py        CLI 入口
examples/            本地虚构夹具（28x10 可行例、不可行诊断例）
tests/               unittest 断言（helpers.py 为共享构造器）
tools/generate_fixtures.py  确定性夹具生成器
```

## 8. 测试覆盖的关键场景

- 相互重叠的互斥组（含 2^n 暴力最优性对照）；
- 部门、风险单维各自可满足却无法同时满足的跨维度矛盾；
- 只有某个可调度指派才能达成最高分（容量瓶颈进入选择剪枝）；
- 事故共同部门不算独立支撑、一记录关联多事故；
- 两个并列最小矛盾集的 ID 字典序决胜，及移除见证；
- 400 组随机小规模指派的暴力字典序对照；
- 结构错误码与字段定位、确定性、CLI 与 SQLite 持久化、28x10 规模上界。
