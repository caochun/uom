from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from uom.loader import load_domain  # noqa: E402
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
        runtime = load_domain(self.domain_root)
        self.ontology = runtime.ontology
        self.repository = runtime.repository
        self.bindings = runtime.bindings
        self.actions = runtime.actions
        self.graph = runtime.change_store

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def apply_business_action(
        self,
        action_id: str,
        inputs: dict,
        context_id: str = "",
    ) -> dict:
        preview = self.actions.preview_action(
            action_id=action_id,
            inputs=inputs,
            context_id=context_id,
        )
        self.assertTrue(preview["valid"], preview["errors"])
        applied = self.actions.execute_action(
            preview_token=preview["preview_token"],
            reason="端到端业务测试",
        )
        self.assertTrue(applied["applied"])
        return preview

    @staticmethod
    def created_object_id(preview: dict, object_type: str) -> str:
        return next(
            operation["record"]["id"]
            for operation in preview["operations"]
            if operation["action"] == "create_object"
            and operation["record"]["type"] == object_type
        )

    def test_provider_loads_public_leasing_ontology(self) -> None:
        self.assertEqual("UOM 融资租赁领域模型", self.ontology.name)
        self.assertIn("get_contract_trace", self.ontology.functions)
        self.assertIn("audit_finance_consistency", self.ontology.functions)
        self.assertEqual(
            "LeasingActionService",
            type(self.actions).__name__,
        )

    def test_complete_business_actions_close_the_lifecycle(self) -> None:
        for record in (
            {
                "id": "party:lifecycle-lessor",
                "type": "party",
                "name": "测试出租方",
                "properties": {"category": "lessor", "status": "active"},
            },
            {
                "id": "party:lifecycle-approver",
                "type": "party",
                "name": "测试审批主体",
                "properties": {"category": "risk", "status": "active"},
            },
        ):
            self.graph.create_object( record)

        customer_preview = self.apply_business_action(
            "register_customer",
            {"name": "端到端承租方", "reference_no": "CUST-LIFECYCLE"},
        )
        customer_id = self.created_object_id(customer_preview, "customer")

        credit_preview = self.apply_business_action(
            "grant_credit",
            {
                "code": "CR-LIFECYCLE",
                "category": "finance_lease",
                "amount": {"amount": 100, "currency": "CNY"},
            },
            customer_id,
        )
        credit_id = self.created_object_id(credit_preview, "credit")

        plan_preview = self.apply_business_action(
            "create_lease_plan",
            {
                "reference_no": "PLAN-LIFECYCLE",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-01",
                "credit_id": credit_id,
            },
            customer_id,
        )
        plan_id = self.created_object_id(plan_preview, "lease_plan")

        approval_preview = self.apply_business_action(
            "start_approval",
            {
                "reference_no": "APR-LIFECYCLE",
                "category": "lease_plan_approval",
                "occurred_on": "2026-08-02",
                "submitted_by": "party:lifecycle-approver",
                "process": [{"sequence": 1, "role": "risk"}],
            },
            plan_id,
        )
        approval_id = self.created_object_id(approval_preview, "approval")
        self.assertEqual(
            "pending_approval",
            self.graph.get_object(plan_id)["properties"]["status"],
        )

        self.apply_business_action(
            "record_approval_decision",
            {
                "decision": "approved",
                "occurred_on": "2026-08-03",
                "sequence": 1,
                "decided_by": "party:lifecycle-approver",
                "is_final": True,
                "opinion": "同意签约",
            },
            approval_id,
        )
        self.assertEqual(
            "approved",
            self.graph.get_object(plan_id)["properties"]["status"],
        )

        contract_preview = self.apply_business_action(
            "sign_contract",
            {
                "reference_no": "FL-LIFECYCLE",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-04",
                "lessor_id": "party:lifecycle-lessor",
                "lessee_id": customer_id,
                "credit_id": credit_id,
            },
            plan_id,
        )
        contract_id = self.created_object_id(contract_preview, "contract")
        self.assertEqual(
            "contracted",
            self.graph.get_object(plan_id)["properties"]["status"],
        )

        schedule_v1_preview = self.apply_business_action(
            "create_schedule_version",
            {
                "version": "1",
                "valid_from": "2026-08-04",
                "details": {"term_count": 1, "annual_rate": 0.05},
            },
            contract_id,
        )
        schedule_v1_id = self.created_object_id(
            schedule_v1_preview, "schedule_version"
        )
        with self.assertRaisesRegex(ChangeValidationError, "被替代"):
            self.actions.preview_action(
                action_id="create_schedule_version",
                context_id=contract_id,
                inputs={
                    "version": "2",
                    "valid_from": "2026-08-05",
                    "details": {"term_count": 1, "annual_rate": 0.048},
                },
            )
        schedule_v2_preview = self.apply_business_action(
            "create_schedule_version",
            {
                "version": "2",
                "valid_from": "2026-08-05",
                "details": {"term_count": 1, "annual_rate": 0.048},
                "supersedes_id": schedule_v1_id,
            },
            contract_id,
        )
        schedule_v2_id = self.created_object_id(
            schedule_v2_preview, "schedule_version"
        )
        self.assertEqual(
            "inactive",
            self.graph.get_object(schedule_v1_id)["properties"]["status"],
        )

        receivable_preview = self.apply_business_action(
            "create_receivable",
            {
                "sequence": 1,
                "category": "rent",
                "amount": {"amount": 100, "currency": "CNY"},
                "due_on": "2026-09-01",
            },
            schedule_v2_id,
        )
        receivable_id = self.created_object_id(receivable_preview, "receivable")

        payment_preview = self.apply_business_action(
            "record_payment",
            {
                "reference_no": "PAY-LIFECYCLE",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-09-01",
                "contract_id": contract_id,
            },
            customer_id,
        )
        payment_id = self.created_object_id(payment_preview, "payment")

        self.apply_business_action(
            "allocate_payment",
            {
                "target_id": receivable_id,
                "amount": {"amount": 40, "currency": "CNY"},
                "occurred_on": "2026-09-01",
                "sequence": 1,
            },
            payment_id,
        )
        self.assertEqual(
            "partial",
            self.graph.get_object(payment_id)["properties"]["status"],
        )
        with self.assertRaisesRegex(ChangeValidationError, "未结清应收"):
            self.actions.preview_action(
                action_id="settle_contract",
                context_id=contract_id,
                inputs={
                    "reference_no": "SET-TOO-EARLY",
                    "category": "maturity",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-09-01",
                },
            )
        self.apply_business_action(
            "allocate_payment",
            {
                "target_id": receivable_id,
                "amount": {"amount": 60, "currency": "CNY"},
                "occurred_on": "2026-09-02",
                "sequence": 2,
            },
            payment_id,
        )
        self.assertEqual(
            "allocated",
            self.graph.get_object(payment_id)["properties"]["status"],
        )
        self.assertEqual(
            "settled",
            self.graph.get_object(receivable_id)["properties"]["status"],
        )

        settlement_preview = self.apply_business_action(
            "settle_contract",
            {
                "reference_no": "SET-LIFECYCLE",
                "category": "maturity",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-09-03",
            },
            contract_id,
        )
        settlement_id = self.created_object_id(settlement_preview, "settlement")
        self.assertEqual(
            "settled",
            self.graph.get_object(contract_id)["properties"]["status"],
        )
        self.assertEqual(
            "inactive",
            self.graph.get_object(schedule_v2_id)["properties"]["status"],
        )
        audit = self.bindings.call("audit_finance_consistency")
        self.assertTrue(audit["valid"], audit["errors"])
        self.assertEqual(
            {"reserved": 0.0, "used": 0.0},
            audit["credit_balances"][credit_id],
        )
        self.assertTrue(any(
            relation.get("type") == "references"
            and relation.get("to") == settlement_id
            and relation.get("properties", {}).get("role") == "source_settlement"
            for relation in self.graph.query_relations()
        ))

    def test_rejected_plan_releases_reserved_credit(self) -> None:
        for record in (
            {
                "id": "customer:rejection",
                "type": "customer",
                "name": "拒绝方案客户",
                "properties": {"reference_no": "CUST-REJECT", "status": "active"},
            },
            {
                "id": "credit:rejection",
                "type": "credit",
                "name": "拒绝方案授信",
                "properties": {
                    "code": "CR-REJECT",
                    "category": "finance_lease",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "status": "active",
                },
            },
            {
                "id": "lease_plan:rejection",
                "type": "lease_plan",
                "name": "待拒绝方案",
                "properties": {
                    "reference_no": "PLAN-REJECT",
                    "amount": {"amount": 60, "currency": "CNY"},
                    "occurred_on": "2026-08-01",
                    "status": "draft",
                },
            },
            {
                "id": "credit_entry:rejection-reserve",
                "type": "credit_entry",
                "name": "拒绝方案预占",
                "properties": {
                    "category": "reserve",
                    "amount": {"amount": 60, "currency": "CNY"},
                    "occurred_on": "2026-08-01",
                    "status": "posted",
                },
            },
            {
                "id": "party:rejection-approver",
                "type": "party",
                "name": "拒绝方案审批主体",
                "properties": {"category": "risk", "status": "active"},
            },
        ):
            self.graph.create_object( record)
        for relation in (
            {
                "id": "rel:rejection-credit-customer",
                "type": "references",
                "from": "credit:rejection",
                "to": "customer:rejection",
                "properties": {"role": "granted_customer"},
            },
            {
                "id": "rel:rejection-credit-entry",
                "type": "contains",
                "from": "credit:rejection",
                "to": "credit_entry:rejection-reserve",
                "properties": {"role": "credit_entry"},
            },
            {
                "id": "rel:rejection-plan-credit",
                "type": "references",
                "from": "lease_plan:rejection",
                "to": "credit:rejection",
                "properties": {"role": "reserved_credit"},
            },
            {
                "id": "rel:rejection-plan-customer",
                "type": "references",
                "from": "lease_plan:rejection",
                "to": "customer:rejection",
                "properties": {"role": "applicant"},
            },
            {
                "id": "rel:rejection-entry-plan",
                "type": "references",
                "from": "credit_entry:rejection-reserve",
                "to": "lease_plan:rejection",
                "properties": {"role": "source_plan"},
            },
        ):
            self.graph.create_relation( relation)

        approval_preview = self.apply_business_action(
            "start_approval",
            {
                "reference_no": "APR-REJECT",
                "category": "lease_plan_approval",
                "occurred_on": "2026-08-02",
                "submitted_by": "party:rejection-approver",
                "process": [{"sequence": 1, "role": "risk"}],
            },
            "lease_plan:rejection",
        )
        approval_id = self.created_object_id(approval_preview, "approval")
        self.apply_business_action(
            "record_approval_decision",
            {
                "decision": "rejected",
                "occurred_on": "2026-08-03",
                "sequence": 1,
                "decided_by": "party:rejection-approver",
                "is_final": True,
                "opinion": "风险条件不满足",
            },
            approval_id,
        )
        self.assertEqual(
            "rejected",
            self.graph.get_object("lease_plan:rejection")["properties"]["status"],
        )
        audit = self.bindings.call("audit_finance_consistency")
        self.assertTrue(audit["valid"], audit["errors"])
        self.assertEqual(
            {"reserved": 0.0, "used": 0.0},
            audit["credit_balances"]["credit:rejection"],
        )

    def test_customer_action_writes_through_uom_repository(self) -> None:
        preview = self.actions.preview_action(
            action_id="register_customer",
            inputs={
                "name": "测试承租人",
                "reference_no": "TEST-CUSTOMER-001",
            },
        )
        self.assertTrue(preview["valid"], preview["errors"])
        applied = self.actions.execute_action(
            preview_token=preview["preview_token"],
            reason="领域集成测试",
        )
        self.assertTrue(applied["applied"])
        self.assertEqual("测试承租人", self.graph.query_objects()[0]["name"])

    def test_approval_decision_updates_one_fact_and_unblocks_contract(self) -> None:
        self.graph.create_object( {
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
        self.graph.create_object( {
            "id": "customer:approval-test", "type": "customer", "name": "测试承租方",
            "properties": {"reference_no": "CUSTOMER-APPROVAL-TEST", "status": "active"},
        })
        self.graph.create_object( {
            "id": "credit:approval-test", "type": "credit", "name": "测试授信",
            "properties": {"code": "CREDIT-APPROVAL-TEST", "category": "finance_lease", "amount": {"amount": 100, "currency": "CNY"}, "status": "active"},
        })
        self.graph.create_object( {
            "id": "credit_entry:approval-test", "type": "credit_entry", "name": "测试额度预占",
            "properties": {"category": "reserve", "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "posted"},
        })
        self.graph.create_relation( {
            "id": "rel:credit-entry-approval-test", "type": "contains",
            "from": "credit:approval-test", "to": "credit_entry:approval-test", "properties": {"role": "credit_entry"},
        })
        self.graph.create_relation( {
            "id": "rel:plan-credit-approval-test", "type": "references",
            "from": "lease_plan:approval-test", "to": "credit:approval-test", "properties": {"role": "reserved_credit"},
        })
        self.graph.create_relation( {
            "id": "rel:plan-customer-approval-test", "type": "references",
            "from": "lease_plan:approval-test", "to": "customer:approval-test", "properties": {"role": "applicant"},
        })
        self.graph.create_object( {
            "id": "party:approver",
            "type": "party",
            "name": "风险审批人",
            "properties": {"category": "risk", "status": "active"},
        })
        with self.assertRaisesRegex(ChangeValidationError, "审批"):
            self.actions.preview_action(
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

        approval = self.actions.preview_action(
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
        applied = self.actions.execute_action(preview_token=approval["preview_token"])
        self.assertTrue(applied["applied"])
        approval_id = next(item["record"]["id"] for item in approval["operations"] if item["action"] == "create_object")
        self.assertEqual(
            "pending_approval",
            self.graph.get_object("lease_plan:approval-test")["properties"]["status"],
        )

        decision = self.actions.preview_action(
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
        self.actions.execute_action(preview_token=decision["preview_token"])
        updated = self.graph.get_object(approval_id)
        self.assertEqual("pending", updated["properties"]["status"])
        self.assertEqual("pending", updated["properties"]["details"]["result"]["decision"])
        self.assertEqual(1, len(updated["properties"]["details"]["history"]))
        self.assertEqual(
            "pending_approval",
            self.graph.get_object("lease_plan:approval-test")["properties"]["status"],
        )

        final_decision = self.actions.preview_action(
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
        self.actions.execute_action(preview_token=final_decision["preview_token"])
        updated = self.graph.get_object(approval_id)
        self.assertEqual("approved", updated["properties"]["status"])
        self.assertEqual("approved", updated["properties"]["details"]["result"]["decision"])
        self.assertEqual(2, len(updated["properties"]["details"]["history"]))
        self.assertEqual(
            "approved",
            self.graph.get_object("lease_plan:approval-test")["properties"]["status"],
        )

        signed = self.actions.preview_action(
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
        self.actions.execute_action(preview_token=signed["preview_token"])
        self.assertEqual(
            "contracted",
            self.graph.get_object("lease_plan:approval-test")["properties"]["status"],
        )
        available = self.actions.list_actions(
            context_id="lease_plan:approval-test",
        )
        sign_again = next(
            action for action in available["actions"]
            if action["id"] == "sign_contract"
        )
        self.assertFalse(sign_again["executable"])

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
            self.graph.create_object( record)

        prepared = self.actions.prepare_action(
            "start_approval",
            context_id="lease_plan:explicit-review",
        )
        self.assertEqual(
            "lease_plan:explicit-review",
            prepared["initial_inputs"]["reviewed_object"],
        )

        preview = self.actions.preview_action(
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
            self.graph.create_object( {
                "id": plan_id, "type": "lease_plan", "name": plan_id,
                "properties": {"reference_no": plan_id, "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "draft"},
            })
        self.graph.create_object( {
            "id": "party:context-test", "type": "party", "name": "提交人",
            "properties": {"category": "business", "status": "active"},
        })
        with self.assertRaisesRegex(ChangeValidationError, "与当前操作对象不一致"):
            self.actions.preview_action(
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
        self.graph.create_object( {
            "id": "lease_plan:blocked-signing", "type": "lease_plan", "name": "未审批方案",
            "properties": {"reference_no": "PLAN-BLOCKED", "amount": {"amount": 100, "currency": "CNY"}, "occurred_on": "2026-08-13", "status": "draft"},
        })
        available = self.actions.list_actions(
            context_id="lease_plan:blocked-signing",
        )
        sign_contract = next(
            action for action in available["actions"]
            if action["id"] == "sign_contract"
        )
        self.assertFalse(sign_contract["executable"])
        self.assertEqual(
            [
                "签订合同前，项目方案必须存在已通过的审批。",
                "只有已审批通过且尚未签约的项目方案可以签订合同。",
            ],
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
            self.graph.create_object( record)
        preview = self.actions.preview_action(
            action_id="allocate_payment",
            context_id="payment:precondition-apply",
            inputs={
                "target_id": "receivable:precondition-apply",
                "amount": {"amount": 100, "currency": "CNY"},
                "occurred_on": "2026-08-13",
                "sequence": 1,
            },
        )
        payment = self.graph.get_object("payment:precondition-apply")
        self.graph.update_object(
            payment["id"],
            {"properties": {"status": "allocated"}},
        )
        with self.assertRaisesRegex(ChangeValidationError, "未核销或部分核销"):
            self.actions.execute_action(preview_token=preview["preview_token"])

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
            self.graph.create_object( record)
        preview = self.actions.preview_action(
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
            self.graph.create_object( record)
        preview = self.actions.preview_action(
            action_id="allocate_payment",
            context_id="payment:test",
            inputs={
                "target_id": "receivable:test",
                "amount": {"amount": 40, "currency": "CNY"},
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
        self.actions.execute_action(preview_token=preview["preview_token"])
        self.assertEqual(
            "partial",
            self.graph.get_object("payment:test")["properties"]["status"],
        )
        self.assertEqual(
            "partial",
            self.graph.get_object("receivable:test")["properties"]["status"],
        )

        final = self.actions.preview_action(
            action_id="allocate_payment",
            context_id="payment:test",
            inputs={
                "target_id": "receivable:test",
                "amount": {"amount": 60, "currency": "CNY"},
                "occurred_on": "2026-08-14",
                "sequence": 2,
            },
        )
        self.assertTrue(final["valid"], final["errors"])
        self.actions.execute_action(preview_token=final["preview_token"])
        self.assertEqual(
            "allocated",
            self.graph.get_object("payment:test")["properties"]["status"],
        )
        self.assertEqual(
            "settled",
            self.graph.get_object("receivable:test")["properties"]["status"],
        )

    def test_voucher_action_generates_balanced_entries(self) -> None:
        self.graph.create_object( {
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
        preview = self.actions.preview_action(
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
            self.graph.create_object( record)
        preview = self.actions.preview_action(
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
