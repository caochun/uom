from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


OMS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OMS_ROOT / "scripts"))

from validate_model import ModelValidator, load_yaml, validate_model  # noqa: E402


class OmsModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.meta = load_yaml(OMS_ROOT / "metamodel.yaml")
        cls.ontology = load_yaml(OMS_ROOT / "ontology.yaml")
        cls.objects = load_yaml(OMS_ROOT / "data" / "objects.yaml")
        cls.relations = load_yaml(OMS_ROOT / "data" / "relations.yaml")
        cls.object_index = {item["id"]: item for item in cls.objects["objects"]}

    @staticmethod
    def money(item: dict, property_name: str = "amount") -> float:
        return item["facts"][property_name]["amount"]

    def test_model_is_valid(self) -> None:
        self.assertEqual([], validate_model(OMS_ROOT).errors)

    def test_metamodel_contains_only_four_language_elements(self) -> None:
        self.assertEqual(
            {"Concept", "Relation", "Property", "Function"},
            set(self.meta["elements"]),
        )

    def test_ontology_has_only_minimal_economic_concepts(self) -> None:
        self.assertEqual(
            {
                "enterprise",
                "counterparty",
                "revenue",
                "expenditure",
                "cost_expense",
                "asset",
                "receivable",
                "payable",
                "cash_receipt",
                "cash_payment",
            },
            set(self.ontology["concepts"]),
        )

    def test_source_objects_are_provenance_not_core_concepts(self) -> None:
        concepts = set(self.ontology["concepts"])
        self.assertTrue(
            concepts.isdisjoint(
                {
                    "operating_activity",
                    "project",
                    "opportunity",
                    "contract",
                    "invoice",
                    "employee",
                    "payroll_line",
                    "purchase_order",
                }
            )
        )
        revenue = self.object_index["revenue:customer-a-2026-07"]
        self.assertIn("contract:customer-a", revenue["source_refs"])

    def test_cost_is_directly_attributed_to_revenue(self) -> None:
        definition = self.ontology["relations"]["cost_attributed_to_revenue"]
        self.assertEqual("cost_expense", definition["from"])
        self.assertEqual("revenue", definition["to"])
        self.assertEqual("money", definition["properties"]["allocated_amount"])

    def test_revenue_contribution_is_550000(self) -> None:
        revenue_id = "revenue:customer-a-2026-07"
        revenue = self.money(self.object_index[revenue_id])
        allocated = sum(
            self.money(item, "allocated_amount")
            for item in self.relations["relations"]
            if item["type"] == "cost_attributed_to_revenue"
            and item["to"] == revenue_id
            and item["facts"]["status"] == "confirmed"
        )
        self.assertEqual(450000, allocated)
        self.assertEqual(550000, revenue - allocated)

    def test_pending_cost_has_no_forced_center_or_revenue(self) -> None:
        pending_cost_id = "cost:presales-pending"
        dispositions = [
            item
            for item in self.relations["relations"]
            if item["from"] == pending_cost_id
            and item["type"] in {"cost_attributed_to_revenue", "cost_absorbed_by_enterprise"}
        ]
        self.assertEqual([], dispositions)
        self.assertEqual(50000, self.money(self.object_index[pending_cost_id]))

    def test_failed_opportunity_cost_is_absorbed_by_enterprise(self) -> None:
        relation = next(
            item
            for item in self.relations["relations"]
            if item["type"] == "cost_absorbed_by_enterprise"
        )
        self.assertEqual("cost:lost-opportunity", relation["from"])
        self.assertEqual(20000, self.money(relation, "absorbed_amount"))

    def test_enterprise_result_includes_all_costs(self) -> None:
        revenue = sum(
            self.money(item) for item in self.objects["objects"] if item["type"] == "revenue"
        )
        costs = sum(
            self.money(item) for item in self.objects["objects"] if item["type"] == "cost_expense"
        )
        self.assertEqual(520000, costs)
        self.assertEqual(480000, revenue - costs)

    def test_purchase_expenditure_splits_into_cost_and_asset(self) -> None:
        expenditure_id = "expenditure:purchase-a"
        dispositions = [
            item
            for item in self.relations["relations"]
            if item["from"] == expenditure_id
            and item["type"]
            in {"expenditure_recognized_as_cost", "expenditure_capitalized_as_asset"}
        ]
        total = sum(
            self.money(
                item,
                "recognized_amount"
                if item["type"] == "expenditure_recognized_as_cost"
                else "capitalized_amount",
            )
            for item in dispositions
        )
        self.assertEqual(200000, total)

    def test_invalid_relation_endpoint_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(
            item for item in relation_data["relations"] if item["type"] == "cost_attributed_to_revenue"
        )
        relation["to"] = "receivable:customer-a-2026-07"
        result = ModelValidator(self.meta, self.ontology, self.objects, relation_data).validate()
        self.assertTrue(any("object type is not allowed by relation" in error for error in result.errors))

    def test_cost_overallocation_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(
            item
            for item in relation_data["relations"]
            if item["id"] == "rel:people-cost-revenue-a"
        )
        relation["facts"]["allocated_amount"]["amount"] = 300001
        result = ModelValidator(self.meta, self.ontology, self.objects, relation_data).validate()
        self.assertTrue(any("cost disposition" in error and "exceeds" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
