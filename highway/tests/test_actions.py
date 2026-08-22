from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from uom.actions import ModelActionService  # noqa: E402
from uom.loader import load_domain  # noqa: E402
from uom.workspace import ChangeValidationError, UomWorkspaceService  # noqa: E402


class ModelActionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.domain_root = Path(self.temp_dir.name) / "highway"
        shutil.copytree(
            ROOT / "highway",
            self.domain_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        runtime = load_domain(self.domain_root)
        self.ontology = runtime.ontology
        self.repository = runtime.repository
        self.graph = runtime.change_store
        self.workspace = UomWorkspaceService(self.domain_root, self.graph)
        self.actions = ModelActionService(self.workspace)

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def insert_object(self, record: dict) -> None:
        self.graph.create_object( record)

    def test_global_and_context_actions_are_selected_from_the_model(self) -> None:
        global_ids = {item["id"] for item in self.actions.list_actions()["actions"]}
        self.assertEqual(
            {
                "register_party", "register_user", "register_toll_road",
                "register_cpc_card", "register_paper_ticket",
                "publish_fee_module", "register_operating_parameter",
            },
            global_ids,
        )
        self.assertTrue(all(
            "effects" not in item and "handler" not in item
            for item in self.actions.list_actions()["actions"]
        ))

        self.insert_object({
            "id": "road:test",
            "type": "toll_road",
            "name": "测试公路",
            "properties": {"code": "G99"},
        })
        context_ids = {
            item["id"]
            for item in self.actions.list_actions("road:test")["actions"]
        }
        self.assertIn("register_section", context_ids)
        self.assertNotIn("record_etc_passage", context_ids)

    def test_action_form_accepts_partial_prefill_without_required_inputs(self) -> None:
        prepared = self.actions.prepare_action(
            "register_toll_road",
            {"name": "济青高速"},
        )
        self.assertEqual("register_toll_road", prepared["action"]["id"])
        self.assertEqual({"name": "济青高速"}, prepared["initial_inputs"])
        self.assertNotIn("effects", prepared["action"])
        self.assertIsNone(prepared["context"])

    def test_action_form_rejects_unknown_or_invalid_prefill(self) -> None:
        with self.assertRaisesRegex(ChangeValidationError, "未定义的输入"):
            self.actions.prepare_action("register_toll_road", {"unknown": "value"})
        with self.assertRaisesRegex(ChangeValidationError, "必须是文本"):
            self.actions.prepare_action("register_toll_road", {"code": 99})

    def test_register_road_and_section_compile_to_contains_graph(self) -> None:
        road = self.actions.preview_action(
            "register_toll_road",
            {"name": "示例高速", "code": "G99"},
        )
        self.assertTrue(road["valid"])
        self.assertEqual(1, len(road["operations"]))
        self.actions.execute_action(road["preview_token"])
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

    def test_cpc_passage_records_temporary_issue_use_and_recovery(self) -> None:
        self.insert_object({
            "id": "vehicle:test",
            "type": "vehicle",
            "name": "测试车辆",
            "properties": {"plate_no": "川A00001", "vehicle_type": "客车一类"},
        })
        for lane_id, name, direction in (
            ("lane:entry", "入口车道", "entry"),
            ("lane:exit", "出口车道", "exit"),
        ):
            self.insert_object({
                "id": lane_id,
                "type": "toll_lane",
                "name": name,
                "properties": {
                    "code": lane_id,
                    "category": "mixed",
                    "direction": direction,
                },
            })
        self.insert_object({
            "id": "cpc:test",
            "type": "cpc_card",
            "name": "测试 CPC 卡",
            "properties": {"code": "CPC-001", "status": "available"},
        })

        preview = self.actions.preview_action(
            "record_cpc_passage",
            {
                "reference_no": "PASS-001",
                "entry_transaction_no": "ENTRY-001",
                "exit_transaction_no": "EXIT-001",
                "cpc_card_id": "cpc:test",
                "entry_lane_id": "lane:entry",
                "exit_lane_id": "lane:exit",
                "entry_at": "2026-08-10T08:00:00+08:00",
                "exit_at": "2026-08-10T09:00:00+08:00",
                "receivable_amount": {"amount": 35, "currency": "CNY"},
                "paid_amount": {"amount": 35, "currency": "CNY"},
            },
            "vehicle:test",
        )
        self.assertTrue(preview["valid"])
        self.assertEqual(11, len(preview["operations"]))
        self.assertEqual(
            {"entry", "exit"},
            {
                operation["record"]["properties"]["stage"]
                for operation in preview["operations"]
                if operation["action"] == "create_object"
                and operation["record"]["type"] == "toll_transaction"
            },
        )
        passage = next(
            operation["record"]
            for operation in preview["operations"]
            if operation["action"] == "create_object"
            and operation["record"]["type"] == "passage"
        )
        self.assertEqual("mtc", passage["properties"]["mode"])
        self.assertNotIn("occurred_on", passage["properties"])
        roles = {
            operation["record"].get("properties", {}).get("role")
            for operation in preview["operations"]
            if operation["action"] == "create_relation"
        }
        self.assertTrue(
            {"used_cpc_card", "issued_cpc_card", "recovered_cpc_card"}.issubset(roles)
        )
        cpc_relations = [
            operation["record"]
            for operation in preview["operations"]
            if operation["action"] == "create_relation"
            and operation["record"]["to"] == "cpc:test"
        ]
        self.assertEqual(3, len(cpc_relations))
        self.assertNotIn("vehicle:test", {item["from"] for item in cpc_relations})
        self.actions.execute_action(preview["preview_token"])
        self.assertEqual(
            1,
            len([item for item in self.workspace.list_objects() if item["type"] == "passage"]),
        )

    def test_etc_consumption_uses_passage_medium_and_rejects_user_account(self) -> None:
        for record in (
            {
                "id": "passage:test",
                "type": "passage",
                "name": "测试通行",
                "properties": {
                    "reference_no": "PASS-001",
                    "mode": "etc",
                },
            },
            {
                "id": "account:user",
                "type": "user_account",
                "name": "用户资金账户",
                "properties": {"reference_no": "UA-001"},
            },
        ):
            self.insert_object(record)

        inputs = {
            "reference_no": "CONSUME-001",
            "account_id": "account:user",
            "amount": {"amount": 35, "currency": "CNY"},
            "occurred_on": "2026-08-10",
        }
        with self.assertRaisesRegex(ChangeValidationError, "对象类型必须是 card_account"):
            self.actions.preview_action("record_consumption", inputs, "passage:test")


if __name__ == "__main__":
    unittest.main()
