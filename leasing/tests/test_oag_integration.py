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
from uom.workspace import ChangeValidationError  # noqa: E402


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

    def test_approval_decision_updates_one_fact_and_unblocks_contract(self) -> None:
        self.repository.insert_record("Object", {
            "id": "lease_plan:approval-test",
            "type": "lease_plan",
            "name": "待审批方案",
            "properties": {
                "reference_no": "PLAN-APPROVAL-TEST",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-13",
                "status": "draft",
            },
        })
        self.repository.insert_record("Object", {
            "id": "customer:approval-test", "type": "customer", "name": "测试承租方",
            "properties": {"reference_no": "CUSTOMER-APPROVAL-TEST", "status": "active"},
        })
        self.repository.insert_record("Object", {
            "id": "credit:approval-test", "type": "credit", "name": "测试授信",
            "properties": {"code": "CREDIT-APPROVAL-TEST", "category": "finance_lease", "amount": {"amount": 100, "currency": "CNY"}, "status": "active"},
        })
        self.repository.insert_record("Object", {
            "id": "credit_entry:approval-test", "type": "credit_entry", "name": "测试额度预占",
            "properties": {"category": "reserve", "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "posted"},
        })
        self.repository.insert_record("Relation", {
            "id": "rel:credit-entry-approval-test", "type": "contains",
            "from": "credit:approval-test", "to": "credit_entry:approval-test", "properties": {"role": "credit_entry"},
        })
        self.repository.insert_record("Relation", {
            "id": "rel:plan-credit-approval-test", "type": "references",
            "from": "lease_plan:approval-test", "to": "credit:approval-test", "properties": {"role": "reserved_credit"},
        })
        self.repository.insert_record("Relation", {
            "id": "rel:plan-customer-approval-test", "type": "references",
            "from": "lease_plan:approval-test", "to": "customer:approval-test", "properties": {"role": "applicant"},
        })
        self.repository.insert_record("Object", {
            "id": "party:approver",
            "type": "party",
            "name": "风险审批人",
            "properties": {"category": "risk", "status": "active"},
        })
        with self.assertRaisesRegex(ChangeValidationError, "审批"):
            self.registry.call(
                "preview_action",
                action_id="sign_contract",
                context_id="lease_plan:approval-test",
                inputs={
                    "reference_no": "CONTRACT-NEW",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-13",
                    "lessor_id": "party:approver",
                    "lessee_id": "customer:approval-test",
                    "credit_id": "credit:approval-test",
                },
            )

        approval = self.registry.call(
            "preview_action",
            action_id="start_approval",
            context_id="lease_plan:approval-test",
            inputs={
                "reference_no": "APR-TEST",
                "category": "contract_approval",
                "occurred_on": "2026-08-13",
                "submitted_by": "party:approver",
                "process": [{"sequence": 1, "role": "risk"}],
            },
        )
        self.assertTrue(approval["valid"], approval["errors"])
        applied = self.registry.call("apply_action", preview_token=approval["preview_token"])
        self.assertTrue(applied["applied"])
        approval_id = next(item["record"]["id"] for item in approval["operations"] if item["action"] == "create_object")

        decision = self.registry.call(
            "preview_action",
            action_id="record_approval_decision",
            context_id=approval_id,
            inputs={
                "decision": "approved",
                "occurred_on": "2026-08-14",
                "sequence": 1,
                "decided_by": "party:approver",
                "opinion": "风险条件满足",
            },
        )
        self.assertTrue(decision["valid"], decision["errors"])
        self.registry.call("apply_action", preview_token=decision["preview_token"])
        updated = self.repository.query_by_id("Object", approval_id)
        self.assertEqual("pending", updated["properties"]["status"])
        self.assertEqual("pending", updated["properties"]["details"]["result"]["decision"])
        self.assertEqual(1, len(updated["properties"]["details"]["history"]))

        final_decision = self.registry.call(
            "preview_action",
            action_id="record_approval_decision",
            context_id=approval_id,
            inputs={
                "decision": "approved",
                "occurred_on": "2026-08-14",
                "sequence": 2,
                "decided_by": "party:approver",
                "is_final": True,
                "opinion": "同意签约",
            },
        )
        self.assertTrue(final_decision["valid"], final_decision["errors"])
        self.registry.call("apply_action", preview_token=final_decision["preview_token"])
        updated = self.repository.query_by_id("Object", approval_id)
        self.assertEqual("approved", updated["properties"]["status"])
        self.assertEqual("approved", updated["properties"]["details"]["result"]["decision"])
        self.assertEqual(2, len(updated["properties"]["details"]["history"]))

        signed = self.registry.call(
            "preview_action",
            action_id="sign_contract",
            context_id="lease_plan:approval-test",
            inputs={
                "reference_no": "CONTRACT-APPROVAL-TEST",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-15",
                "lessor_id": "party:approver",
                "lessee_id": "customer:approval-test",
                "credit_id": "credit:approval-test",
            },
        )
        self.assertTrue(signed["valid"], signed["errors"])

    def test_approval_has_explicit_reviewed_object_without_ui_context(self) -> None:
        for record in (
            {
                "id": "lease_plan:explicit-review", "type": "lease_plan", "name": "明确送审方案",
                "properties": {"reference_no": "PLAN-EXPLICIT", "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "draft"},
            },
            {
                "id": "party:explicit-submitter", "type": "party", "name": "明确提交人",
                "properties": {"category": "business", "status": "active"},
            },
        ):
            self.repository.insert_record("Object", record)

        prepared = self.registry.get_resolver("uom_actions").prepare_action_form(
            "start_approval",
            context_id="lease_plan:explicit-review",
        )
        self.assertEqual(
            "lease_plan:explicit-review",
            prepared["initial_inputs"]["reviewed_object"],
        )

        preview = self.registry.call(
            "preview_action",
            action_id="start_approval",
            inputs={
                "reviewed_object": "lease_plan:explicit-review",
                "reference_no": "APR-EXPLICIT",
                "category": "lease_plan_approval",
                "occurred_on": "2026-08-13",
                "submitted_by": "party:explicit-submitter",
                "process": [{"sequence": 1, "role": "risk"}],
            },
        )
        self.assertTrue(preview["valid"], preview["errors"])
        reviewed_relation = next(
            item["record"] for item in preview["operations"]
            if item["action"] == "create_relation"
            and item["record"].get("properties", {}).get("role") == "reviewed_object"
        )
        self.assertEqual("lease_plan:explicit-review", reviewed_relation["to"])

    def test_action_rejects_conflicting_ui_context_and_business_object(self) -> None:
        for plan_id in ("lease_plan:context-a", "lease_plan:context-b"):
            self.repository.insert_record("Object", {
                "id": plan_id, "type": "lease_plan", "name": plan_id,
                "properties": {"reference_no": plan_id, "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "draft"},
            })
        self.repository.insert_record("Object", {
            "id": "party:context-test", "type": "party", "name": "提交人",
            "properties": {"category": "business", "status": "active"},
        })
        with self.assertRaisesRegex(ChangeValidationError, "与当前操作对象不一致"):
            self.registry.call(
                "preview_action",
                action_id="start_approval",
                context_id="lease_plan:context-a",
                inputs={
                    "reviewed_object": "lease_plan:context-b",
                    "reference_no": "APR-CONTEXT-MISMATCH",
                    "category": "lease_plan_approval",
                    "occurred_on": "2026-08-13",
                    "submitted_by": "party:context-test",
                    "process": [{"sequence": 1, "role": "risk"}],
                },
            )

    def test_available_actions_explain_unsatisfied_preconditions(self) -> None:
        self.repository.insert_record("Object", {
            "id": "lease_plan:blocked-signing", "type": "lease_plan", "name": "未审批方案",
            "properties": {"reference_no": "PLAN-BLOCKED", "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "draft"},
        })
        available = self.registry.call(
            "get_available_actions",
            context_id="lease_plan:blocked-signing",
        )
        sign_contract = next(
            action for action in available["actions"]
            if action["id"] == "sign_contract"
        )
        self.assertFalse(sign_contract["executable"])
        self.assertEqual(
            ["签订合同前，项目方案必须存在已通过的审批。"],
            sign_contract["blocked_reasons"],
        )

    def test_action_preconditions_are_rechecked_before_apply(self) -> None:
        for record in (
            {
                "id": "payment:precondition-apply", "type": "payment", "name": "待核销收款",
                "properties": {"reference_no": "PAY-PRECONDITION", "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "category": "rent", "status": "unallocated"},
            },
            {
                "id": "receivable:precondition-apply", "type": "receivable", "name": "待核销应收",
                "properties": {"sequence": 1, "category": "rent", "amount": {"amount": 100, "currency": "CNY"}, "due_on": "2026-08-13", "status": "open"},
            },
        ):
            self.repository.insert_record("Object", record)
        preview = self.registry.call(
            "preview_action",
            action_id="allocate_payment",
            context_id="payment:precondition-apply",
            inputs={
                "target_id": "receivable:precondition-apply",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-13",
                "sequence": 1,
            },
        )
        payment = self.repository.query_by_id("Object", "payment:precondition-apply")
        self.repository.update_record(
            "Object",
            payment["id"],
            {"properties": {"status": "allocated"}},
        )
        with self.assertRaisesRegex(ChangeValidationError, "未核销或部分核销"):
            self.registry.call("apply_action", preview_token=preview["preview_token"])

    def test_penalty_can_be_a_payment_allocation_target(self) -> None:
        for record in (
            {
                "id": "payment:penalty-test", "type": "payment", "name": "罚息到账",
                "properties": {"reference_no": "PAY-PENALTY", "amount": {"amount": 20, "currency": "CNY"}, "occurred_on": "2026-08-13", "category": "penalty", "status": "unallocated"},
            },
            {
                "id": "penalty:test", "type": "penalty", "name": "逾期罚息",
                "properties": {"amount": {"amount": 20, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "open"},
            },
        ):
            self.repository.insert_record("Object", record)
        preview = self.registry.call(
            "preview_action",
            action_id="allocate_payment",
            context_id="payment:penalty-test",
            inputs={"target_id": "penalty:test", "amount": {"amount": 20, "currency": "CNY"}, "occurred_on": "2026-08-13", "sequence": 1},
        )
        self.assertTrue(preview["valid"], preview["errors"])
        self.assertEqual("penalty:test", next(item["record"]["to"] for item in preview["operations"] if item["action"] == "create_relation" and item["record"]["type"] == "references"))

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
                "target_id": "receivable:test",
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
                "target_id": "receivable:limit",
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
