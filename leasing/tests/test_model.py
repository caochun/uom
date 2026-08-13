from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_ROOT = ROOT / "leasing"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from leasing.scripts.seed import build_graph  # noqa: E402
from uom.validation import ModelValidator, load_data, load_yaml  # noqa: E402


class LeasingDomainModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_yaml(DOMAIN_ROOT / "model.yaml")
        cls.ontology = load_yaml(ROOT / "uom" / "ontology.yaml")

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

    def test_model_keeps_money_allocation_as_an_object(self) -> None:
        allocation = self.model["object_types"]["allocation"]
        self.assertTrue(allocation["properties"][name]["required"] for name in (
            "amount", "occurred_on", "sequence", "status",
        ))
        self.assertIn("allocate_payment", self.model["actions"])

    def test_model_uses_small_stable_relation_vocabulary(self) -> None:
        self.assertEqual(
            {"contains", "references", "associates", "derives", "supersedes"},
            set(self.model["relation_types"]),
        )


if __name__ == "__main__":
    unittest.main()
