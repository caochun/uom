from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from oag.ontology.loader import load_domain  # noqa: E402


class LeasingOagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.domain_root = Path(self.temp_dir.name) / "leasing"
        shutil.copytree(
            ROOT / "leasing",
            self.domain_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        self.ontology, self.repository, self.registry = load_domain(self.domain_root)

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def test_provider_loads_effective_leasing_ontology(self) -> None:
        self.assertEqual("UOM 融资租赁领域模型", self.ontology.name)
        self.assertIn("get_contract_trace", self.ontology.functions)
        self.assertIn("audit_finance_consistency", self.ontology.functions)
        self.assertEqual(
            "LeasingActionService",
            type(self.registry.get_resolver("uom_actions")).__name__,
        )

    def test_customer_action_writes_through_uom_repository(self) -> None:
        preview = self.registry.call(
            "preview_action",
            action_id="register_customer",
            inputs={
                "name": "测试承租人",
                "reference_no": "TEST-CUSTOMER-001",
            },
        )
        self.assertTrue(preview["valid"], preview["errors"])
        applied = self.registry.call(
            "apply_action",
            preview_token=preview["preview_token"],
            reason="领域集成测试",
        )
        self.assertTrue(applied["applied"])
        self.assertEqual("测试承租人", self.repository.query("Object")[0]["name"])

    def test_payment_allocation_action_preserves_intermediate_fact(self) -> None:
        for record in (
            {
                "id": "payment:test",
                "type": "payment",
                "name": "测试到账",
                "properties": {
                    "reference_no": "PAY-TEST",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-13",
                    "category": "rent",
                    "status": "unallocated",
                },
            },
            {
                "id": "receivable:test",
                "type": "receivable",
                "name": "测试应收",
                "properties": {
                    "sequence": 1,
                    "category": "rent",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "due_on": "2026-08-13",
                    "status": "open",
                },
            },
        ):
            self.repository.insert_record("Object", record)
        preview = self.registry.call(
            "preview_action",
            action_id="allocate_payment",
            context_id="payment:test",
            inputs={
                "receivable_id": "receivable:test",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-13",
                "sequence": 1,
            },
        )
        self.assertTrue(preview["valid"], preview["errors"])
        object_operations = [
            item for item in preview["operations"]
            if item["action"] == "create_object"
        ]
        relation_operations = [
            item for item in preview["operations"]
            if item["action"] == "create_relation"
        ]
        self.assertEqual("allocation", object_operations[0]["record"]["type"])
        self.assertEqual(2, len(relation_operations))

    def test_voucher_action_generates_balanced_entries(self) -> None:
        self.repository.insert_record("Object", {
            "id": "contract:test",
            "type": "contract",
            "name": "测试合同",
            "properties": {
                "reference_no": "CONTRACT-TEST",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-13",
                "status": "active",
            },
        })
        preview = self.registry.call(
            "preview_action",
            action_id="issue_voucher",
            context_id="contract:test",
            inputs={
                "reference_no": "VOUCHER-TEST",
                "occurred_on": "2026-08-13",
                "period": "2026-08",
                "amount": {"amount": 100, "currency": "CNY"},
                "debit_account": "银行存款",
                "credit_account": "应收融资租赁款",
            },
        )
        self.assertTrue(preview["valid"], preview["errors"])
        records = [
            item["record"] for item in preview["operations"]
            if item["action"] == "create_object"
        ]
        lines = [item for item in records if item["type"] == "voucher_line"]
        self.assertEqual(["debit", "credit"], [item["properties"]["category"] for item in lines])
        self.assertEqual(lines[0]["properties"]["amount"], lines[1]["properties"]["amount"])

    def test_action_preview_blocks_over_allocation(self) -> None:
        for record in (
            {
                "id": "payment:limit",
                "type": "payment",
                "name": "限额到账",
                "properties": {
                    "reference_no": "PAY-LIMIT",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-13",
                    "category": "rent",
                    "status": "unallocated",
                },
            },
            {
                "id": "receivable:limit",
                "type": "receivable",
                "name": "限额应收",
                "properties": {
                    "sequence": 1,
                    "category": "rent",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "due_on": "2026-08-13",
                    "status": "open",
                },
            },
        ):
            self.repository.insert_record("Object", record)
        preview = self.registry.call(
            "preview_action",
            action_id="allocate_payment",
            context_id="payment:limit",
            inputs={
                "receivable_id": "receivable:limit",
                "amount": {"amount": 101, "currency": "CNY"},
                "occurred_on": "2026-08-13",
                "sequence": 1,
            },
        )
        self.assertFalse(preview["valid"])
        self.assertNotIn("preview_token", preview)
        self.assertTrue(any("累计核销金额超过" in error for error in preview["errors"]))


if __name__ == "__main__":
    unittest.main()
