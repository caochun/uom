from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

DOMAIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOMAIN_ROOT / "scripts"))
sys.path.insert(0, str(DOMAIN_ROOT.parent / "oag-agent"))
sys.path.insert(0, str(DOMAIN_ROOT.parent))

from seed_shandong import build_graph  # noqa: E402
from uom.composition import compose_domain_models  # noqa: E402
from uom.loader import load_composed_domain  # noqa: E402
from uom.model import load_action_plans, load_public_ontology, public_ontology, storage_contract_payload, workspace_model  # noqa: E402
from uom.registry import DomainRegistry  # noqa: E402
from uom.validation import ModelValidator  # noqa: E402


class UomDomainModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = DomainRegistry.discover(DOMAIN_ROOT)
        cls.domain_paths = [item.path for item in cls.registry.list()]
        cls.passage_root = DOMAIN_ROOT / "domains" / "passage_charging"
        cls.composed_model = compose_domain_models(cls.domain_paths, include_actions=False)
        cls.public_model, _ = public_ontology(cls.composed_model)
        cls.domain_model = workspace_model(
            cls.public_model,
            {"schema": "uom.action_plans.v1", "actions": {}},
            cls.composed_model.model_dump(by_alias=True),
        )
        cls.passage_public_model, _ = load_public_ontology(cls.passage_root)
        cls.passage_domain_model = workspace_model(
            cls.passage_public_model, load_action_plans(cls.passage_root)
        )
        cls.objects, cls.relations = build_graph()

    def validate(self, objects=None, relations=None, model=None):
        return ModelValidator(
            storage_contract_payload(),
            {"schema": "uom.data.objects.v1", "objects": self.objects if objects is None else objects},
            {"schema": "uom.data.relations.v1", "relations": self.relations if relations is None else relations},
            self.domain_model if model is None else model,
        ).validate()

    def test_model_is_small_oag_native_ontology(self) -> None:
        self.assertEqual("oag.ontology.v1", self.public_model["schema"])
        self.assertEqual(21, len(self.public_model["objects"]))
        self.assertEqual(5, len(self.public_model["relations"]))
        self.assertEqual(0, len(self.public_model["actions"]))
        self.assertEqual(8, len(self.passage_public_model["actions"]))
        self.assertIn("get_passage_economics", self.public_model["functions"])
        self.assertIn("get_passage_fare_basis", self.public_model["functions"])
        self.assertIn("rate_rule", self.public_model["objects"])
        self.assertNotIn("toll_transaction", self.public_model["objects"])
        self.assertNotIn("clearing_result", self.public_model["objects"])

    def test_seed_covers_every_model_type_and_is_valid(self) -> None:
        result = self.validate()
        self.assertEqual([], result.errors)
        self.assertEqual(set(self.domain_model["object_types"]), {item["type"] for item in self.objects})
        self.assertEqual(set(self.domain_model["relation_types"]), {item["type"] for item in self.relations})

    def test_cpc_is_reused_per_passage_without_long_term_binding(self) -> None:
        used = [item for item in self.relations if item["type"] == "references" and item["to"] == "medium:cpc_001" and item["properties"].get("role") == "used_medium"]
        self.assertEqual({"passage:cpc_001", "passage:cpc_002"}, {item["from"] for item in used})
        self.assertFalse(any(item["from"].startswith("vehicle:") and item["to"] == "medium:cpc_001" for item in self.relations))

    def test_cpc_issue_and_recovery_are_event_level_relations(self) -> None:
        event_links = [
            item for item in self.relations
            if item["type"] == "references"
            and item["to"] == "medium:cpc_001"
            and item["properties"].get("role") in {"issued_medium", "recovered_medium"}
        ]
        self.assertEqual(
            {("event:cpc1_entry", "issued_medium"), ("event:cpc1_exit", "recovered_medium"),
             ("event:cpc2_entry", "issued_medium"), ("event:cpc2_exit", "recovered_medium")},
            {(item["from"], item["properties"]["role"]) for item in event_links},
        )

    def test_passage_financial_chain_is_explicit(self) -> None:
        edges = {(item["from"], item["to"]) for item in self.relations if item["type"] == "derives"}
        self.assertIn(("passage:etc_001", "charge:etc_001"), edges)
        self.assertIn(("charge:etc_001", "split:etc_001"), edges)
        self.assertIn(("charge:etc_001", "split:etc_external"), edges)
        self.assertIn(("split:etc_001", "settlement:etc_001"), edges)
        self.assertIn(("split:etc_external", "settlement:etc_external"), edges)

    def test_spatial_coordinates_are_complete_and_in_range(self) -> None:
        spatial = [item for item in self.objects if item["type"] in {"toll_road", "section", "toll_interval", "toll_station", "toll_gantry", "toll_lane"}]
        self.assertTrue(spatial)
        for item in spatial:
            props = item["properties"]
            self.assertEqual("GCJ-02", props["coordinate_system"])
            self.assertTrue(-180 <= props["longitude"] <= 180)
            self.assertTrue(-90 <= props["latitude"] <= 90)
        mutated = copy.deepcopy(self.objects)
        next(item for item in mutated if item["type"] == "toll_station")["properties"]["longitude"] = 181
        result = self.validate(objects=mutated)
        self.assertTrue(any("between -180 and 180" in error for error in result.errors))

    def test_property_types_are_enforced(self) -> None:
        mutated = copy.deepcopy(self.objects)
        next(item for item in mutated if item["type"] == "passage_event")["properties"]["occurred_at"] = "bad"
        result = self.validate(objects=mutated)
        self.assertTrue(any("occurred_at" in error and "datetime" in error for error in result.errors))

    def test_relation_endpoint_and_derives_cycle_are_rejected(self) -> None:
        invalid = copy.deepcopy(self.relations)
        invalid.append({"id": "rel:bad", "type": "contains", "from": "station:jinan_east", "to": "vehicle:lu_a12345"})
        self.assertTrue(any("object type does not match domain model" in error for error in self.validate(relations=invalid).errors))
        cycle = copy.deepcopy(self.relations)
        cycle.append({"id": "rel:cycle", "type": "derives", "from": "split:etc_001", "to": "charge:etc_001"})
        self.assertTrue(self.validate(relations=cycle).errors)

    def test_action_plans_match_public_actions(self) -> None:
        self.assertEqual(set(self.passage_public_model["actions"]), set(load_action_plans(self.passage_root)["actions"]))
        self.assertEqual(["passage"], self.passage_domain_model["actions"]["record_passage_event"]["available_on"])
        self.assertEqual(["toll_medium"], self.passage_domain_model["actions"]["record_passage"]["inputs"]["medium_id"]["object_types"])
        self.assertEqual(["rate_rule"], self.passage_domain_model["actions"]["record_charge"]["inputs"]["rate_rule_id"]["object_types"])

        facility_root = DOMAIN_ROOT / "domains" / "facility_operations"
        facility_public, _ = load_public_ontology(facility_root)
        facility_model = workspace_model(
            facility_public, load_action_plans(facility_root)
        )
        self.assertEqual(
            ["toll_road"],
            facility_model["actions"]["register_section"]["available_on"],
        )

    def test_functions_are_bound_to_repository(self) -> None:
        runtime = load_composed_domain(self.domain_paths)
        try:
            self.assertTrue(all(runtime.bindings.has(name) for name in runtime.ontology.functions))
            economics = runtime.bindings.call("get_passage_economics", passage_id="passage:etc_001")
            self.assertEqual(168.0, economics["totals"]["paid"]["amount"])
            self.assertEqual(["charge:etc_001"], economics["linked_ids"]["charge"])
            basis = runtime.bindings.call("get_passage_fare_basis", passage_id="passage:etc_001")
            self.assertEqual(["rate:sd_2026_08"], basis["summary"][0]["rate_version_ids"])
            self.assertEqual(["rate_rule:passenger_1"], basis["summary"][0]["rate_rule_ids"])
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
