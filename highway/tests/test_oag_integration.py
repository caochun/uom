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

from oag.ontology.loader import load_domain  # noqa: E402
from oag.tools.registry import ToolRegistry  # noqa: E402
from highway.app.presentation_tools import register_presentation_tools  # noqa: E402
from uom.workspace import UomWorkspaceService  # noqa: E402


class OagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.domain_root = Path(self.temp_dir.name) / "highway"
        shutil.copytree(
            ROOT / "highway",
            self.domain_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        self.ontology, self.repository, self.registry = load_domain(self.domain_root)

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
            self.repository.insert_record("Object", record)
        self.repository.insert_record(
            "Relation",
            {
                "id": "rel:test-passage-split",
                "type": "derives",
                "from": "passage:test",
                "to": "split:test",
            },
        )
        self.repository.insert_record(
            "Relation",
            {
                "id": "rel:test-split-clearing",
                "type": "derives",
                "from": "split:test",
                "to": "clearing:test",
            },
        )

    def test_empty_sqlite_data_is_exposed_through_repository_adapters(self) -> None:
        self.assertEqual([], self.repository.query("Object"))
        self.assertEqual([], self.repository.query("Relation"))
        self.assertEqual("uom_sqlite", self.ontology.objects["Object"].source.type)
        self.assertEqual("uom_sqlite", self.ontology.objects["Relation"].source.type)
        self.assertEqual(
            "UomSqliteAdapter",
            type(self.repository.adapter_for("Object")).__name__,
        )

    def test_provider_builds_one_effective_ontology_for_the_runtime(self) -> None:
        self.assertEqual("OMS 高速联网收费领域模型", self.ontology.name)
        self.assertIs(self.ontology, self.repository.ontology)
        self.assertIn("trace_object", self.ontology.functions)
        self.assertIn("get_passage_trace", self.ontology.functions)
        instructions = self.ontology.interaction_policies["user_chat"].instructions
        self.assertTrue(any("properties" in item for item in instructions))
        self.assertTrue(any("通行、收费和清分" in item for item in instructions))
        self.assertIsNotNone(self.registry.get_resolver("uom_workspace"))
        self.assertIsNotNone(self.registry.get_resolver("uom_actions"))
        self.assertEqual(
            "SpatialViewService",
            type(self.registry.get_resolver("spatial_view")).__name__,
        )
        self.assertIsNone(self.registry.get_resolver("oms_actions"))

    def test_domain_functions_keep_graph_queries_outside_the_llm(self) -> None:
        self.seed_passage_example()
        trace = self.registry.call(
            "get_passage_trace",
            passage_id="passage:test",
            depth=3,
        )

        self.assertEqual("passage:test", trace["passage"]["id"])
        self.assertTrue(any(item["type"] == "derives" for item in trace["relations"]))
        self.assertIn("mutate", self.ontology.excluded_tools)

    def test_repository_crud_is_persisted_in_sqlite(self) -> None:
        self.repository.insert_record(
            "Object",
            {"id": "note:oag", "type": "note", "name": "OAG adapter 记录"},
        )
        self.repository.insert_record(
            "Object",
            {"id": "context:oag", "type": "context", "name": "OAG 上下文"},
        )
        self.repository.insert_record(
            "Relation",
            {
                "id": "rel:oag-context",
                "type": "observed_by",
                "from": "note:oag",
                "to": "context:oag",
            },
        )

        record = self.repository.query_by_id("Object", "note:oag")
        relation = self.repository.query_by_id("Relation", "rel:oag-context")
        self.assertEqual("note", record["type"])
        self.assertEqual("note:oag", relation["from"])

    def test_repository_search_returns_oag_result_metadata(self) -> None:
        self.repository.insert_record(
            "Object",
            {"id": "party:search", "type": "party", "name": "检索客户"},
        )
        results = self.repository.search_text("检索客户", ["Object"])

        self.assertTrue(results)
        self.assertEqual("Object", results[0]["_object_type"])
        self.assertIn("name", results[0]["_matched_field"])

    def test_changeset_functions_write_through_the_loaded_repository(self) -> None:
        operations = [{
            "action": "create_object",
            "record": {
                "id": "note:changeset",
                "type": "note",
                "name": "Repository ChangeSet 记录",
            },
        }]

        preview = self.registry.call("preview_changes", operations=operations)
        applied = self.registry.call("apply_changes", operations=operations)

        self.assertTrue(preview["valid"])
        self.assertTrue(applied["applied"])
        self.assertEqual(
            "Repository ChangeSet 记录",
            self.repository.query_by_id("Object", "note:changeset")["name"],
        )

    def test_business_action_functions_share_the_repository(self) -> None:
        available = self.registry.call("get_available_actions")
        self.assertTrue(any(item["id"] == "register_party" for item in available["actions"]))

        preview = self.registry.call(
            "preview_action",
            action_id="register_party",
            inputs={"name": "测试客户", "category": "issuer"},
        )
        applied = self.registry.call(
            "apply_action",
            preview_token=preview["preview_token"],
            reason="测试动作接口",
        )
        self.assertTrue(applied["applied"])
        self.assertTrue(any(item["name"] == "测试客户" for item in self.repository.query("Object")))

    def test_action_form_is_a_bound_presentation_tool(self) -> None:
        workspace = UomWorkspaceService(self.domain_root, self.repository)
        actions = self.registry.get_resolver("uom_actions")
        harness = SimpleNamespace(tools=ToolRegistry())

        register_presentation_tools(harness, self.ontology, workspace, actions)

        tool = harness.tools.get("ui_open_action_form")
        self.assertIsNotNone(tool)
        self.assertEqual(["action_id"], tool.parameters["required"])
        result = json.loads(tool.handler({
            "action_id": "register_toll_road",
            "initial_inputs": {"name": "济青高速", "code": "G35"},
        }))
        self.assertEqual("action_form", result["presentation"]["kind"])
        self.assertEqual(
            {"name": "济青高速", "code": "G35"},
            result["presentation"]["initial_inputs"],
        )
        self.assertFalse(self.ontology.functions["preview_action"].user_visible)
        self.assertFalse(self.ontology.functions["apply_action"].user_visible)


if __name__ == "__main__":
    unittest.main()
