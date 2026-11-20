"""CLI 端到端：四个命令、退出码、UTF-8 JSON 输出与 SQLite 持久化。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import EXAMPLES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEASIBLE = os.path.join(EXAMPLES, "demo_feasible_28x10.json")
INFEASIBLE = os.path.join(EXAMPLES, "demo_infeasible_quota.json")


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run(
            [sys.executable, "-m", "solution", *args],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_validate_command(self):
        code, out, err = self.run_cli("validate", FEASIBLE)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["status"], "valid")
        self.assertEqual(data["counts"]["records"], 28)
        self.assertEqual(data["counts"]["reviewers"], 10)
        self.assertEqual(data["counts"]["diagnosable_constraints"], 16)

    def test_plan_requires_db(self):
        code, out, _ = self.run_cli("plan", FEASIBLE)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "E3001")

    def test_plan_and_history_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "runs.sqlite")
            code, out, err = self.run_cli("plan", FEASIBLE, "--db", db)
            self.assertEqual(code, 0, err)
            plan = json.loads(out)
            self.assertEqual(plan["status"], "optimal")
            self.assertTrue(plan["optimal"])
            self.assertFalse(plan["approximation"])
            # 全部配额与事故满足
            self.assertTrue(all(q["satisfied"] for q in plan["quota_usage"]))
            self.assertTrue(
                all(i["satisfied"] for i in plan["incident_coverage"]))
            self.assertTrue(
                all(m["satisfied"] for m in plan["mutex_compliance"]))
            self.assertTrue(
                all(v["satisfied"] for v in plan["reviewer_loads"]))

            code, out, err = self.run_cli(
                "history", FEASIBLE, "--db", db)
            self.assertEqual(code, 0, err)
            runs = json.loads(out)["runs"]
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["command"], "plan")
            self.assertEqual(runs[0]["status"], "optimal")

    def test_diagnose_command_and_witnesses(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "d.sqlite")
            code, out, err = self.run_cli(
                "diagnose", INFEASIBLE, "--db", db)
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["status"], "contradiction_found")
            c = data["contradiction"]
            self.assertEqual(c["cardinality"], 2)
            self.assertEqual(
                c["constraint_ids"],
                ["quota:department:D1", "quota:risk:R1"],
            )
            for w in c["removal_witnesses"]:
                self.assertTrue(w["feasible"])
                self.assertTrue(w["witness"]["assignments"])

    def test_plan_on_infeasible_reports_not_optimal(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "x.sqlite")
            code, out, err = self.run_cli(
                "plan", INFEASIBLE, "--db", db)
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["status"], "infeasible")
            self.assertFalse(data["optimal"])
            self.assertIn("diagnosis_hint", data)

    def test_malformed_json_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            bad = os.path.join(td, "broken.json")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("{not json")
            code, out, _ = self.run_cli("validate", bad)
            self.assertEqual(code, 2)
            err = json.loads(out)["error"]
            self.assertEqual(err["code"], "E2001")
            self.assertIn("line", err["field"])

    def test_output_is_utf8_and_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "a.sqlite")
            outs = set()
            for _ in range(2):
                _, out, _ = self.run_cli("plan", FEASIBLE, "--db", db)
                # 中文内容正确解码即证明 UTF-8
                self.assertIn("合规部", out)
                payload = json.loads(out)
                payload.pop("run_seq", None)  # 自增序号不参与确定性
                outs.add(json.dumps(payload, ensure_ascii=False,
                                    sort_keys=True))
            self.assertEqual(len(outs), 1)


if __name__ == "__main__":
    unittest.main()
