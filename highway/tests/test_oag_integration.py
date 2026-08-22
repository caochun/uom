from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from oag.harness import Harness  # noqa: E402
from oag.ontology.schema import DataBindingDef  # noqa: E402

from uom.loader import load_domain  # noqa: E402


class OagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.domain_root = Path(self.temp_dir.name) / "highway"
        shutil.copytree(
            ROOT / "highway",
            self.domain_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        runtime = load_domain(self.domain_root)
        self.ontology = runtime.ontology
        self.repository = runtime.repository
        self.bindings = runtime.bindings
        self.actions = runtime.actions
        self.graph = runtime.change_store
        self.workspace = runtime.workspace

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def seed_passage_example(self) -> None:
        for record in (
            {
                "id": "vehicle:test",
                "type": "vehicle",
                "name": "测试车辆",
                "properties": {"plate_no": "川A00001", "vehicle_type": "客车一类"},
            },
            {
                "id": "passage:test",
                "type": "passage",
                "name": "测试通行",
                "properties": {"reference_no": "P-001", "occurred_on": "2026-08-10"},
            },
            {
                "id": "split:test",
                "type": "split_record",
                "name": "测试拆分",
                "properties": {
                    "reference_no": "S-001",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "occurred_on": "2026-08-10",
                },
            },
            {
                "id": "clearing:test",
                "type": "clearing_result",
                "name": "测试清分",
                "properties": {
                    "reference_no": "C-001",
                    "amount": {"amount": 100, "currency": "CNY"},
                    "period": "2026-08",
                    "occurred_on": "2026-08-10",
                },
            },
        ):
            self.graph.create_object( record)
        self.graph.create_relation(
            {
                "id": "rel:test-passage-split",
                "type": "derives",
                "from": "passage:test",
                "to": "split:test",
            },
        )
        self.graph.create_relation(
            {
                "id": "rel:test-split-clearing",
                "type": "derives",
                "from": "split:test",
                "to": "clearing:test",
            },
        )

    def test_empty_sqlite_data_is_exposed_through_repository_adapters(self) -> None:
        self.assertEqual([], self.repository.query_all_objects())
        self.assertEqual([], self.repository.query_all_relations())
        self.assertEqual("graph", self.ontology.objects["passage"].binding.source)
        self.assertEqual("passage", self.ontology.objects["passage"].binding.selector["type"])
        self.assertEqual("uom_sqlite_graph", self.ontology.data_sources["graph"].type)

    def test_provider_loads_the_public_oag_ontology(self) -> None:
        self.assertEqual("OMS 高速联网收费领域模型", self.ontology.name)
        self.assertIs(self.ontology, self.repository.ontology)
        self.assertIn("get_passage_trace", self.ontology.functions)
        instructions = self.ontology.interaction_policies["user_chat"].instructions
        self.assertTrue(any("通行、收费和清分" in item for item in instructions))
        self.assertIsNotNone(self.workspace)
        self.assertIsNotNone(self.actions)
        self.assertFalse(hasattr(self.bindings, "get_service"))

    def test_domain_functions_keep_graph_queries_outside_the_llm(self) -> None:
        self.seed_passage_example()
        trace = self.bindings.call(
            "get_passage_trace",
            passage_id="passage:test",
            depth=3,
        )

        self.assertEqual("passage:test", trace["passage"]["id"])
        self.assertTrue(any(item["_object_type"] == "derives" for item in trace["relations"]))
        self.assertNotIn("mutate", self.ontology.model_dump_json())

    def test_repository_reads_records_persisted_by_uom(self) -> None:
        self.graph.create_object({
            "id": "party:oag", "type": "party", "name": "OAG adapter 记录",
        })
        self.graph.create_object({
            "id": "passage:oag", "type": "passage", "name": "OAG 上下文",
        })
        self.graph.create_relation({
            "id": "rel:oag-context",
            "type": "associates",
            "from": "party:oag",
            "to": "passage:oag",
        })

        record = self.repository.get_object("party", "party:oag")
        relation = self.repository.get_relation("associates", "rel:oag-context")
        self.assertEqual("party", record["_object_type"])
        self.assertEqual("party:oag", relation["from"])

    def test_source_rejects_binding_with_the_wrong_record_kind(self) -> None:
        source = self.repository.sources.get("graph")
        wrong_binding = DataBindingDef(
            source="graph",
            selector={"kind": "relation", "type": "party"},
        )

        with self.assertRaisesRegex(ValueError, "selector.kind"):
            source.query_objects("party", wrong_binding)

    def test_repository_search_returns_oag_result_metadata(self) -> None:
        self.graph.create_object({
            "id": "party:search", "type": "party", "name": "检索客户",
        })
        results = self.repository.search_text("检索客户", ["party"])

        self.assertTrue(results)
        self.assertEqual("party", results[0]["_object_type"])
        self.assertIn("name", results[0]["_matched_field"])

    def test_repository_search_filters_physical_type_before_limit(self) -> None:
        for index in range(5):
            self.graph.create_object({
                "id": f"passage:search-{index}",
                "type": "passage",
                "name": f"同一关键词通行 {index}",
            })
        self.graph.create_object({
            "id": "party:search-after-other-types",
            "type": "party",
            "name": "同一关键词客户",
        })

        results = self.repository.search_text("同一关键词", ["party"], limit=1)

        self.assertEqual(["party:search-after-other-types"], [row["id"] for row in results])

    def test_workspace_changesets_write_through_the_loaded_repository(self) -> None:
        operations = [{
            "action": "create_object",
            "record": {
                "id": "note:changeset",
                "type": "note",
                "name": "Repository ChangeSet 记录",
            },
        }]

        preview = self.workspace.preview_changes(operations)
        applied = self.workspace.apply_changes(operations)

        self.assertTrue(preview["valid"])
        self.assertTrue(applied["applied"])
        self.assertEqual(
            "Repository ChangeSet 记录",
            self.graph.get_object("note:changeset")["name"],
        )

    def test_business_action_functions_share_the_repository(self) -> None:
        available = self.actions.list_actions()
        self.assertTrue(any(item["id"] == "register_party" for item in available["actions"]))

        preview = self.actions.preview_action(
            action_id="register_party",
            inputs={"name": "测试客户", "category": "issuer"},
        )
        applied = self.actions.execute_action(
            preview_token=preview["preview_token"],
            reason="测试动作接口",
        )
        self.assertTrue(applied["applied"])
        self.assertTrue(any(item["name"] == "测试客户" for item in self.repository.query_objects("party")))

    def test_action_form_is_a_bound_interaction_tool(self) -> None:
        harness = Harness(
            self.ontology, self.repository, self.bindings,
            SimpleNamespace(), "test-model",
        )

        tool = harness.tools.get("request_action_input")
        self.assertIsNotNone(tool)
        self.assertEqual(["action_id"], tool.parameters["required"])
        result = json.loads(tool.handler({
            "action_id": "register_toll_road",
            "initial_inputs": {"name": "济青高速", "code": "G35"},
        }))
        self.assertEqual("action_form", result["interaction"]["kind"])
        self.assertEqual(
            {"name": "济青高速", "code": "G35"},
            result["interaction"]["initial_inputs"],
        )
        self.assertIn("register_toll_road", self.ontology.actions)
        self.assertNotIn("preview_action", self.ontology.functions)
        self.assertNotIn("apply_action", self.ontology.functions)


if __name__ == "__main__":
    unittest.main()
