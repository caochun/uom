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

    def test_obu_card_pairing_and_issuer_are_explicit_relations(self) -> None:
        self.insert_object({"id": "medium:obu", "type": "toll_medium", "name": "测试 OBU", "properties": {"medium_kind": "obu", "code": "OBU-TEST", "status": "active"}})
        self.insert_object({"id": "medium:etc", "type": "toll_medium", "name": "测试 ETC 卡", "properties": {"medium_kind": "etc_card", "code": "ETC-TEST", "status": "active"}})
        self.insert_object({"id": "party:issuer", "type": "party", "name": "测试发行方", "properties": {"category": "issuer", "status": "active"}})

        paired = self.actions.preview_action(
            "pair_toll_media", {"card_id": "medium:etc"}, "medium:obu"
        )
        self.assertTrue(paired["valid"])
        self.assertEqual(
            "paired_card", paired["operations"][0]["record"]["properties"]["role"]
        )
        issuer = self.actions.preview_action(
            "assign_medium_party",
            {"party_id": "party:issuer", "role": "issuer"},
            "medium:etc",
        )
        self.assertTrue(issuer["valid"])
        self.assertEqual(
            ("medium:etc", "party:issuer"),
            (issuer["operations"][0]["record"]["from"], issuer["operations"][0]["record"]["to"]),
        )

    def test_account_fund_flow_and_bill_source_actions_are_role_aware(self) -> None:
        actions = self.child_actions("customer_accounts")
        self.insert_object({"id": "account:source", "type": "account", "name": "来源账户", "properties": {"account_kind": "user_account", "code": "SOURCE", "status": "active"}})
        self.insert_object({"id": "account:target", "type": "account", "name": "卡账户", "properties": {"account_kind": "card_account", "code": "TARGET", "status": "active"}})

        wallet = actions.preview_action(
            "register_wallet",
            {"name": "测试钱包", "wallet_kind": "card_wallet", "code": "WALLET"},
            "account:target",
        )
        self.assertTrue(wallet["valid"])
        actions.execute_action(wallet["preview_token"])
        wallet_id = wallet["operations"][0]["record"]["id"]

        transaction = actions.preview_action(
            "record_fund_transaction",
            {
                "reference_no": "TX-TEST",
                "transaction_kind": "account_transfer",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_at": "2026-09-01T10:00:00+08:00",
                "result": "success",
                "account_role": "source_account",
                "related_account_id": "account:target",
                "related_account_role": "target_account",
                "wallet_id": wallet_id,
                "wallet_role": "target_wallet",
            },
            "account:source",
        )
        self.assertTrue(transaction["valid"])
        roles = {
            item["record"]["properties"]["role"]
            for item in transaction["operations"]
            if item["action"] == "create_relation" and item["record"]["type"] == "associates"
        }
        self.assertEqual({"source_account", "target_account", "target_wallet"}, roles)
        actions.execute_action(transaction["preview_token"])
        transaction_id = transaction["operations"][0]["record"]["id"]

        bill = actions.preview_action(
            "record_bill",
            {
                "reference_no": "BILL-TEST",
                "billing_period": "2026-09",
                "amount": {"amount": 100, "currency": "CNY"},
                "first_transaction_id": transaction_id,
            },
            "account:target",
        )
        self.assertTrue(bill["valid"])
        source_link = next(
            item["record"] for item in bill["operations"]
            if item["action"] == "create_relation" and item["record"]["type"] == "derives"
        )
        self.assertEqual(transaction_id, source_link["from"])

    def test_pricing_path_actions_preserve_node_order(self) -> None:
        actions = self.child_actions("pricing_control")
        self.insert_object({"id": "passage:path", "type": "passage", "name": "路径通行", "properties": {"reference_no": "PASS-PATH", "mode": "etc"}})
        self.insert_object({"id": "station:start", "type": "toll_station", "name": "起点站", "properties": {"code": "START"}})
        self.insert_object({"id": "gantry:next", "type": "toll_gantry", "name": "下一门架", "properties": {"code": "NEXT"}})

        path = actions.preview_action(
            "record_pricing_path",
            {
                "reference_no": "PATH-TEST",
                "path_kind": "charging",
                "occurred_at": "2026-09-01T11:00:00+08:00",
                "result": "matched",
                "node_id": "station:start",
                "sequence": 1,
                "node_mileage": 0,
            },
            "passage:path",
        )
        self.assertTrue(path["valid"])
        first_link = next(
            item["record"] for item in path["operations"]
            if item["action"] == "create_relation" and item["record"]["type"] == "references"
        )
        self.assertEqual(1, first_link["properties"]["sequence"])
        actions.execute_action(path["preview_token"])
        path_id = path["operations"][0]["record"]["id"]

        appended = actions.preview_action(
            "append_pricing_path_node",
            {"node_id": "gantry:next", "sequence": 2, "mileage": 52},
            path_id,
        )
        self.assertTrue(appended["valid"])
        self.assertEqual(2, appended["operations"][0]["record"]["properties"]["sequence"])

    def workspace_objects(self, object_type: str) -> list[dict]:
        return [item for item in self.runtime.workspace.list_objects() if item.get("type") == object_type]


if __name__ == "__main__":
    unittest.main()
