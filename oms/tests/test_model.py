from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


OMS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OMS_ROOT / "scripts"))

from validate_model import ModelValidator, load_data, load_yaml, validate_model  # noqa: E402
from seed_shandong import build_graph  # noqa: E402


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
                    "name": "示例联网收费运营方",
                    "properties": {"category": "operator"},
                },
                {
                    "id": "user:001",
                    "type": "user",
                    "name": "示例客户",
                    "properties": {"reference_no": "U-001"},
                },
                {
                    "id": "vehicle:001",
                    "type": "vehicle",
                    "name": "示例车辆",
                    "properties": {
                        "plate_no": "川A00001",
                        "vehicle_type": "客车一类",
                    },
                },
                {
                    "id": "highway:g99",
                    "type": "toll_road",
                    "name": "示例高速",
                    "properties": {"code": "G99"},
                },
                {
                    "id": "section:east",
                    "type": "section",
                    "name": "东段",
                    "properties": {"code": "G99-E", "mileage": 42.5},
                },
                {
                    "id": "interval:east",
                    "type": "toll_interval",
                    "name": "东段收费单元",
                    "properties": {"code": "TI-001"},
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
                    "id": "lane:entry",
                    "type": "toll_lane",
                    "name": "东入口车道",
                    "properties": {"code": "G99-ENTRY-01", "category": "etc"},
                },
                {
                    "id": "lane:exit",
                    "type": "toll_lane",
                    "name": "西出口车道",
                    "properties": {"code": "G99-EXIT-01", "category": "mixed"},
                },
                {
                    "id": "passage:001",
                    "type": "passage",
                    "name": "PASS-001",
                    "properties": {
                        "reference_no": "PASS-001",
                        "mode": "etc",
                    },
                },
                {
                    "id": "transaction:entry",
                    "type": "toll_transaction",
                    "name": "ENTRY-001",
                    "properties": {
                        "reference_no": "ENTRY-001",
                        "stage": "entry",
                        "occurred_at": "2026-08-01T08:00:00+08:00",
                    },
                },
                {
                    "id": "transaction:exit",
                    "type": "toll_transaction",
                    "name": "EXIT-001",
                    "properties": {
                        "reference_no": "EXIT-001",
                        "stage": "exit",
                        "paid_amount": {"amount": 35, "currency": "CNY"},
                        "occurred_at": "2026-08-01T09:00:00+08:00",
                    },
                },
                {
                    "id": "split:001",
                    "type": "split_record",
                    "name": "SPLIT-001",
                    "properties": {
                        "reference_no": "SPLIT-001",
                        "amount": {"amount": 35, "currency": "CNY"},
                        "occurred_on": "2026-08-02",
                    },
                },
                {
                    "id": "clearing:001",
                    "type": "clearing_result",
                    "name": "CLEAR-001",
                    "properties": {
                        "reference_no": "CLEAR-001",
                        "amount": {"amount": 35, "currency": "CNY"},
                        "period": "2026-08",
                        "occurred_on": "2026-08-03",
                    },
                },
            ],
        }
        self.relations = {
            "schema": "oms.data.relations.v2",
            "relations": [
                {
                    "id": "rel:road-section",
                    "type": "contains",
                    "from": "highway:g99",
                    "to": "section:east",
                },
                {
                    "id": "rel:section-interval",
                    "type": "contains",
                    "from": "section:east",
                    "to": "interval:east",
                },
                {
                    "id": "rel:section-entry",
                    "type": "contains",
                    "from": "section:east",
                    "to": "station:entry",
                },
                {
                    "id": "rel:section-exit",
                    "type": "contains",
                    "from": "section:east",
                    "to": "station:exit",
                },
                {
                    "id": "rel:station-entry-lane",
                    "type": "contains",
                    "from": "station:entry",
                    "to": "lane:entry",
                },
                {
                    "id": "rel:station-exit-lane",
                    "type": "contains",
                    "from": "station:exit",
                    "to": "lane:exit",
                },
                {
                    "id": "rel:user-vehicle",
                    "type": "associates",
                    "from": "user:001",
                    "to": "vehicle:001",
                    "properties": {"role": "owned_vehicle"},
                },
                {
                    "id": "rel:passage-vehicle",
                    "type": "associates",
                    "from": "passage:001",
                    "to": "vehicle:001",
                    "properties": {"role": "passage_vehicle"},
                },
                {
                    "id": "rel:passage-entry",
                    "type": "references",
                    "from": "passage:001",
                    "to": "transaction:entry",
                    "properties": {"role": "entry_transaction"},
                },
                {
                    "id": "rel:passage-exit",
                    "type": "references",
                    "from": "passage:001",
                    "to": "transaction:exit",
                    "properties": {"role": "exit_transaction"},
                },
                {
                    "id": "rel:entry-lane",
                    "type": "references",
                    "from": "transaction:entry",
                    "to": "lane:entry",
                    "properties": {"role": "toll_lane"},
                },
                {
                    "id": "rel:exit-lane",
                    "type": "references",
                    "from": "transaction:exit",
                    "to": "lane:exit",
                    "properties": {"role": "toll_lane"},
                },
                {
                    "id": "rel:passage-split",
                    "type": "derives",
                    "from": "passage:001",
                    "to": "split:001",
                    "properties": {"role": "passage_split"},
                },
                {
                    "id": "rel:split-clearing",
                    "type": "derives",
                    "from": "split:001",
                    "to": "clearing:001",
                    "properties": {"role": "clearing_result"},
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

    def test_v3_model_keeps_the_core_domains(self) -> None:
        self.assertEqual(42, len(self.business_model["object_types"]))
        self.assertEqual(5, len(self.business_model["relation_types"]))
        self.assertEqual(51, len(self.business_model["actions"]))
        self.assertEqual(
            {"route_next", "contains", "references", "associates", "derives"},
            set(self.business_model["relation_types"]),
        )
        self.assertIn("passage", self.business_model["object_types"])
        self.assertIn("clearing_result", self.business_model["object_types"])
        self.assertIn("account_transaction", self.business_model["object_types"])
        self.assertNotIn("passage_medium", self.business_model["object_types"])
        self.assertNotIn("account", self.business_model["object_types"])
        self.assertNotIn("control_entry", self.business_model["object_types"])
        self.assertNotIn("road_node", self.business_model["object_types"])
        for type_id in ("obu", "etc_card", "cpc_card", "user_account", "card_account"):
            self.assertIn(type_id, self.business_model["object_types"])
        for type_id in (
            "account_entry", "business_device", "customer_service_record",
            "fee_rule", "control_record", "operating_parameter",
        ):
            self.assertIn(type_id, self.business_model["object_types"])

    def test_shandong_seed_is_valid_and_reuses_cpc_by_passage(self) -> None:
        objects, relations = build_graph()
        result = self.validate(
            objects={"schema": "oms.data.objects.v2", "objects": objects},
            relations={"schema": "oms.data.relations.v2", "relations": relations},
        )
        self.assertEqual([], result.errors)
        cpc_roles = [
            item.get("properties", {}).get("role")
            for item in relations
            if item.get("to") == "cpc_card:sd_001"
        ]
        self.assertEqual(2, cpc_roles.count("used_cpc_card"))
        self.assertEqual(2, cpc_roles.count("issued_cpc_card"))
        self.assertEqual(2, cpc_roles.count("recovered_cpc_card"))
        self.assertFalse(any(
            item.get("from", "").startswith("vehicle:")
            and item.get("to") == "cpc_card:sd_001"
            for item in relations
        ))
        object_types = {item["id"]: item["type"] for item in objects}
        self.assertFalse(any(
            object_types.get(item["from"]) == "toll_transaction"
            and object_types.get(item["to"]) in {"vehicle", "obu", "etc_card", "toll_station"}
            for item in relations
        ))
        transaction_lanes = [
            item for item in relations
            if object_types.get(item["from"]) == "toll_transaction"
            and object_types.get(item["to"]) == "toll_lane"
        ]
        self.assertEqual(8, len(transaction_lanes))
        container_by_child = {
            item["to"]: item["from"]
            for item in relations
            if item["type"] == "contains"
        }
        for item in transaction_lanes:
            parent = container_by_child[item["to"]]
            if object_types[parent] == "toll_plaza":
                parent = container_by_child[parent]
            self.assertEqual("toll_station", object_types[parent])
        self.assertFalse(any(
            item.get("from") == "consumption:sd_etc_001"
            and object_types.get(item.get("to")) == "etc_card"
            for item in relations
        ))
        passages_with_splits = {
            item["from"]
            for item in relations
            if item["type"] == "derives"
            and object_types.get(item["from"]) == "passage"
            and object_types.get(item["to"]) == "split_record"
        }
        self.assertEqual(
            {item["id"] for item in objects if item["type"] == "passage"},
            passages_with_splits,
        )

    def test_shandong_seed_has_v31_traceability_chains(self) -> None:
        objects, relations = build_graph()
        object_types = {item["id"]: item["type"] for item in objects}
        edges = {
            (item["from"], item["type"], item["to"], item.get("properties", {}).get("role"))
            for item in relations
        }
        self.assertIn(
            ("passage:sd_cpc_001", "references", "check:sd_cpc_001", "vehicle_check"),
            edges,
        )
        self.assertIn(
            ("check:sd_cpc_001", "derives", "second_charge:sd_cpc_001", "check_basis"),
            edges,
        )
        self.assertIn(
            ("account_tx:sd_recharge_001", "derives", "account_entry:sd_recharge_001", "bookkeeping_entry"),
            edges,
        )
        self.assertIn(
            ("user_account:qilu", "contains", "account_entry:sd_recharge_001", "account_entry"),
            edges,
        )
        route_edges = [item for item in relations if item["type"] == "route_next"]
        self.assertEqual(6, len(route_edges))
        self.assertTrue(all(
            object_types[item["from"]] in {"toll_station", "toll_gantry"}
            and object_types[item["to"]] in {"toll_station", "toll_gantry"}
            for item in route_edges
        ))
        interval_node_roles = {
            item.get("properties", {}).get("role")
            for item in relations
            if object_types.get(item["from"]) == "toll_interval"
            and object_types.get(item["to"]) in {"toll_station", "toll_gantry"}
        }
        self.assertEqual({"start_node", "end_node"}, interval_node_roles)

    def test_shandong_seed_covers_all_model_types_and_spatial_objects(self) -> None:
        objects, relations = build_graph()
        self.assertEqual(
            set(self.business_model["object_types"]),
            {item["type"] for item in objects},
        )
        self.assertEqual(
            set(self.business_model["relation_types"]),
            {item["type"] for item in relations},
        )
        spatial_types = {
            "toll_road", "section", "toll_interval", "toll_station", "toll_plaza",
            "toll_lane", "toll_gantry", "service_facility", "business_device",
        }
        spatial_objects = [item for item in objects if item["type"] in spatial_types]
        self.assertTrue(spatial_objects)
        for item in spatial_objects:
            properties = item["properties"]
            self.assertEqual("GCJ-02", properties.get("coordinate_system"), item["id"])
            self.assertLessEqual(-180, properties["longitude"])
            self.assertLessEqual(properties["longitude"], 180)
            self.assertLessEqual(-90, properties["latitude"])
            self.assertLessEqual(properties["latitude"], 90)

    def test_spatial_coordinates_must_be_complete_and_in_range(self) -> None:
        object_data = copy.deepcopy(self.objects)
        station = next(item for item in object_data["objects"] if item["id"] == "station:entry")
        station["properties"]["longitude"] = 181
        result = self.validate(objects=object_data)
        self.assertTrue(any("longitude, latitude and coordinate_system" in error for error in result.errors))
        self.assertTrue(any("longitude" in error and "between -180 and 180" in error for error in result.errors))

    def test_shandong_adjusted_charge_flows_to_split_and_clearing(self) -> None:
        objects, relations = build_graph()
        amounts = {item["id"]: item.get("properties", {}).get("amount") for item in objects}
        self.assertEqual({"amount": 42, "currency": "CNY"}, amounts["second_charge:sd_cpc_001"])
        self.assertEqual(amounts["second_charge:sd_cpc_001"], amounts["split:sd_cpc_001"])
        self.assertEqual(amounts["split:sd_cpc_001"], amounts["clearing:sd_cpc_001"])
        self.assertTrue(any(
            item["from"] == "passage:sd_ticket_001"
            and item["type"] == "derives"
            and item["to"] == "split:sd_ticket_001"
            for item in relations
        ))

    def test_business_model_and_property_types_are_validated(self) -> None:
        self.assertEqual("money", self.business_model["property_definitions"]["amount"]["type"])
        invalid_model = copy.deepcopy(self.business_model)
        invalid_model["relation_types"]["contains"]["from_types"] = ["TollRoad"]
        result = self.validate(model=invalid_model)
        self.assertTrue(any("ASCII snake_case" in error for error in result.errors))

    def test_action_definitions_compile_only_changeset_effects(self) -> None:
        actions = self.business_model["actions"]
        self.assertEqual(["toll_road"], actions["register_section"]["available_on"])
        self.assertEqual(["toll_station", "toll_plaza"], actions["register_toll_lane"]["available_on"])
        self.assertEqual(["passage"], actions["record_vehicle_check"]["available_on"])
        self.assertEqual(["passage"], actions["record_second_charge"]["available_on"])
        self.assertEqual(["account_transaction"], actions["record_account_entry"]["available_on"])
        self.assertEqual(["toll_station", "toll_gantry"], actions["connect_route_node"]["available_on"])
        self.assertEqual(["toll_interval"], actions["bind_interval_nodes"]["available_on"])
        self.assertEqual(["vehicle"], actions["record_etc_passage"]["available_on"])
        self.assertEqual(["vehicle"], actions["record_cpc_passage"]["available_on"])
        self.assertEqual(["toll_transaction"], actions["record_vehicle_id"]["available_on"])
        self.assertNotIn("facility_id", actions["record_vehicle_id"]["inputs"])
        self.assertEqual(["split_record"], actions["produce_clearing_result"]["available_on"])
        self.assertEqual(
            ["cpc_card"],
            actions["record_cpc_passage"]["inputs"]["cpc_card_id"]["object_types"],
        )
        self.assertNotIn("card_id", actions["record_consumption"]["inputs"])
        self.assertEqual(
            ["card_account"],
            actions["record_consumption"]["inputs"]["account_id"]["object_types"],
        )
        invalid_model = copy.deepcopy(self.business_model)
        invalid_model["actions"]["register_party"]["effects"].append({"send_email": {}})
        result = self.validate(model=invalid_model)
        self.assertTrue(any("only create_object and create_relation" in error for error in result.errors))

    def test_business_property_type_is_enforced(self) -> None:
        object_data = copy.deepcopy(self.objects)
        transaction = next(item for item in object_data["objects"] if item["id"] == "transaction:exit")
        transaction["properties"]["paid_amount"] = "not-money"
        result = self.validate(objects=object_data)
        self.assertTrue(any("properties.paid_amount" in error and "currency" in error for error in result.errors))

    def test_transaction_datetime_is_enforced(self) -> None:
        object_data = copy.deepcopy(self.objects)
        transaction = next(item for item in object_data["objects"] if item["id"] == "transaction:entry")
        transaction["properties"]["occurred_at"] = "not-a-datetime"
        result = self.validate(objects=object_data)
        self.assertTrue(any("properties.occurred_at" in error and "datetime" in error for error in result.errors))

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
            "id": "rel:sensor-road",
            "type": "observed_by",
            "from": "sensor:new",
            "to": "highway:g99",
        })
        self.assertEqual([], self.validate(object_data, relation_data).errors)

    def test_passage_has_traceable_split_clearing_chain(self) -> None:
        next_object = {
            item["from"]: item["to"]
            for item in self.relations["relations"]
            if item["type"] == "derives"
        }
        path = ["passage:001"]
        while path[-1] in next_object:
            path.append(next_object[path[-1]])
        self.assertEqual(["passage:001", "split:001", "clearing:001"], path)

    def test_relation_endpoint_constraints_are_enforced(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append({
            "id": "rel:invalid-contains",
            "type": "contains",
            "from": "station:entry",
            "to": "vehicle:001",
        })
        result = self.validate(relations=relation_data)
        self.assertTrue(any("object type does not match business model" in error for error in result.errors))

    def test_derives_is_acyclic(self) -> None:
        relation_data = copy.deepcopy(self.relations)
        relation_data["relations"].append({
            "id": "rel:cycle",
            "type": "derives",
            "from": "split:001",
            "to": "passage:001",
        })
        result = self.validate(relations=relation_data)
        self.assertTrue(result.errors)

    def test_tags_are_optional_search_metadata(self) -> None:
        object_data = copy.deepcopy(self.objects)
        vehicle = next(item for item in object_data["objects"] if item["id"] == "vehicle:001")
        vehicle["tags"] = ["etc_vehicle"]
        self.assertEqual([], self.validate(objects=object_data).errors)
        vehicle["tags"].append("etc_vehicle")
        result = self.validate(objects=object_data)
        self.assertTrue(any("must not contain duplicates" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
