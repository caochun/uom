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
        cls.current_objects, cls.current_relations = load_data(OMS_ROOT)

    def setUp(self) -> None:
        self.objects = {
            "schema": "oms.data.objects.v2",
            "objects": [
                {"id": "party:customer-a", "type": "party", "name": "客户 A", "properties": {"roles": ["customer"]}},
                {"id": "opportunity:a", "type": "opportunity", "name": "客户 A 商机"},
                {"id": "contract:a", "type": "contract", "name": "客户 A 合同"},
                {"id": "settlement:a", "type": "settlement_result", "name": "客户 A 结算结果"},
                {
                    "id": "revenue:a",
                    "type": "revenue",
                    "name": "客户 A 收入",
                    "properties": {"amount": {"amount": 1000000, "currency": "CNY"}},
                    "tags": ["management_view"],
                },
                {
                    "id": "cost:delivery-a",
                    "type": "cost",
                    "name": "客户 A 交付成本",
                    "properties": {"amount": {"amount": 300000, "currency": "CNY"}},
                },
                {
                    "id": "cost:presales-a",
                    "type": "cost",
                    "name": "客户 A 售前成本",
                    "properties": {"amount": {"amount": 50000, "currency": "CNY"}},
                },
                {
                    "id": "receivable:a",
                    "type": "receivable",
                    "name": "客户 A 应收",
                    "properties": {"amount": {"amount": 1000000, "currency": "CNY"}},
                },
                {
                    "id": "receipt:a",
                    "type": "cash_receipt",
                    "name": "客户 A 收款",
                    "properties": {
                        "amount": {"amount": 600000, "currency": "CNY"},
                        "occurred_on": "2026-08-01",
                    },
                },
                {
                    "id": "payable:a",
                    "type": "payable",
                    "name": "供应商应付",
                    "properties": {"amount": {"amount": 200000, "currency": "CNY"}},
                },
            ],
        }
        self.relations = {
            "schema": "oms.data.relations.v2",
            "relations": [
                {"id": "rel:contract-customer", "type": "involves", "from": "contract:a", "to": "party:customer-a", "properties": {"role": "customer"}},
                {"id": "rel:revenue-settlement", "type": "derived_from", "from": "revenue:a", "to": "settlement:a"},
                {"id": "rel:settlement-contract", "type": "derived_from", "from": "settlement:a", "to": "contract:a"},
                {"id": "rel:contract-opportunity", "type": "derived_from", "from": "contract:a", "to": "opportunity:a"},
                {
                    "id": "rel:cost-revenue",
                    "type": "allocated_to",
                    "from": "cost:delivery-a",
                    "to": "revenue:a",
                    "properties": {
                        "amount": {"amount": 300000, "currency": "CNY"},
                        "status": "confirmed",
                        "occurred_on": "2026-08-01",
                    },
                },
                {
                    "id": "rel:receipt-receivable",
                    "type": "allocated_to",
                    "from": "receipt:a",
                    "to": "receivable:a",
                    "properties": {
                        "amount": {"amount": 600000, "currency": "CNY"},
                        "status": "confirmed",
                        "occurred_on": "2026-08-01",
                    },
                },
                {"id": "rel:presales-opportunity", "type": "associated_with", "from": "cost:presales-a", "to": "opportunity:a", "properties": {"role": "presales_context"}},
            ],
        }

    def validate(self, objects: dict | None = None, relations: dict | None = None, model: dict | None = None):
        return ModelValidator(
            self.ontology,
            self.objects if objects is None else objects,
            self.relations if relations is None else relations,
            self.business_model if model is None else model,
        ).validate()

    def test_model_and_current_database_are_valid(self) -> None:
        self.assertEqual([], validate_model(OMS_ROOT).errors)
        self.assertIsInstance(self.current_objects["objects"], list)
        self.assertIsInstance(self.current_relations["relations"], list)

    def test_business_model_is_validated_with_the_domain(self) -> None:
        invalid_model = copy.deepcopy(self.business_model)
        invalid_model["relation_types"]["allocated_to"]["from_types"] = ["Cost"]
        result = self.validate(model=invalid_model)
        self.assertTrue(any("ASCII snake_case" in error for error in result.errors))

    def test_property_types_are_defined_in_the_business_model(self) -> None:
        self.assertNotIn("property_conventions", self.ontology)
        self.assertEqual("money", self.business_model["property_definitions"]["amount"]["type"])
        self.assertTrue(
            self.business_model["relation_types"]["allocated_to"]["properties"]["amount"]["required"]
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

    def test_business_model_keeps_the_operating_spine_small(self) -> None:
        object_types = set(self.business_model["object_types"])
        relation_types = set(self.business_model["relation_types"])
        self.assertTrue(
            {"party", "opportunity", "contract", "project", "revenue", "cost", "receivable", "payable", "cash_receipt", "cash_payment"}.issubset(object_types)
        )
        self.assertEqual(
            {"involves", "derived_from", "associated_with", "allocated_to", "evidenced_by"},
            relation_types,
        )

    def test_business_actions_are_small_validated_changeset_definitions(self) -> None:
        actions = self.business_model["actions"]
        self.assertIn("record_cash_receipt", actions)
        self.assertEqual("changeset", actions["record_cash_receipt"]["handler"])
        self.assertEqual(["receivable"], actions["record_cash_receipt"]["available_on"])
        self.assertTrue(actions["record_contract"]["inputs"]["customer_id"]["required"])
        self.assertEqual(
            ["opportunity"],
            actions["record_contract_from_opportunity"]["available_on"],
        )
        self.assertNotIn("record_invoice", actions)
        self.assertEqual(["contract", "revenue"], actions["record_sales_invoice"]["available_on"])
        self.assertEqual(["purchase_order", "cost"], actions["record_purchase_invoice"]["available_on"])
        self.assertNotIn("invoice", actions["record_receivable"]["available_on"])
        self.assertNotIn("delivery", actions["recognize_revenue"]["available_on"])

        invalid_model = copy.deepcopy(self.business_model)
        invalid_model["actions"]["record_cash_receipt"]["effects"].append({"send_email": {}})
        result = self.validate(model=invalid_model)
        self.assertTrue(any("only create_object and create_relation" in error for error in result.errors))

    def test_type_vocabularies_are_extensible(self) -> None:
        object_data = copy.deepcopy(self.objects)
        object_data["objects"].append({"id": "custom:new-source", "type": "custom_source", "name": "新来源对象", "properties": {"source_kind": "external"}})
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append({"id": "rel:custom-source-contract", "type": "observed_by", "from": "custom:new-source", "to": "contract:a", "properties": {"confidence": 0.9}})
        self.assertEqual([], self.validate(object_data, relation_data).errors)

    def test_revenue_has_traceable_source_chain(self) -> None:
        derived = {item["from"]: item["to"] for item in self.relations["relations"] if item["type"] == "derived_from"}
        path = ["revenue:a"]
        while path[-1] in derived:
            path.append(derived[path[-1]])
        self.assertEqual(["revenue:a", "settlement:a", "contract:a", "opportunity:a"], path)

    def test_amount_allocation_explains_revenue_contribution(self) -> None:
        allocations = [item for item in self.relations["relations"] if item["type"] == "allocated_to" and item["from"].startswith("cost:")]
        self.assertEqual(300000, sum(item["properties"]["amount"]["amount"] for item in allocations))

    def test_pending_cost_can_have_context_without_revenue_allocation(self) -> None:
        links = [item for item in self.relations["relations"] if item["from"] == "cost:presales-a"]
        self.assertTrue(any(item["type"] == "associated_with" for item in links))
        self.assertFalse(any(item["type"] == "allocated_to" for item in links))

    def test_invalid_allocation_endpoints_are_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(item for item in relation_data["relations"] if item["id"] == "rel:receipt-receivable")
        relation["to"] = "payable:a"
        result = self.validate(relations=relation_data)
        self.assertTrue(any("allocated_to only supports" in error for error in result.errors))

    def test_allocation_cannot_exceed_its_source(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(item for item in relation_data["relations"] if item["id"] == "rel:cost-revenue")
        relation["properties"]["amount"]["amount"] = 300001
        result = self.validate(relations=relation_data)
        self.assertTrue(any("exceeds object amount" in error for error in result.errors))

    def test_missing_required_allocation_status_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(item for item in relation_data["relations"] if item["id"] == "rel:cost-revenue")
        del relation["properties"]["status"]
        result = self.validate(relations=relation_data)
        self.assertTrue(any("missing required property status" in error for error in result.errors))

    def test_derived_from_cycle_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append({"id": "rel:opportunity-revenue", "type": "derived_from", "from": "opportunity:a", "to": "revenue:a"})
        result = self.validate(relations=relation_data)
        self.assertTrue(any("derived_from" in error and "cycle" in error for error in result.errors))

    def test_tags_are_optional_search_metadata(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        allocation = next(item for item in relation_data["relations"] if item["id"] == "rel:cost-revenue")
        allocation["tags"] = ["management_view"]
        self.assertEqual([], self.validate(relations=relation_data).errors)

        allocation["tags"] = ["management_view", "management_view"]
        result = self.validate(relations=relation_data)
        self.assertTrue(any("must not contain duplicates" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
