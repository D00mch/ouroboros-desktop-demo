from __future__ import annotations

import csv
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from ouroboros.tool_policy import initial_tool_schemas
from ouroboros.tools.registry import ToolContext, ToolRegistry

REPO = pathlib.Path(__file__).resolve().parents[1]


def _rows() -> list[dict[str, str]]:
    return [
        {
            "employee_id": "EMP-00001",
            "tab_number": "10001",
            "profile_last_name": "Иванов",
            "profile_first_name": "Иван",
            "profile_patronymic": "Петрович",
            "hr_position": "Ведущий инженер",
            "profile_structure": '["Platform", "Backend"]',
            "manager": "Петров Петр Петрович",
            "email": "ivanov@example.com",
        },
        {
            "employee_id": "EMP-00002",
            "tab_number": "10002",
            "profile_last_name": "Смирнова",
            "profile_first_name": "Анна",
            "profile_patronymic": "Андреевна",
            "hr_position": "Главный менеджер",
            "profile_structure": '{"department": "Sales"}',
            "manager": "Кузнецов Иван Сергеевич",
            "email": "anna.smirnova@example.com",
        },
        {
            "employee_id": "EMP-00003",
            "tab_number": "10003",
            "profile_last_name": "Смирнова",
            "profile_first_name": "Екатерина",
            "profile_patronymic": "Николаевна",
            "hr_position": "Старший разработчик",
            "profile_structure": '{"department": "Engineering"}',
            "manager": "Иванов Иван Петрович",
            "email": "ekaterina.smirnova@example.com",
        },
    ]


def _write_csv(path: pathlib.Path) -> pathlib.Path:
    rows = _rows()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    data_dir = tmp_path / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return ToolContext(repo_dir=tmp_path, drive_root=data_dir)


class TestEmployeeLookupBehavior(unittest.TestCase):
    def test_employee_lookup_found_by_last_and_first_name_using_env_override(self):
        from ouroboros.tools.employee_directory import _employee_lookup

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            csv_path = _write_csv(tmp_path / "employees.csv")
            with patch.dict("os.environ", {"OUROBOROS_EMPLOYEE_CSV": str(csv_path)}, clear=False):
                payload = json.loads(_employee_lookup(_ctx(tmp_path), query="  Иванов,   ИВАН "))

        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["query"], "  Иванов,   ИВАН ")
        self.assertEqual(payload["source"], str(csv_path))
        self.assertEqual(payload["employee"]["display_name"], "Иванов Иван Петрович")
        self.assertEqual(payload["employee"]["fields"]["employee_id"], "EMP-00001")
        self.assertEqual(payload["employee"]["fields"]["profile_structure"], ["Platform", "Backend"])

    def test_employee_lookup_found_by_employee_id(self):
        from ouroboros.tools.employee_directory import _employee_lookup

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            csv_path = _write_csv(tmp_path / "employees.csv")
            with patch.dict("os.environ", {"OUROBOROS_EMPLOYEE_CSV": str(csv_path)}, clear=False):
                payload = json.loads(_employee_lookup(_ctx(tmp_path), query="EMP-00002"))

        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["employee"]["display_name"], "Смирнова Анна Андреевна")
        self.assertEqual(payload["employee"]["fields"]["tab_number"], "10002")

    def test_employee_lookup_found_by_tab_number(self):
        from ouroboros.tools.employee_directory import _employee_lookup

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            csv_path = _write_csv(tmp_path / "employees.csv")
            with patch.dict("os.environ", {"OUROBOROS_EMPLOYEE_CSV": str(csv_path)}, clear=False):
                payload = json.loads(_employee_lookup(_ctx(tmp_path), query="10003"))

        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["employee"]["display_name"], "Смирнова Екатерина Николаевна")
        self.assertEqual(payload["employee"]["fields"]["employee_id"], "EMP-00003")

    def test_employee_lookup_shared_last_name_returns_ambiguous(self):
        from ouroboros.tools.employee_directory import _employee_lookup

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            csv_path = _write_csv(tmp_path / "employees.csv")
            with patch.dict("os.environ", {"OUROBOROS_EMPLOYEE_CSV": str(csv_path)}, clear=False):
                payload = json.loads(_employee_lookup(_ctx(tmp_path), query="Смирнова"))

        self.assertEqual(payload["status"], "ambiguous")
        self.assertIn("do not choose automatically", payload["message"].lower())
        self.assertEqual(len(payload["candidates"]), 2)
        for candidate in payload["candidates"]:
            self.assertTrue(candidate["ref"].startswith("row:"))
            self.assertTrue(candidate["display_name"])
            self.assertTrue(candidate["fields"]["employee_id"].startswith("EMP-"))
            self.assertTrue(candidate["fields"]["tab_number"].startswith("100"))
            self.assertLess(len(candidate["fields"]), len(_rows()[0]))

    def test_employee_lookup_ref_returns_full_card(self):
        from ouroboros.tools.employee_directory import _employee_lookup

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            csv_path = _write_csv(tmp_path / "employees.csv")
            with patch.dict("os.environ", {"OUROBOROS_EMPLOYEE_CSV": str(csv_path)}, clear=False):
                ambiguous = json.loads(_employee_lookup(_ctx(tmp_path), query="Смирнова"))
                ref = ambiguous["candidates"][0]["ref"]
                payload = json.loads(_employee_lookup(_ctx(tmp_path), ref=ref))

        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["employee"]["ref"], ref)
        self.assertTrue(payload["employee"]["fields"]["profile_patronymic"])
        self.assertEqual(len(payload["employee"]["fields"]), len(_rows()[0]))

    def test_employee_lookup_missing_csv_returns_error_json(self):
        from ouroboros.tools.employee_directory import _employee_lookup

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            with patch.dict("os.environ", {}, clear=True):
                payload = json.loads(_employee_lookup(_ctx(tmp_path), query="Иванов"))

        self.assertEqual(payload["status"], "error")
        self.assertIn("employees.csv", payload["message"])
        self.assertIn("Data", payload["message"])


class TestEmployeeLookupRegistration(unittest.TestCase):
    def test_employee_lookup_is_registered_core_parallel_safe_and_untruncated(self):
        from ouroboros.safety import TOOL_POLICY, POLICY_SKIP
        from ouroboros.tool_capabilities import (
            CORE_TOOL_NAMES,
            READ_ONLY_PARALLEL_TOOLS,
            TOOL_RESULT_LIMITS,
        )
        from ouroboros.tools import registry as registry_mod

        tmp = pathlib.Path(tempfile.mkdtemp())
        registry = ToolRegistry(repo_dir=tmp, drive_root=tmp)

        self.assertIn("employee_directory", ToolRegistry._FROZEN_TOOL_MODULES)
        self.assertIn("employee_lookup", registry_mod.CORE_TOOL_NAMES)
        self.assertIn("employee_lookup", CORE_TOOL_NAMES)
        self.assertIn("employee_lookup", READ_ONLY_PARALLEL_TOOLS)
        self.assertGreaterEqual(TOOL_RESULT_LIMITS["employee_lookup"], 80_000)
        self.assertEqual(TOOL_POLICY["employee_lookup"], POLICY_SKIP)
        self.assertIn("employee_lookup", {schema["function"]["name"] for schema in registry.schemas()})
        self.assertIn(
            "employee_lookup",
            {schema["function"]["name"] for schema in registry.schemas(core_only=True)},
        )
        self.assertIn(
            "employee_lookup",
            {schema["function"]["name"] for schema in initial_tool_schemas(registry)},
        )

    def test_system_prompt_instructs_employee_lookup_flow(self):
        system_md = (REPO / "prompts" / "SYSTEM.md").read_text(encoding="utf-8")

        self.assertIn("employee_lookup", system_md)
        self.assertIn("If the user asks about an employee", system_md)
        self.assertIn('If `employee_lookup` returns `status: "ambiguous"`', system_md)
        self.assertIn("Do not choose automatically", system_md)
