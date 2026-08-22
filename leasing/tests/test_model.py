from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_ROOT = ROOT / "leasing"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from leasing.scripts.seed import build_graph  # noqa: E402
from uom.model import (  # noqa: E402
    load_action_plans,
    load_public_ontology,
    storage_contract_payload,
    workspace_model,
)
from uom.validation import ModelValidator, load_data  # noqa: E402


class LeasingDomainModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.public_model, _ = load_public_ontology(DOMAIN_ROOT)
        cls.model = workspace_model(
            cls.public_model,
            load_action_plans(DOMAIN_ROOT),
        )
        cls.ontology = storage_contract_payload()

    def test_model_and_tracked_graph_are_valid(self) -> None:
        objects, relations = load_data(DOMAIN_ROOT)
        result = ModelValidator(
            self.ontology,
            objects,
            relations,
            self.model,
        ).validate()
        self.assertEqual([], result.errors)

    def test_seed_covers_every_declared_type(self) -> None:
        objects, relations = build_graph()
        self.assertEqual(
            set(self.model["object_types"]),
            {item["type"] for item in objects},
        )
        self.assertEqual(
            set(self.model["relation_types"]),
            {item["type"] for item in relations},
        )

    def test_seed_is_a_multi_case_semantic_dataset(self) -> None:
        objects, relations = build_graph()
        self.assertGreaterEqual(len(objects), 80)
        self.assertGreaterEqual(len(relations), 120)
        statuses_by_type = {}
        for item in objects:
            statuses_by_type.setdefault(item["type"], set()).add(
                item.get("properties", {}).get("status")
            )
        self.assertTrue(
            {"pending", "approved", "rejected"}.issubset(
                statuses_by_type["approval"]
            )
        )
        self.assertTrue(
            {"active", "settled"}.issubset(statuses_by_type["contract"])
        )
        self.assertIn("inactive", statuses_by_type["customer"])

    def test_model_keeps_money_allocation_as_an_object(self) -> None:
        allocation = self.model["object_types"]["allocation"]
        self.assertTrue(allocation["properties"][name]["required"] for name in (
            "amount", "occurred_on", "sequence", "status",
        ))
        self.assertIn("allocate_payment", self.model["actions"])
        self.assertIn("start_approval", self.model["actions"])
        self.assertIn("record_approval_decision", self.model["actions"])

    def test_model_uses_small_stable_relation_vocabulary(self) -> None:
        self.assertEqual(
            {"contains", "references", "associates", "derives", "supersedes"},
            set(self.model["relation_types"]),
        )

    def test_context_actions_declare_their_business_object_inputs(self) -> None:
        expected = {
            "start_approval": "reviewed_object",
            "record_approval_decision": "approval_id",
            "create_lease_plan": "applicant_id",
            "grant_credit": "customer_id",
            "sign_contract": "lease_plan_id",
            "record_loan": "contract_id",
            "create_schedule_version": "contract_id",
            "create_receivable": "schedule_version_id",
            "record_payment": "payer_id",
            "allocate_payment": "payment_id",
            "settle_contract": "contract_id",
            "issue_voucher": "accounting_source",
        }
        for action_id, input_id in expected.items():
            action = self.model["actions"][action_id]
            self.assertEqual(input_id, action["context_input"], action_id)
            self.assertTrue(action["inputs"][input_id]["required"], action_id)
            self.assertNotIn("$context", str(action["effects"]), action_id)

    def test_action_preconditions_declare_business_order_constraints(self) -> None:
        actions = self.model["actions"]
        self.assertEqual(
            "签订合同前，项目方案必须存在已通过的审批。",
            actions["sign_contract"]["requires"][0]["related_object"]["message"],
        )
        self.assertEqual(
            ["unallocated", "partial"],
            actions["allocate_payment"]["requires"][0]["object_status"]["in"],
        )
        self.assertIn("requires", actions["record_loan"])
        self.assertIn("requires", actions["create_receivable"])

    def test_action_outcome_statuses_are_not_user_inputs(self) -> None:
        actions = self.model["actions"]
        for action_id in (
            "register_customer",
            "create_lease_plan",
            "grant_credit",
            "sign_contract",
            "record_loan",
            "create_schedule_version",
            "create_receivable",
            "record_payment",
            "allocate_payment",
            "settle_contract",
            "issue_voucher",
        ):
            self.assertNotIn("status", actions[action_id]["inputs"], action_id)
        self.assertEqual(
            "contracted",
            actions["sign_contract"]["effects"][1]["update_object"]
            ["changes"]["properties"]["status"],
        )
        self.assertEqual(
            "supersedes",
            actions["create_schedule_version"]["effects"][-1]["create_relation"]["type"],
        )

    def test_approval_is_one_decision_fact_with_traceable_process(self) -> None:
        approval = next(item for item in build_graph()[0] if item["type"] == "approval")
        details = approval["properties"]["details"]
        self.assertEqual(["process", "history", "result"], list(details))
        self.assertEqual("approved", details["result"]["decision"])

        approval_relations = [
            item for item in build_graph()[1] if item["from"] == approval["id"]
        ]
        self.assertIn(
            "reviewed_object",
            {item["properties"]["role"] for item in approval_relations},
        )
        self.assertEqual(
            {"submitted_by", "decided_by"},
            {
                item["properties"]["role"]
                for item in approval_relations
                if item["type"] == "associates"
            },
        )
        decided = [
            item for item in approval_relations
            if item["properties"]["role"] == "decided_by"
        ]
        self.assertEqual([2, 3], [item["properties"]["sequence"] for item in decided])


if __name__ == "__main__":
    unittest.main()
