from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from uom.loader import UomRuntimeManager  # noqa: E402
from uom.registry import DomainRegistry  # noqa: E402


class DomainRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DomainRegistry.discover(ROOT / "highway")

    def test_discovery_is_metadata_only_and_prioritizes_child_domain(self) -> None:
        self.assertEqual(
            {
                "highway.passage_charging",
                "highway.customer_accounts",
                "highway.clearing_settlement",
                "highway.facility_operations",
                "highway.pricing_control",
            },
            {item.id for item in self.registry.list()},
        )
        self.assertFalse((ROOT / "highway" / "model.yaml").exists())
        self.assertNotIn(ROOT / "highway", {item.path for item in self.registry.list()})
        self.assertEqual(
            "highway.facility_operations",
            self.registry.match("登记收费站", limit=1)[0].id,
        )

    def test_runtime_manager_loads_only_on_demand_and_reuses_runtime(self) -> None:
        manager = UomRuntimeManager(self.registry)
        self.assertEqual([], manager.loaded_domain_sets)
        runtime = manager.load_for_intent("登记收费站")
        try:
            self.assertEqual([("highway.facility_operations",)], manager.loaded_domain_sets)
            self.assertIs(runtime, manager.load(["highway.facility_operations"]))
            self.assertEqual(8, len(runtime.ontology.actions))
        finally:
            manager.close()


if __name__ == "__main__":
    unittest.main()
