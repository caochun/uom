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
                {
                    "id": "party:operator",
                    "type": "party",
                    "name": "示例高速运营公司",
                    "properties": {"roles": ["operator"]},
                },
                {
                    "id": "highway:g99",
                    "type": "highway",
                    "name": "示例高速",
                    "properties": {"code": "G99"},
                },
                {
                    "id": "section:east",
                    "type": "road_section",
                    "name": "东段",
                    "properties": {"code": "G99-E", "mileage": 42.5},
                },
                {
                    "id": "station:entry",
                    "type": "toll_station",
                    "name": "东入口",
                    "properties": {"code": "G99-ENTRY"},
                },
                {
                    "id": "station:exit",
                    "type": "toll_station",
                    "name": "西出口",
                    "properties": {"code": "G99-EXIT"},
                },
                {
                    "id": "passage:001",
                    "type": "vehicle_passage",
                    "name": "PASS-001",
                    "properties": {
                        "reference_no": "PASS-001",
                        "vehicle_type": "客车一类",
                        "occurred_on": "2026-08-01",
                    },
                },
                {
                    "id": "transaction:001",
                    "type": "toll_transaction",
                    "name": "TX-001",
                    "properties": {
                        "reference_no": "TX-001",
                        "amount": {"amount": 1000, "currency": "CNY"},
                        "occurred_on": "2026-08-01",
                    },
                },
                {
                    "id": "settlement:august",
                    "type": "settlement_batch",
                    "name": "2026年8月清分",
                    "properties": {
                        "reference_no": "SETTLE-202608",
                        "amount": {"amount": 1000, "currency": "CNY"},
                        "period": "2026-08",
                        "occurred_on": "2026-08-02",
                    },
                },
                {
                    "id": "revenue:august",
                    "type": "revenue",
                    "name": "2026年8月通行费收入",
                    "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
                    "tags": ["management_view"],
                },
                {
                    "id": "work:pavement",
                    "type": "maintenance_work",
                    "name": "东段路面养护",
                    "properties": {"category": "pavement", "occurred_on": "2026-08-03"},
                },
                {
                    "id": "cost:allocated",
                    "type": "cost",
                    "name": "路面养护成本",
                    "properties": {"amount": {"amount": 300, "currency": "CNY"}},
                },
                {
                    "id": "cost:pending",
                    "type": "cost",
                    "name": "待分配养护成本",
                    "properties": {"amount": {"amount": 50, "currency": "CNY"}},
                },
                {
                    "id": "receivable:august",
                    "type": "receivable",
                    "name": "8月收费应收",
                    "properties": {
                        "amount": {"amount": 1000, "currency": "CNY"},
                        "occurred_on": "2026-08-02",
                    },
                },
                {
                    "id": "receipt:august",
                    "type": "cash_receipt",
                    "name": "8月收费到账",
                    "properties": {
                        "amount": {"amount": 600, "currency": "CNY"},
                        "occurred_on": "2026-08-05",
                    },
                },
                {
                    "id": "payable:maintenance",
                    "type": "payable",
                    "name": "养护应付",
                    "properties": {
                        "amount": {"amount": 300, "currency": "CNY"},
                        "occurred_on": "2026-08-03",
                    },
                },
            ],
        }
        self.relations = {
            "schema": "oms.data.relations.v2",
            "relations": [
                {
                    "id": "rel:highway-operator",
                    "type": "involves",
                    "from": "highway:g99",
                    "to": "party:operator",
                    "properties": {"role": "operator"},
                },
                {
                    "id": "rel:highway-section",
                    "type": "contains",
                    "from": "highway:g99",
                    "to": "section:east",
                    "properties": {"role": "road_section"},
                },
                {
                    "id": "rel:section-entry",
                    "type": "contains",
                    "from": "section:east",
                    "to": "station:entry",
                    "properties": {"role": "toll_station"},
                },
                {
                    "id": "rel:section-exit",
                    "type": "contains",
                    "from": "section:east",
                    "to": "station:exit",
                    "properties": {"role": "toll_station"},
                },
                {
                    "id": "rel:passage-entry",
                    "type": "occurred_at",
                    "from": "passage:001",
                    "to": "station:entry",
                    "properties": {"role": "entry_station"},
                },
                {
                    "id": "rel:passage-exit",
                    "type": "occurred_at",
                    "from": "passage:001",
                    "to": "station:exit",
                    "properties": {"role": "exit_station"},
                },
                {
                    "id": "rel:transaction-passage",
                    "type": "derived_from",
                    "from": "transaction:001",
                    "to": "passage:001",
                },
                {
                    "id": "rel:settlement-transaction",
                    "type": "derived_from",
                    "from": "settlement:august",
                    "to": "transaction:001",
                },
                {
                    "id": "rel:revenue-settlement",
                    "type": "derived_from",
                    "from": "revenue:august",
                    "to": "settlement:august",
                },
                {
                    "id": "rel:work-section",
                    "type": "affects",
                    "from": "work:pavement",
                    "to": "section:east",
                    "properties": {"role": "maintenance_scope"},
                },
                {
                    "id": "rel:cost-work",
                    "type": "derived_from",
                    "from": "cost:allocated",
                    "to": "work:pavement",
                },
                {
                    "id": "rel:pending-cost-work",
                    "type": "derived_from",
                    "from": "cost:pending",
                    "to": "work:pavement",
                },
                {
                    "id": "rel:cost-revenue",
                    "type": "allocated_to",
                    "from": "cost:allocated",
                    "to": "revenue:august",
                    "properties": {
                        "amount": {"amount": 300, "currency": "CNY"},
                        "status": "confirmed",
                        "occurred_on": "2026-08-04",
                    },
                },
                {
                    "id": "rel:receipt-receivable",
                    "type": "allocated_to",
                    "from": "receipt:august",
                    "to": "receivable:august",
                    "properties": {
                        "amount": {"amount": 600, "currency": "CNY"},
                        "status": "confirmed",
                        "occurred_on": "2026-08-05",
                    },
                },
            ],
        }

    def validate(self, objects=None, relations=None, model=None):
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

    def test_ontology_defines_only_object_and_relation(self) -> None:
        self.assertEqual({"Object", "Relation"}, set(self.ontology["objects"]))
        self.assertEqual("open", self.ontology["objects"]["Object"]["type_policy"])
        self.assertFalse((OMS_ROOT / "metamodel.yaml").exists())

    def test_highway_model_keeps_a_small_operating_spine(self) -> None:
        self.assertEqual(16, len(self.business_model["object_types"]))
        self.assertEqual(7, len(self.business_model["relation_types"]))
        self.assertEqual(17, len(self.business_model["actions"]))
        self.assertEqual(
            {
                "party", "highway", "road_section", "toll_station",
                "vehicle_passage", "toll_transaction", "settlement_batch",
                "revenue", "receivable", "cash_receipt", "maintenance_work",
                "cost", "payable", "cash_payment", "road_event", "evidence",
            },
            set(self.business_model["object_types"]),
        )

    def test_business_model_and_property_types_are_validated(self) -> None:
        self.assertEqual(
            "money",
            self.business_model["property_definitions"]["amount"]["type"],
        )
        invalid_model = copy.deepcopy(self.business_model)
        invalid_model["relation_types"]["allocated_to"]["from_types"] = ["Cost"]
        result = self.validate(model=invalid_model)
        self.assertTrue(any("ASCII snake_case" in error for error in result.errors))

    def test_highway_actions_are_validated_changesets(self) -> None:
        actions = self.business_model["actions"]
        self.assertEqual(["highway"], actions["register_road_section"]["available_on"])
        self.assertEqual(["vehicle_passage"], actions["record_toll_transaction"]["available_on"])
        self.assertEqual(
            ["toll_transaction", "settlement_batch"],
            actions["recognize_toll_revenue"]["available_on"],
        )
        invalid_model = copy.deepcopy(self.business_model)
        invalid_model["actions"]["record_cash_receipt"]["effects"].append({"send_email": {}})
        result = self.validate(model=invalid_model)
        self.assertTrue(any("only create_object and create_relation" in error for error in result.errors))

    def test_business_property_type_is_enforced(self) -> None:
        object_data = copy.deepcopy(self.objects)
        revenue = next(item for item in object_data["objects"] if item["type"] == "revenue")
        revenue["properties"]["amount"] = "not-money"
        result = self.validate(objects=object_data)
        self.assertTrue(any("properties.amount" in error and "currency" in error for error in result.errors))

    def test_type_vocabularies_remain_extensible(self) -> None:
        object_data = copy.deepcopy(self.objects)
        object_data["objects"].append({
            "id": "sensor:new",
            "type": "road_sensor",
            "name": "自定义路侧传感器",
            "properties": {"vendor": "example"},
        })
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append({
            "id": "rel:sensor-highway",
            "type": "observed_by",
            "from": "sensor:new",
            "to": "highway:g99",
        })
        self.assertEqual([], self.validate(object_data, relation_data).errors)

    def test_revenue_has_traceable_highway_source_chain(self) -> None:
        derived = {
            item["from"]: item["to"]
            for item in self.relations["relations"]
            if item["type"] == "derived_from"
        }
        path = ["revenue:august"]
        while path[-1] in derived:
            path.append(derived[path[-1]])
        self.assertEqual(
            ["revenue:august", "settlement:august", "transaction:001", "passage:001"],
            path,
        )

    def test_cost_allocation_explains_revenue_contribution(self) -> None:
        allocations = [
            item for item in self.relations["relations"]
            if item["type"] == "allocated_to" and item["from"].startswith("cost:")
        ]
        self.assertEqual(300, sum(item["properties"]["amount"]["amount"] for item in allocations))

    def test_pending_cost_keeps_its_source_without_revenue_allocation(self) -> None:
        links = [item for item in self.relations["relations"] if item["from"] == "cost:pending"]
        self.assertTrue(any(item["type"] == "derived_from" for item in links))
        self.assertFalse(any(item["type"] == "allocated_to" for item in links))

    def test_invalid_allocation_endpoints_are_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(item for item in relation_data["relations"] if item["id"] == "rel:receipt-receivable")
        relation["to"] = "payable:maintenance"
        result = self.validate(relations=relation_data)
        self.assertTrue(any("allocated_to only supports" in error for error in result.errors))

    def test_allocation_cannot_exceed_its_source(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(item for item in relation_data["relations"] if item["id"] == "rel:cost-revenue")
        relation["properties"]["amount"]["amount"] = 301
        result = self.validate(relations=relation_data)
        self.assertTrue(any("exceeds object amount" in error for error in result.errors))

    def test_required_allocation_status_is_enforced(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation = next(item for item in relation_data["relations"] if item["id"] == "rel:cost-revenue")
        del relation["properties"]["status"]
        result = self.validate(relations=relation_data)
        self.assertTrue(any("missing required property status" in error for error in result.errors))

    def test_derived_from_cycle_is_rejected(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append({
            "id": "rel:passage-revenue",
            "type": "derived_from",
            "from": "passage:001",
            "to": "revenue:august",
        })
        result = self.validate(relations=relation_data)
        self.assertTrue(any("derived_from" in error and "cycle" in error for error in result.errors))

    def test_tags_are_optional_search_metadata(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        allocation = next(item for item in relation_data["relations"] if item["id"] == "rel:cost-revenue")
        allocation["tags"] = ["management_view"]
        self.assertEqual([], self.validate(relations=relation_data).errors)
        allocation["tags"].append("management_view")
        result = self.validate(relations=relation_data)
        self.assertTrue(any("must not contain duplicates" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
