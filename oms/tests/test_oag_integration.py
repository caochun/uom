from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from oag.ontology.loader import load_domain  # noqa: E402


class OagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.oms_root = Path(self.temp_dir.name) / "oms"
        shutil.copytree(
            ROOT / "oms",
            self.oms_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db-*"),
        )
        self.ontology, self.repository, self.registry = load_domain(self.oms_root)

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def test_sqlite_data_is_exposed_through_object_resolvers(self) -> None:
        revenues = self.repository.query("Object", {"type": "revenue"})
        attributions = self.repository.query("Relation", {"type": "cost_attribution"})

        self.assertEqual(["revenue:a-2026-07"], [item["id"] for item in revenues])
        self.assertEqual(2, len(attributions))
        self.assertEqual("resolver", self.ontology.objects["Object"].source.type)
        self.assertEqual("resolver", self.ontology.objects["Relation"].source.type)

    def test_domain_functions_keep_graph_queries_outside_the_llm(self) -> None:
        contribution = self.registry.call(
            "calculate_revenue_contribution",
            revenue_id="revenue:a-2026-07",
        )
        trace = self.registry.call("trace_object", object_id="revenue:a-2026-07", depth=2)

        self.assertEqual(550000, contribution["contribution"])
        self.assertTrue(any(item["type"] == "cost_attribution" for item in trace["relations"]))
        self.assertIn("mutate", self.ontology.excluded_tools)

    def test_resolver_crud_is_persisted_in_sqlite(self) -> None:
        self.repository.insert_record(
            "Object",
            {"id": "note:oag", "type": "note", "name": "OAG resolver 记录"},
        )
        self.repository.insert_record(
            "Relation",
            {
                "id": "rel:oag-enterprise",
                "type": "owned_by",
                "from": "note:oag",
                "to": "enterprise:oms",
            },
        )

        record = self.repository.query_by_id("Object", "note:oag")
        relation = self.repository.query_by_id("Relation", "rel:oag-enterprise")
        self.assertEqual("note", record["type"])
        self.assertEqual("note:oag", relation["from"])

    def test_resolver_search_returns_oag_result_metadata(self) -> None:
        results = self.repository.search_text("示例客户", ["Object"])

        self.assertTrue(results)
        self.assertEqual("Object", results[0]["_object_type"])
        self.assertIn("name", results[0]["_matched_field"])


if __name__ == "__main__":
    unittest.main()
