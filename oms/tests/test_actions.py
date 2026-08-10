from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from oag.ontology.loader import load_domain  # noqa: E402
from oms.actions import OmsActionService  # noqa: E402
from oms.store import ChangeValidationError, OmsWorkspaceService  # noqa: E402


class OmsActionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.oms_root = Path(self.temp_dir.name) / "oms"
        shutil.copytree(
            ROOT / "oms",
            self.oms_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        self.ontology, self.repository, _ = load_domain(self.oms_root)
        self.workspace = OmsWorkspaceService(self.oms_root, self.repository)
        self.actions = OmsActionService(self.workspace)

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def insert_object(self, record: dict) -> None:
        self.repository.insert_record("Object", record)

    def test_global_and_context_actions_are_selected_from_the_model(self) -> None:
        global_ids = {item["id"] for item in self.actions.get_available_actions()["actions"]}
        self.assertEqual(
            {
                "register_party", "register_user", "register_toll_road",
                "publish_fee_module", "add_control_entry",
            },
            global_ids,
        )

        self.insert_object({
            "id": "road:test",
            "type": "toll_road",
            "name": "测试公路",
            "properties": {"code": "G99"},
        })
        context_ids = {
            item["id"]
            for item in self.actions.get_available_actions("road:test")["actions"]
        }
        self.assertIn("register_section", context_ids)
        self.assertNotIn("record_passage", context_ids)

    def test_action_form_accepts_partial_prefill_without_required_inputs(self) -> None:
        prepared = self.actions.prepare_action_form(
            "register_toll_road",
            {"name": "济青高速"},
        )
        self.assertEqual("register_toll_road", prepared["action"]["id"])
        self.assertEqual({"name": "济青高速"}, prepared["initial_inputs"])
        self.assertNotIn("effects", prepared["action"])
        self.assertIsNone(prepared["context"])

    def test_action_form_rejects_unknown_or_invalid_prefill(self) -> None:
        with self.assertRaisesRegex(ChangeValidationError, "未定义的输入"):
            self.actions.prepare_action_form("register_toll_road", {"unknown": "value"})
        with self.assertRaisesRegex(ChangeValidationError, "必须是文本"):
            self.actions.prepare_action_form("register_toll_road", {"code": 99})

    def test_register_road_and_section_compile_to_contains_graph(self) -> None:
        road = self.actions.preview_action(
            "register_toll_road",
            {"name": "示例高速", "code": "G99"},
        )
        self.assertTrue(road["valid"])
        self.assertEqual(1, len(road["operations"]))
        self.actions.apply_action(road["preview_token"])
        road_id = road["operations"][0]["record"]["id"]

        section = self.actions.preview_action(
            "register_section",
            {"name": "东段", "code": "G99-E", "mileage": 42.5},
            road_id,
        )
        self.assertTrue(section["valid"])
        relation = section["operations"][1]["record"]
        self.assertEqual((road_id, section["operations"][0]["record"]["id"]), (relation["from"], relation["to"]))
        self.assertEqual("contains", relation["type"])

    def test_passage_action_creates_transactions_and_station_references(self) -> None:
        self.insert_object({
            "id": "vehicle:test",
            "type": "vehicle",
            "name": "测试车辆",
            "properties": {"plate_no": "川A00001", "vehicle_type": "客车一类"},
        })
        for station_id, name in (("station:entry", "入口"), ("station:exit", "出口")):
            self.insert_object({
                "id": station_id,
                "type": "toll_station",
                "name": name,
                "properties": {"code": station_id},
            })

        preview = self.actions.preview_action(
            "record_passage",
            {
                "reference_no": "PASS-001",
                "entry_station_id": "station:entry",
                "exit_station_id": "station:exit",
                "entry_on": "2026-08-10",
                "exit_on": "2026-08-10",
                "amount": {"amount": 35, "currency": "CNY"},
            },
            "vehicle:test",
        )
        self.assertTrue(preview["valid"])
        self.assertEqual(8, len(preview["operations"]))
        self.assertEqual(
            {"entry", "exit"},
            {
                operation["record"]["properties"]["stage"]
                for operation in preview["operations"]
                if operation["action"] == "create_object"
                and operation["record"]["type"] == "toll_transaction"
            },
        )
        self.actions.apply_action(preview["preview_token"])
        self.assertEqual(
            1,
            len([item for item in self.workspace.list_objects() if item["type"] == "passage"]),
        )


if __name__ == "__main__":
    unittest.main()
