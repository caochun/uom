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
        self.ontology, self.repository, self.registry = load_domain(self.oms_root)
        self.workspace = OmsWorkspaceService(self.oms_root, self.repository)
        self.actions = OmsActionService(self.workspace)

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def insert_object(self, record: dict) -> None:
        self.repository.insert_record("Object", record)

    def test_global_and_context_actions_are_selected_from_the_model(self) -> None:
        global_ids = {item["id"] for item in self.actions.get_available_actions()["actions"]}
        self.assertEqual({"register_party", "register_highway"}, global_ids)

        self.insert_object({
            "id": "highway:test",
            "type": "highway",
            "name": "测试高速",
            "properties": {"code": "G99"},
        })
        context_ids = {
            item["id"]
            for item in self.actions.get_available_actions("highway:test")["actions"]
        }
        self.assertIn("register_road_section", context_ids)
        self.assertIn("attach_evidence", context_ids)
        self.assertNotIn("record_cash_receipt", context_ids)

    def test_action_form_accepts_partial_prefill_without_required_inputs(self) -> None:
        prepared = self.actions.prepare_action_form(
            "register_highway",
            {"name": "济青高速"},
        )
        self.assertEqual("register_highway", prepared["action"]["id"])
        self.assertEqual({"name": "济青高速"}, prepared["initial_inputs"])
        self.assertNotIn("effects", prepared["action"])
        self.assertIsNone(prepared["context"])

    def test_action_form_rejects_unknown_or_invalid_prefill(self) -> None:
        with self.assertRaisesRegex(ChangeValidationError, "未定义的输入"):
            self.actions.prepare_action_form(
                "register_highway",
                {"unknown": "value"},
            )
        with self.assertRaisesRegex(ChangeValidationError, "必须是文本"):
            self.actions.prepare_action_form(
                "register_highway",
                {"code": 99},
            )

    def test_preview_does_not_write_and_apply_is_audited(self) -> None:
        self.insert_object({
            "id": "receivable:test",
            "type": "receivable",
            "name": "测试收费应收",
            "properties": {
                "amount": {"amount": 1000, "currency": "CNY"},
                "occurred_on": "2026-08-01",
            },
        })
        preview = self.actions.preview_action(
            "record_cash_receipt",
            {
                "name": "首笔收费到账",
                "amount": {"amount": 600, "currency": "CNY"},
                "occurred_on": "2026-08-05",
            },
            "receivable:test",
        )
        self.assertTrue(preview["valid"])
        self.assertEqual(1, len(self.workspace.list_objects()))
        self.assertEqual(0, len(self.workspace.list_relations()))

        result = self.actions.apply_action(
            preview["preview_token"],
            reason="银行到账",
            actor="tester",
            channel="test",
        )
        self.assertTrue(result["applied"])
        self.assertEqual(
            1,
            len([item for item in self.workspace.list_objects() if item["type"] == "cash_receipt"]),
        )
        allocation = self.workspace.list_relations()[0]
        self.assertEqual("receivable:test", allocation["to"])

        log = self.repository.adapter_for("Object").list_action_log()
        self.assertEqual("record_cash_receipt", log[0]["action_id"])
        self.assertEqual("tester", log[0]["actor"])
        self.assertEqual("银行到账", log[0]["payload"]["reason"])

    def test_register_highway_creates_operator_relationship(self) -> None:
        self.insert_object({
            "id": "party:operator",
            "type": "party",
            "name": "示例高速运营公司",
            "properties": {"roles": ["operator"]},
        })
        preview = self.actions.preview_action(
            "register_highway",
            {
                "name": "示例高速",
                "code": "G99",
                "operator_id": "party:operator",
            },
        )
        self.assertTrue(preview["valid"])
        self.assertEqual(2, len(preview["operations"]))
        highway_id = preview["operations"][0]["record"]["id"]
        relation = preview["operations"][1]["record"]
        self.assertEqual("highway", preview["operations"][0]["record"]["type"])
        self.assertEqual((highway_id, "party:operator"), (relation["from"], relation["to"]))
        self.assertEqual("operator", relation["properties"]["role"])

    def test_highway_operations_compile_to_the_operating_graph(self) -> None:
        self.insert_object({
            "id": "party:operator",
            "type": "party",
            "name": "示例高速运营公司",
            "properties": {"roles": ["operator"]},
        })
        highway = self.actions.preview_action(
            "register_highway",
            {"name": "示例高速", "code": "G99", "operator_id": "party:operator"},
        )
        self.actions.apply_action(highway["preview_token"])
        highway_id = highway["operations"][0]["record"]["id"]

        section = self.actions.preview_action(
            "register_road_section",
            {"name": "东段", "code": "G99-E", "mileage": 42.5},
            highway_id,
        )
        self.actions.apply_action(section["preview_token"])
        section_id = section["operations"][0]["record"]["id"]

        self.insert_object({
            "id": "toll_station:exit",
            "type": "toll_station",
            "name": "西出口",
            "properties": {"code": "G99-EXIT"},
        })
        station = self.actions.preview_action(
            "register_toll_station",
            {"name": "东入口", "code": "G99-ENTRY"},
            section_id,
        )
        self.actions.apply_action(station["preview_token"])
        station_id = station["operations"][0]["record"]["id"]

        passage = self.actions.preview_action(
            "record_vehicle_passage",
            {
                "reference_no": "PASS-001",
                "vehicle_type": "客车一类",
                "exit_station_id": "toll_station:exit",
                "occurred_on": "2026-08-10",
            },
            station_id,
        )
        self.assertTrue(passage["valid"])
        self.assertEqual(
            {"entry_station", "exit_station"},
            {item["record"]["properties"]["role"] for item in passage["operations"][1:]},
        )
        self.actions.apply_action(passage["preview_token"])
        passage_id = passage["operations"][0]["record"]["id"]

        transaction = self.actions.preview_action(
            "record_toll_transaction",
            {
                "reference_no": "TX-001",
                "amount": {"amount": 35, "currency": "CNY"},
                "occurred_on": "2026-08-10",
            },
            passage_id,
        )
        self.assertTrue(transaction["valid"])
        self.assertEqual("passage_rating", transaction["operations"][1]["record"]["properties"]["basis"])
        self.actions.apply_action(transaction["preview_token"])
        transaction_id = transaction["operations"][0]["record"]["id"]

        revenue = self.actions.preview_action(
            "recognize_toll_revenue",
            {
                "name": "8月通行费收入",
                "amount": {"amount": 35, "currency": "CNY"},
                "occurred_on": "2026-08-10",
                "period": "2026-08",
            },
            transaction_id,
        )
        self.assertTrue(revenue["valid"])
        self.assertEqual("toll", revenue["operations"][0]["record"]["properties"]["category"])

    def test_maintenance_cost_and_revenue_allocation(self) -> None:
        self.insert_object({
            "id": "section:test",
            "type": "road_section",
            "name": "测试路段",
            "properties": {"code": "G99-T"},
        })
        work = self.actions.preview_action(
            "record_maintenance_work",
            {
                "name": "路面维修",
                "category": "pavement",
                "occurred_on": "2026-08-03",
            },
            "section:test",
        )
        self.assertTrue(work["valid"])
        self.actions.apply_action(work["preview_token"])
        work_id = work["operations"][0]["record"]["id"]

        cost = self.actions.preview_action(
            "record_highway_cost",
            {
                "name": "路面维修成本",
                "amount": {"amount": 300, "currency": "CNY"},
                "occurred_on": "2026-08-04",
            },
            work_id,
        )
        self.assertTrue(cost["valid"])
        self.actions.apply_action(cost["preview_token"])
        cost_id = cost["operations"][0]["record"]["id"]

        self.insert_object({
            "id": "revenue:test",
            "type": "revenue",
            "name": "测试通行费收入",
            "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
        })
        allocation = self.actions.preview_action(
            "allocate_cost",
            {
                "revenue_id": "revenue:test",
                "amount": {"amount": 300, "currency": "CNY"},
                "occurred_on": "2026-08-05",
            },
            cost_id,
        )
        self.assertTrue(allocation["valid"])
        self.assertEqual((cost_id, "revenue:test"), (
            allocation["operations"][0]["record"]["from"],
            allocation["operations"][0]["record"]["to"],
        ))

    def test_receivable_and_payable_keep_counterparties(self) -> None:
        self.insert_object({
            "id": "party:counterparty",
            "type": "party",
            "name": "清分合作方",
            "properties": {"roles": ["payer", "supplier"]},
        })
        self.insert_object({
            "id": "revenue:test",
            "type": "revenue",
            "name": "测试通行费收入",
            "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
        })
        self.insert_object({
            "id": "cost:test",
            "type": "cost",
            "name": "测试养护成本",
            "properties": {"amount": {"amount": 400, "currency": "CNY"}},
        })
        cases = (
            ("record_receivable", "revenue:test", "debtor_id", "debtor"),
            ("record_payable", "cost:test", "creditor_id", "creditor"),
        )
        for action_id, context_id, party_input, role in cases:
            preview = self.actions.preview_action(
                action_id,
                {
                    "name": action_id,
                    party_input: "party:counterparty",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-10",
                },
                context_id,
            )
            self.assertTrue(preview["valid"])
            relations = [item["record"] for item in preview["operations"]]
            self.assertTrue(any(
                item["type"] == "involves"
                and item["to"] == "party:counterparty"
                and item["properties"]["role"] == role
                for item in relations
            ))

    def test_invalid_context_and_object_reference_are_rejected(self) -> None:
        self.insert_object({
            "id": "cost:test",
            "type": "cost",
            "name": "测试成本",
            "properties": {"amount": {"amount": 100, "currency": "CNY"}},
        })
        with self.assertRaisesRegex(ChangeValidationError, "不适用于"):
            self.actions.preview_action(
                "record_cash_receipt",
                {
                    "name": "错误收款",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-10",
                },
                "cost:test",
            )
        with self.assertRaisesRegex(ChangeValidationError, "未找到对象"):
            self.actions.preview_action(
                "allocate_cost",
                {
                    "revenue_id": "revenue:missing",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-10",
                },
                "cost:test",
            )


if __name__ == "__main__":
    unittest.main()
