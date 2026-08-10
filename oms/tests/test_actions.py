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
        global_ids = {
            item["id"] for item in self.actions.get_available_actions()["actions"]
        }
        self.assertIn("register_party", global_ids)
        self.assertNotIn("record_cash_receipt", global_ids)

        self.insert_object({
            "id": "receivable:test",
            "type": "receivable",
            "name": "测试应收",
            "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
        })
        context_ids = {
            item["id"]
            for item in self.actions.get_available_actions("receivable:test")["actions"]
        }
        self.assertTrue({"register_party", "record_cash_receipt", "attach_evidence"}.issubset(context_ids))

    def test_action_form_accepts_partial_prefill_without_required_inputs(self) -> None:
        prepared = self.actions.prepare_action_form(
            "record_contract",
            {"name": "华星科技年度服务合同"},
        )

        self.assertEqual("record_contract", prepared["action"]["id"])
        self.assertEqual(
            {"name": "华星科技年度服务合同"},
            prepared["initial_inputs"],
        )
        self.assertNotIn("effects", prepared["action"])
        self.assertIsNone(prepared["context"])

    def test_action_form_rejects_unknown_or_invalid_prefill(self) -> None:
        with self.assertRaisesRegex(ChangeValidationError, "未定义的输入"):
            self.actions.prepare_action_form(
                "record_contract",
                {"unknown": "value"},
            )
        with self.assertRaisesRegex(ChangeValidationError, "必须是数字"):
            self.actions.prepare_action_form(
                "record_contract",
                {"amount": {"amount": "120000", "currency": "CNY"}},
            )

    def test_preview_does_not_write_and_apply_is_audited(self) -> None:
        self.insert_object({
            "id": "receivable:test",
            "type": "receivable",
            "name": "测试应收",
            "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
        })
        inputs = {
            "name": "首笔回款",
            "amount": {"amount": 600, "currency": "CNY"},
            "occurred_on": "2026-08-10",
        }
        preview = self.actions.preview_action(
            "record_cash_receipt",
            inputs,
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
        receipts = [item for item in self.workspace.list_objects() if item["type"] == "cash_receipt"]
        allocations = [item for item in self.workspace.list_relations() if item["type"] == "allocated_to"]
        self.assertEqual(1, len(receipts))
        self.assertEqual("receivable:test", allocations[0]["to"])

        log = self.repository.adapter_for("Object").list_action_log()
        self.assertEqual("record_cash_receipt", log[0]["action_id"])
        self.assertEqual("tester", log[0]["actor"])
        self.assertEqual("银行到账", log[0]["payload"]["reason"])
        self.assertEqual(2, len(log[0]["payload"]["changes"]))

    def test_record_contract_creates_the_customer_relationship(self) -> None:
        self.insert_object({
            "id": "party:customer",
            "type": "party",
            "name": "测试客户",
            "properties": {"roles": ["customer"]},
        })
        preview = self.actions.preview_action(
            "record_contract",
            {
                "name": "测试客户年度合同",
                "customer_id": "party:customer",
                "amount": {"amount": 120000, "currency": "CNY"},
            },
        )
        self.assertTrue(preview["valid"])
        self.assertEqual(2, len(preview["operations"]))

        contract_id = preview["operations"][0]["record"]["id"]
        relation = preview["operations"][1]["record"]
        self.assertEqual("involves", relation["type"])
        self.assertEqual((contract_id, "party:customer"), (relation["from"], relation["to"]))
        self.assertEqual("customer", relation["properties"]["role"])

        self.actions.apply_action(preview["preview_token"])
        self.assertEqual("contract", self.repository.query_by_id("Object", contract_id)["type"])
        self.assertEqual("party:customer", self.workspace.list_relations()[0]["to"])

    def test_opportunity_conversion_records_customer_and_source(self) -> None:
        self.insert_object({
            "id": "party:customer",
            "type": "party",
            "name": "测试客户",
            "properties": {"roles": ["customer"]},
        })
        self.insert_object({
            "id": "opportunity:test",
            "type": "opportunity",
            "name": "测试商机",
        })
        available = {
            item["id"]
            for item in self.actions.get_available_actions("opportunity:test")["actions"]
        }
        self.assertIn("record_contract_from_opportunity", available)

        preview = self.actions.preview_action(
            "record_contract_from_opportunity",
            {
                "name": "测试商机成交合同",
                "customer_id": "party:customer",
            },
            "opportunity:test",
        )
        self.assertTrue(preview["valid"])
        self.assertEqual(3, len(preview["operations"]))
        contract_id = preview["operations"][0]["record"]["id"]
        relations = [item["record"] for item in preview["operations"][1:]]
        self.assertTrue(any(
            item["type"] == "involves"
            and (item["from"], item["to"]) == (contract_id, "party:customer")
            for item in relations
        ))
        self.assertTrue(any(
            item["type"] == "derived_from"
            and (item["from"], item["to"]) == (contract_id, "opportunity:test")
            for item in relations
        ))

    def test_commercial_commitments_record_their_counterparties(self) -> None:
        self.insert_object({
            "id": "party:counterparty",
            "type": "party",
            "name": "测试往来方",
            "properties": {"roles": ["customer", "supplier"]},
        })
        opportunity = self.actions.preview_action(
            "register_opportunity",
            {"name": "测试商机", "customer_id": "party:counterparty"},
        )
        purchase_order = self.actions.preview_action(
            "record_purchase_order",
            {"name": "测试采购单", "supplier_id": "party:counterparty"},
        )
        for preview, role in ((opportunity, "customer"), (purchase_order, "supplier")):
            self.assertTrue(preview["valid"])
            relation = preview["operations"][1]["record"]
            self.assertEqual("involves", relation["type"])
            self.assertEqual("party:counterparty", relation["to"])
            self.assertEqual(role, relation["properties"]["role"])

    def test_receivable_and_payable_record_their_counterparties(self) -> None:
        self.insert_object({
            "id": "party:counterparty",
            "type": "party",
            "name": "测试往来方",
            "properties": {"roles": ["customer", "supplier"]},
        })
        self.insert_object({
            "id": "revenue:test",
            "type": "revenue",
            "name": "测试收入",
            "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
        })
        self.insert_object({
            "id": "cost:test",
            "type": "cost",
            "name": "测试成本",
            "properties": {"amount": {"amount": 400, "currency": "CNY"}},
        })
        cases = (
            (
                "record_receivable",
                "revenue:test",
                "debtor_id",
                "debtor",
                "测试应收",
            ),
            (
                "record_payable",
                "cost:test",
                "creditor_id",
                "creditor",
                "测试应付",
            ),
        )
        for action_id, context_id, party_input, role, name in cases:
            preview = self.actions.preview_action(
                action_id,
                {
                    "name": name,
                    party_input: "party:counterparty",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-10",
                },
                context_id,
            )
            self.assertTrue(preview["valid"])
            relations = [item["record"] for item in preview["operations"] if item["action"] == "create_relation"]
            self.assertTrue(any(
                item["type"] == "involves"
                and item["to"] == "party:counterparty"
                and item["properties"]["role"] == role
                for item in relations
            ))

    def test_invoice_actions_are_split_by_business_direction(self) -> None:
        self.insert_object({
            "id": "party:counterparty",
            "type": "party",
            "name": "测试往来方",
            "properties": {"roles": ["customer", "supplier"]},
        })
        self.insert_object({
            "id": "revenue:test",
            "type": "revenue",
            "name": "测试收入",
            "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
        })
        self.insert_object({
            "id": "cost:test",
            "type": "cost",
            "name": "测试成本",
            "properties": {"amount": {"amount": 400, "currency": "CNY"}},
        })
        revenue_actions = {
            item["id"]
            for item in self.actions.get_available_actions("revenue:test")["actions"]
        }
        cost_actions = {
            item["id"]
            for item in self.actions.get_available_actions("cost:test")["actions"]
        }
        self.assertIn("record_sales_invoice", revenue_actions)
        self.assertNotIn("record_purchase_invoice", revenue_actions)
        self.assertIn("record_purchase_invoice", cost_actions)
        self.assertNotIn("record_sales_invoice", cost_actions)

        common = {
            "name": "测试发票",
            "reference_no": "INV-001",
            "amount": {"amount": 100, "currency": "CNY"},
            "occurred_on": "2026-08-10",
        }
        sales = self.actions.preview_action(
            "record_sales_invoice",
            {**common, "customer_id": "party:counterparty"},
            "revenue:test",
        )
        purchase = self.actions.preview_action(
            "record_purchase_invoice",
            {**common, "supplier_id": "party:counterparty"},
            "cost:test",
        )
        self.assertTrue(sales["valid"])
        self.assertTrue(purchase["valid"])
        self.assertEqual("sales", sales["operations"][0]["record"]["properties"]["category"])
        self.assertEqual("purchase", purchase["operations"][0]["record"]["properties"]["category"])

    def test_project_and_revenue_contexts_preserve_business_direction(self) -> None:
        self.insert_object({
            "id": "opportunity:test",
            "type": "opportunity",
            "name": "测试商机",
        })
        self.insert_object({
            "id": "delivery:purchase",
            "type": "delivery",
            "name": "采购交付",
        })
        opportunity_actions = {
            item["id"]
            for item in self.actions.get_available_actions("opportunity:test")["actions"]
        }
        delivery_actions = {
            item["id"]
            for item in self.actions.get_available_actions("delivery:purchase")["actions"]
        }
        self.assertIn("start_project_from_context", opportunity_actions)
        self.assertNotIn("recognize_revenue", delivery_actions)

        preview = self.actions.preview_action(
            "start_project_from_context",
            {"name": "商机交付项目"},
            "opportunity:test",
        )
        self.assertTrue(preview["valid"])
        relation = preview["operations"][1]["record"]
        self.assertEqual("derived_from", relation["type"])
        self.assertEqual("opportunity:test", relation["to"])

    def test_settlement_records_the_customer(self) -> None:
        self.insert_object({
            "id": "party:customer",
            "type": "party",
            "name": "测试客户",
            "properties": {"roles": ["customer"]},
        })
        self.insert_object({
            "id": "contract:test",
            "type": "contract",
            "name": "测试合同",
        })
        preview = self.actions.preview_action(
            "record_settlement",
            {
                "name": "八月结算",
                "customer_id": "party:customer",
                "amount": {"amount": 800, "currency": "CNY"},
                "period": "2026-08",
            },
            "contract:test",
        )
        self.assertTrue(preview["valid"])
        relations = [item["record"] for item in preview["operations"][1:]]
        self.assertTrue(any(
            item["type"] == "involves"
            and item["to"] == "party:customer"
            and item["properties"]["role"] == "customer"
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
                    "name": "错误回款",
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

    def test_cost_allocation_compiles_to_a_relation(self) -> None:
        self.insert_object({
            "id": "cost:test",
            "type": "cost",
            "name": "测试成本",
            "properties": {"amount": {"amount": 400, "currency": "CNY"}},
        })
        self.insert_object({
            "id": "revenue:test",
            "type": "revenue",
            "name": "测试收入",
            "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
        })
        preview = self.actions.preview_action(
            "allocate_cost",
            {
                "revenue_id": "revenue:test",
                "amount": {"amount": 300, "currency": "CNY"},
                "occurred_on": "2026-08-10",
            },
            "cost:test",
        )
        record = preview["operations"][0]["record"]
        self.assertTrue(preview["valid"])
        self.assertEqual(("cost:test", "revenue:test"), (record["from"], record["to"]))
        self.assertEqual("confirmed", record["properties"]["status"])


if __name__ == "__main__":
    unittest.main()
