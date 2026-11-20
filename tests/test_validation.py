"""输入结构错误：错误码与字段位置可定位。"""

import unittest

from helpers import make_case, quota, rec, rev
from solution.errors import (
    E_DUPLICATE, E_MISSING, E_PARSE, E_REFERENCE, E_SEMANTIC, E_TYPE,
    E_UNKNOWN, E_VALUE,
)
from solution.validate import validate
from solution.errors import InputError


def base_raw():
    return make_case(
        records=[rec("r1", "D1", "R1"), rec("r2", "D2", "R1")],
        reviewers=[rev("v1", "D2", ["R1"]), rev("v2", "D1", ["R1"])],
        quotas=[
            quota("department", "D1", 0, 2),
            quota("department", "D2", 0, 2),
            quota("risk", "R1", 0, 2),
        ],
    )


class TestValidationErrors(unittest.TestCase):
    def assert_error(self, raw, code):
        with self.assertRaises(InputError) as ctx:
            validate(raw)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def test_missing_field(self):
        raw = base_raw()
        del raw["records"]
        e = self.assert_error(raw, E_MISSING)
        self.assertEqual(e.field, "$.records")

    def test_wrong_type(self):
        raw = base_raw()
        raw["records"] = "not-a-list"
        e = self.assert_error(raw, E_TYPE)
        self.assertEqual(e.field, "$.records")

    def test_value_out_of_range(self):
        raw = base_raw()
        raw["records"][0]["priority"] = 0
        e = self.assert_error(raw, E_VALUE)
        self.assertEqual(e.field, "$.records[0].priority")

    def test_unknown_field(self):
        raw = base_raw()
        raw["bogus"] = 1
        e = self.assert_error(raw, E_UNKNOWN)
        self.assertEqual(e.field, "$.bogus")

    def test_duplicate_id(self):
        raw = base_raw()
        raw["records"][1]["id"] = "r1"
        e = self.assert_error(raw, E_DUPLICATE)
        self.assertIn("records[1]", e.field)

    def test_bad_reference_department(self):
        raw = base_raw()
        raw["records"][0]["department"] = "GHOST"
        e = self.assert_error(raw, E_REFERENCE)
        self.assertEqual(e.field, "$.records[0].department")

    def test_bad_reference_qualification(self):
        raw = base_raw()
        raw["reviewers"][0]["qualifications"] = ["GHOST-RISK"]
        e = self.assert_error(raw, E_REFERENCE)
        self.assertIn("qualifications", e.field)

    def test_lower_greater_than_upper(self):
        raw = base_raw()
        raw["quotas"][0]["lower"] = 5
        e = self.assert_error(raw, E_VALUE)
        self.assertIn("lower", e.field)

    def test_missing_quota_for_label(self):
        raw = base_raw()
        raw["quotas"] = [q for q in raw["quotas"]
                         if not (q["dimension"] == "risk")]
        e = self.assert_error(raw, E_MISSING)
        self.assertEqual(e.field, "$.quotas")

    def test_mutex_too_small_and_bad_ref(self):
        raw = base_raw()
        raw["mutex_groups"] = [{"id": "g1", "records": ["r1"]}]
        e = self.assert_error(raw, E_VALUE)
        self.assertIn("mutex_groups[0]", e.field)

        raw["mutex_groups"] = [{"id": "g1", "records": ["r1", "NOPE"]}]
        e = self.assert_error(raw, E_REFERENCE)

    def test_incident_structurally_impossible(self):
        # 事故只在一个部门的记录中出现，却要求两个不同部门
        raw = make_case(
            records=[
                rec("r1", "D1", "R1", incidents=["I1"]),
                rec("r2", "D1", "R1", incidents=["I1"]),
            ],
            reviewers=[rev("v1", "D2", ["R1"])],
            quotas=[
                quota("department", "D1", 0, 2),
                quota("department", "D2", 0, 2),
                quota("risk", "R1", 0, 2),
            ],
            incidents=[
                {"incident": "I1", "min_records": 2,
                 "distinct_departments": 2},
            ],
            departments=["D1", "D2"],
        )
        e = self.assert_error(raw, E_SEMANTIC)
        self.assertIn("incident_requirements[0]", e.field)

    def test_bool_not_accepted_as_int(self):
        raw = base_raw()
        raw["records"][0]["priority"] = True
        self.assert_error(raw, E_VALUE)

    def test_parse_error_code_exists(self):
        # E_PARSE 由 CLI 层产生，这里仅确认常量稳定
        self.assertEqual(E_PARSE, "E2001")


if __name__ == "__main__":
    unittest.main()
