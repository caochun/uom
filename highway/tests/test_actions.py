from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from uom.loader import load_domain  # noqa: E402
from uom.workspace import ChangeValidationError  # noqa: E402


class ModelActionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.domain_root = Path(self.temp_dir.name) / "highway"
        shutil.copytree(ROOT / "highway", self.domain_root, ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"))
        runtime = load_domain(self.domain_root / "domains" / "passage_charging")
        self.runtime = runtime
        self.repository = runtime.repository
        self.graph = runtime.change_store
        self.actions = runtime.actions
        self.child_runtimes = []

    def tearDown(self) -> None:
        for runtime in self.child_runtimes:
            runtime.close()
        self.repository.close()
        self.temp_dir.cleanup()

    def child_actions(self, name: str):
        runtime = load_domain(self.domain_root / "domains" / name)
        self.child_runtimes.append(runtime)
        return runtime.actions

    def insert_object(self, record: dict) -> None:
        self.graph.create_object(record)

    def test_global_and_context_actions_follow_model(self) -> None:
        global_ids = {item["id"] for item in self.actions.list_actions()["actions"]}
        self.assertEqual({"register_party", "register_medium"}, global_ids)
        self.insert_object({"id": "party:test", "type": "party", "name": "主体", "properties": {"category": "operator"}})
        party_ids = {item["id"] for item in self.actions.list_actions("party:test")["actions"]}
        self.assertIn("register_vehicle", party_ids)
        self.assertNotIn("record_passage", party_ids)

    def test_action_form_validates_partial_prefill(self) -> None:
        prepared = self.actions.prepare_action("register_party", {"name": "山东发行方"})
        self.assertEqual("register_party", prepared["action"]["id"])
        self.assertEqual({"name": "山东发行方"}, prepared["initial_inputs"])
        with self.assertRaisesRegex(ChangeValidationError, "未定义的输入"):
            self.actions.prepare_action("register_party", {"unknown": "value"})

    def test_register_road_and_section_compile_to_contains(self) -> None:
        actions = self.child_actions("facility_operations")
        road = actions.preview_action("register_toll_road", {"name": "示例高速", "code": "G99"})
        self.assertTrue(road["valid"])
        actions.execute_action(road["preview_token"])
        road_id = road["operations"][0]["record"]["id"]
        section = actions.preview_action("register_section", {"name": "东段", "code": "G99-E"}, road_id)
        self.assertTrue(section["valid"])
        relation = section["operations"][1]["record"]
        self.assertEqual((road_id, section["operations"][0]["record"]["id"]), (relation["from"], relation["to"]))
        self.assertEqual("contains", relation["type"])

    def test_register_rate_rule_compiles_typed_fare_basis(self) -> None:
        preview = self.child_actions("pricing_control").preview_action(
            "register_rate_rule",
            {
                "name": "一类客车基础费率",
                "code": "RULE-001",
                "vehicle_type": "一类客车",
                "unit_rate": 0.4,
                "fee_type": "distance",
                "valid_from": "2026-08-01",
            },
        )
        self.assertTrue(preview["valid"])
        record = preview["operations"][0]["record"]
        self.assertEqual("rate_rule", record["type"])
        self.assertEqual(0.4, record["properties"]["unit_rate"])

    def test_cpc_is_used_by_passage_without_binding(self) -> None:
        self.insert_object({"id": "vehicle:test", "type": "vehicle", "name": "测试车辆", "properties": {"plate_no": "鲁A00001"}})
        self.insert_object({"id": "medium:cpc", "type": "toll_medium", "name": "CPC 卡", "properties": {"medium_kind": "cpc_card", "code": "CPC-001"}})
        preview = self.actions.preview_action("record_passage", {"reference_no": "PASS-001", "mode": "mtc", "medium_id": "medium:cpc"}, "vehicle:test")
        self.assertTrue(preview["valid"])
        relation_types = {(op["record"]["type"], op["record"].get("properties", {}).get("role")) for op in preview["operations"] if op["action"] == "create_relation"}
        self.assertIn(("associates", "passage_vehicle"), relation_types)
        self.assertIn(("references", "used_medium"), relation_types)
        self.assertFalse(any(op["record"]["from"] == "vehicle:test" and op["record"]["to"] == "medium:cpc" for op in preview["operations"] if op["action"] == "create_relation"))
        self.actions.execute_action(preview["preview_token"])
        self.assertEqual(1, len(self.workspace_objects("passage")))

    def workspace_objects(self, object_type: str) -> list[dict]:
        return [item for item in self.runtime.workspace.list_objects() if item.get("type") == object_type]


if __name__ == "__main__":
    unittest.main()
