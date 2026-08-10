from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


OMS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OMS_ROOT / "scripts"))

from validate_model import ModelValidator, load_data, load_yaml, validate_model  # noqa: E402


class OmsModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ontology = load_yaml(OMS_ROOT / "ontology.yaml")
        cls.business_model = load_yaml(OMS_ROOT / "model.yaml")
        cls.objects, cls.relations = load_data(OMS_ROOT)
        cls.object_index = {item["id"]: item for item in cls.objects["objects"]}

    @staticmethod
    def amount(item: dict) -> float:
        return item["properties"]["amount"]["amount"]

    def validate(self, objects: dict | None = None, relations: dict | None = None):
        return ModelValidator(
            self.ontology,
            self.objects if objects is None else objects,
            self.relations if relations is None else relations,
            self.business_model,
        ).validate()

    def test_model_is_valid(self) -> None:
        self.assertEqual([], validate_model(OMS_ROOT).errors)

    def test_business_model_is_validated_with_the_domain(self) -> None:
        invalid_model = copy.deepcopy(self.business_model)
        invalid_model["relation_types"]["cost_attribution"]["from_types"] = ["Cost"]
        result = ModelValidator(
            self.ontology,
            self.objects,
            self.relations,
            invalid_model,
        ).validate()
        self.assertTrue(any("ASCII snake_case" in error for error in result.errors))

    def test_property_types_are_defined_in_the_business_model(self) -> None:
        self.assertNotIn("property_conventions", self.ontology)
        self.assertEqual("money", self.business_model["property_definitions"]["amount"]["type"])
        self.assertTrue(
            self.business_model["relation_types"]["cost_attribution"]["properties"]["amount"]["required"]
        )

    def test_business_property_type_is_enforced(self) -> None:
        object_data = copy.deepcopy(self.objects)
        revenue = next(item for item in object_data["objects"] if item["type"] == "revenue")
        revenue["properties"]["amount"] = "not-money"
        result = self.validate(objects=object_data)
        self.assertTrue(any("properties.amount" in error and "currency" in error for error in result.errors))

    def test_metamodel_is_not_part_of_the_model(self) -> None:
        self.assertFalse((OMS_ROOT / "metamodel.yaml").exists())

    def test_ontology_defines_only_object_and_relation(self) -> None:
        self.assertEqual({"Object", "Relation"}, set(self.ontology["objects"]))
        self.assertEqual("open", self.ontology["objects"]["Object"]["type_policy"])
        self.assertEqual("open", self.ontology["objects"]["Relation"]["type_policy"])

    def test_ontology_is_an_oag_native_domain(self) -> None:
        self.assertEqual("resolver", self.ontology["objects"]["Object"]["source"]["type"])
        self.assertEqual("oms_objects", self.ontology["objects"]["Object"]["source"]["resolver"])
        self.assertIn("trace_object", self.ontology["functions"])
        self.assertIn("user_chat", self.ontology["interaction_policies"])

    def test_business_semantics_are_direct_types_and_properties(self) -> None:
        object_types = {item["type"] for item in self.objects["objects"]}
        self.assertTrue({"customer", "contract", "revenue", "cost"}.issubset(object_types))
        self.assertTrue(
            all("object_type" not in item.get("properties", {}) for item in self.objects["objects"])
        )
        self.assertTrue(
            all("relation_type" not in item.get("properties", {}) for item in self.relations["relations"])
        )
        self.assertTrue(all("role" not in item for item in self.relations["relations"]))

    def test_type_vocabularies_are_extensible(self) -> None:
        object_data = copy.deepcopy(self.objects)
        object_data["objects"].append(
            {
                "id": "custom:new-source",
                "type": "custom_source",
                "name": "新来源对象",
                "properties": {"source_kind": "external"},
            }
        )
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append(
            {
                "id": "rel:custom-source-enterprise",
                "type": "observed_by",
                "from": "custom:new-source",
                "to": "enterprise:oms",
                "properties": {"confidence": 0.9},
            }
        )
        self.assertEqual([], self.validate(object_data, relation_data).errors)

    def test_revenue_has_traceable_source_chain(self) -> None:
        derived = {
            item["from"]: item["to"]
            for item in self.relations["relations"]
            if item["type"] == "derived_from"
        }
        path = ["revenue:a-2026-07"]
        while path[-1] in derived:
            path.append(derived[path[-1]])
        self.assertEqual(
            [
                "revenue:a-2026-07",
                "settlement:a-2026-07",
                "contract:a",
                "opportunity:a",
            ],
            path,
        )

    def test_confirmed_cost_attribution_explains_revenue_contribution(self) -> None:
        revenue_id = "revenue:a-2026-07"
        attributed = sum(
            item["properties"]["amount"]["amount"]
            for item in self.relations["relations"]
            if item["type"] == "cost_attribution"
            and item["to"] == revenue_id
            and item["properties"]["status"] == "confirmed"
        )
        revenue = self.amount(self.object_index[revenue_id])
        self.assertEqual(450000, attributed)
        self.assertEqual(550000, revenue - attributed)

    def test_pending_cost_has_context_but_no_attribution(self) -> None:
        cost_id = "cost:presales-pending"
        links = [item for item in self.relations["relations"] if item["from"] == cost_id]
        self.assertTrue(any(item["type"] == "potential_cost_for" for item in links))
        self.assertFalse(any(item["type"] == "cost_attribution" for item in links))

    def test_failed_opportunity_cost_is_absorbed_by_enterprise(self) -> None:
        relation = next(
            item
            for item in self.relations["relations"]
            if item["id"] == "rel:lost-cost-enterprise"
        )
        self.assertEqual("enterprise_absorption", relation["type"])
        self.assertEqual("enterprise:oms", relation["to"])
        self.assertEqual(20000, self.amount(relation))

    def test_invalid_settlement_endpoints_are_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(
            item for item in relation_data["relations"] if item["type"] == "settles_receivable"
        )
        relation["to"] = "payable:a"
        result = self.validate(relations=relation_data)
        self.assertTrue(any("does not match business model" in error for error in result.errors))

    def test_cost_overallocation_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(
            item
            for item in relation_data["relations"]
            if item["id"] == "rel:people-cost-revenue"
        )
        relation["properties"]["amount"]["amount"] = 300001
        result = self.validate(relations=relation_data)
        self.assertTrue(any("exceeds object amount" in error for error in result.errors))

    def test_missing_required_relation_property_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(
            item for item in relation_data["relations"] if item["type"] == "cost_attribution"
        )
        del relation["properties"]["basis"]
        result = self.validate(relations=relation_data)
        self.assertTrue(any("missing required property basis" in error for error in result.errors))

    def test_derived_from_cycle_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append(
            {
                "id": "rel:opportunity-from-revenue",
                "type": "derived_from",
                "from": "opportunity:a",
                "to": "revenue:a-2026-07",
                "properties": {"basis": "invalid_cycle", "status": "confirmed"},
            }
        )
        result = self.validate(relations=relation_data)
        self.assertTrue(any("derived_from" in error and "cycle" in error for error in result.errors))

    def test_tags_are_optional_search_metadata(self) -> None:
        self.assertTrue(any("tags" in item for item in self.objects["objects"]))
        self.assertTrue(any("tags" not in item for item in self.objects["objects"]))

        relation_data = copy.deepcopy(self.relations)
        attribution = next(
            item for item in relation_data["relations"] if item["type"] == "cost_attribution"
        )
        attribution["tags"] = ["management_view"]
        self.assertEqual([], self.validate(relations=relation_data).errors)

        attribution["tags"] = ["management_view", "management_view"]
        result = self.validate(relations=relation_data)
        self.assertTrue(any("must not contain duplicates" in error for error in result.errors))

        attribution["tags"] = [{"invalid": "tag"}]
        result = self.validate(relations=relation_data)
        self.assertTrue(any("ASCII snake_case" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
