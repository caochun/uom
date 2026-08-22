from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAIN_ROOT = ROOT / "foxoms"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from foxoms.business import audit_foxoms_records  # noqa: E402
from foxoms.scripts.seed import build_graph, validate_graph  # noqa: E402
from uom.loader import load_domain  # noqa: E402
from uom.model import (  # noqa: E402
    load_action_plans,
    load_domain_model,
    load_public_ontology,
    workspace_model,
)
from uom.validation import validate_model  # noqa: E402


class FoxOmsDomainModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_model, _ = load_domain_model(DOMAIN_ROOT)
        cls.public_model, _ = load_public_ontology(DOMAIN_ROOT)
        cls.action_plans = load_action_plans(DOMAIN_ROOT)
        cls.model = workspace_model(cls.public_model, cls.action_plans)

    def test_domain_is_loadable(self) -> None:
        ontology, _, _ = load_domain(DOMAIN_ROOT)

        self.assertEqual("FoxOMS", ontology.name)
        self.assertEqual("uom.domain.v1", self.source_model["schema"])
        self.assertEqual("oag.ontology.v1", self.public_model["schema"])
        self.assertEqual(set(self.public_model["objects"]), set(ontology.objects))

    def test_model_and_graph_are_valid(self) -> None:
        self.assertEqual([], validate_model(DOMAIN_ROOT).errors)

    def test_model_defines_party_and_opportunity_semantics(self) -> None:
        model = self.model

        self.assertEqual(
            {
                "party",
                "opportunity",
                "tender",
                "bid",
                "framework_agreement",
                "contract",
                "order",
                "work_item",
                "personnel",
                "software_resource",
                "hardware_resource",
                "intellectual_asset",
                "invoice",
                "receipt",
            },
            set(model["object_types"]),
        )
        self.assertEqual("业务主体", model["object_types"]["party"]["name"])
        self.assertTrue(
            model["object_types"]["party"]["properties"]["is_managed"]["required"]
        )
        participation = model["relation_types"]["participates_in"]
        self.assertEqual(["party"], participation["from_types"])
        self.assertEqual(
            [
                "opportunity",
                "tender",
                "bid",
                "framework_agreement",
                "contract",
                "order",
                "work_item",
            ],
            participation["to_types"],
        )
        self.assertTrue(participation["properties"]["participation_role"]["required"])
        contains = model["relation_types"]["contains"]
        self.assertEqual(
            ["opportunity", "tender", "framework_agreement", "contract", "order"],
            contains["from_types"],
        )
        self.assertEqual(
            ["tender", "bid", "order", "work_item", "invoice"],
            contains["to_types"],
        )
        derives = model["relation_types"]["derives"]
        self.assertEqual(["bid"], derives["from_types"])
        self.assertEqual(
            ["framework_agreement", "contract"],
            derives["to_types"],
        )
        self.assertFalse(
            model["object_types"]["bid"]["properties"]["bid_result"]["required"]
        )
        allocation = model["relation_types"]["allocated_to"]
        self.assertEqual(
            ["personnel", "software_resource", "hardware_resource"],
            allocation["from_types"],
        )
        self.assertEqual(["order", "work_item"], allocation["to_types"])
        self.assertTrue(allocation["properties"]["quantity"]["required"])
        self.assertTrue(allocation["properties"]["unit"]["required"])
        self.assertFalse(allocation["properties"]["start_date"]["required"])
        self.assertFalse(allocation["properties"]["end_date"]["required"])
        ip_relation = model["relation_types"]["involves_ip"]
        self.assertEqual(["order", "work_item"], ip_relation["from_types"])
        self.assertEqual(["intellectual_asset"], ip_relation["to_types"])
        self.assertTrue(ip_relation["properties"]["ip_role"]["required"])
        settlement = model["relation_types"]["settles"]
        self.assertEqual(["receipt"], settlement["from_types"])
        self.assertEqual(["invoice"], settlement["to_types"])
        self.assertTrue(settlement["properties"]["settled_amount"]["required"])
        self.assertNotIn("invoice", participation["to_types"])
        self.assertNotIn("receipt", participation["to_types"])
        self.assertEqual(
            {
                "register_party",
                "register_personnel",
                "register_software_resource",
                "register_hardware_resource",
                "create_opportunity",
                "register_tender",
                "register_bid",
                "add_business_participant",
                "record_bid_result",
                "sign_framework_agreement",
                "issue_order",
                "sign_project_contract",
                "define_work_item",
                "allocate_personnel",
                "allocate_software",
                "allocate_hardware",
                "register_intellectual_asset",
                "issue_invoice",
                "record_receipt",
                "settle_receipt",
            },
            set(model["actions"]),
        )

    def test_context_actions_have_explicit_context_inputs(self) -> None:
        for action_id, action in self.model["actions"].items():
            if "available_on" not in action:
                continue
            context_input = action.get("context_input")
            self.assertIsNotNone(context_input, action_id)
            self.assertTrue(action["inputs"][context_input]["required"], action_id)
            self.assertNotIn("$context", str(action["effects"]), action_id)

    def test_opportunity_has_no_direct_signing_path(self) -> None:
        signing_actions = {
            "sign_framework_agreement",
            "sign_project_contract",
        }
        for action_id in signing_actions:
            self.assertEqual(["bid"], self.model["actions"][action_id]["available_on"])
        self.assertFalse(
            any(
                action.get("available_on") == ["opportunity"]
                and any(
                    effect.get("create_object", {}).get("type")
                    in {"framework_agreement", "contract"}
                    for effect in action["effects"]
                )
                for action in self.model["actions"].values()
            )
        )

    def test_seed_covers_every_declared_type_and_is_valid(self) -> None:
        objects, relations = build_graph()

        validate_graph(objects, relations)
        self.assertTrue(audit_foxoms_records(objects, relations)["valid"])
        self.assertEqual(
            set(self.model["object_types"]),
            {item["type"] for item in objects},
        )
        self.assertEqual(
            set(self.model["relation_types"]),
            {item["type"] for item in relations},
        )

    def test_seed_contains_both_award_paths_and_split_receipts(self) -> None:
        objects, relations = build_graph()
        object_index = {item["id"]: item for item in objects}

        derived_types = {
            object_index[item["to"]]["type"]
            for item in relations
            if item["type"] == "derives"
        }
        self.assertEqual({"framework_agreement", "contract"}, derived_types)

        receipt_targets = [
            item["to"]
            for item in relations
            if item["type"] == "settles"
            and item["from"] == "receipt:park:002"
        ]
        self.assertEqual(3, len(receipt_targets))

        factory_invoice = object_index["invoice:factory:002"]
        settled = sum(
            item["properties"]["settled_amount"]["amount"]
            for item in relations
            if item["type"] == "settles"
            and item["to"] == factory_invoice["id"]
        )
        self.assertEqual(
            50_000,
            factory_invoice["properties"]["amount"]["amount"] - settled,
        )


if __name__ == "__main__":
    unittest.main()
