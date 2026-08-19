from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_ROOT = ROOT / "foxoms"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from oag.ontology import load_domain  # noqa: E402
from foxoms.scripts.seed import build_graph, validate_graph  # noqa: E402
from uom.validation import load_yaml, validate_model  # noqa: E402


class FoxOmsDomainModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_yaml(DOMAIN_ROOT / "model.yaml")

    def test_domain_is_loadable(self) -> None:
        ontology, _, registry = load_domain(DOMAIN_ROOT)

        self.assertEqual("FoxOMS", ontology.name)
        self.assertTrue(registry.has("get_model_vocabulary"))

    def test_model_and_graph_are_valid(self) -> None:
        self.assertEqual([], validate_model(DOMAIN_ROOT).errors)

    def test_model_defines_party_and_opportunity_semantics(self) -> None:
        model = load_yaml(DOMAIN_ROOT / "model.yaml")

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
        self.assertEqual({}, model["actions"])

    def test_seed_covers_every_declared_type_and_is_valid(self) -> None:
        objects, relations = build_graph()

        validate_graph(objects, relations)
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
