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
from app.presentation_tools import register_presentation_tools  # noqa: E402
from oms.store import OmsWorkspaceService  # noqa: E402


class OagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.oms_root = Path(self.temp_dir.name) / "oms"
        shutil.copytree(
            ROOT / "oms",
            self.oms_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        self.ontology, self.repository, self.registry = load_domain(self.oms_root)

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def seed_contribution_example(self) -> None:
        for record in (
            {
                "id": "revenue:test",
                "type": "revenue",
                "name": "测试收入",
                "properties": {"amount": {"amount": 1000, "currency": "CNY"}},
            },
            {
                "id": "cost:test",
                "type": "cost",
                "name": "测试成本",
                "properties": {"amount": {"amount": 400, "currency": "CNY"}},
            },
        ):
            self.repository.insert_record("Object", record)
        self.repository.insert_record(
            "Relation",
            {
                "id": "rel:test-allocation",
                "type": "allocated_to",
                "from": "cost:test",
                "to": "revenue:test",
                "properties": {
                    "amount": {"amount": 400, "currency": "CNY"},
                    "status": "confirmed",
                },
            },
        )

    def test_empty_sqlite_data_is_exposed_through_repository_adapters(self) -> None:
        self.assertEqual([], self.repository.query("Object"))
        self.assertEqual([], self.repository.query("Relation"))
        self.assertEqual("oms_sqlite", self.ontology.objects["Object"].source.type)
        self.assertEqual("oms_sqlite", self.ontology.objects["Relation"].source.type)
        self.assertEqual(
            "OmsSqliteAdapter",
            type(self.repository.adapter_for("Object")).__name__,
        )

    def test_domain_functions_keep_graph_queries_outside_the_llm(self) -> None:
        self.seed_contribution_example()
        contribution = self.registry.call(
            "calculate_revenue_contribution",
            revenue_id="revenue:test",
        )
        trace = self.registry.call("trace_object", object_id="revenue:test", depth=2)

        self.assertEqual(600, contribution["contribution"])
        self.assertTrue(any(item["type"] == "allocated_to" for item in trace["relations"]))
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
            inputs={"name": "测试客户", "roles": ["customer"]},
        )
        applied = self.registry.call(
            "apply_action",
            preview_token=preview["preview_token"],
            reason="测试动作接口",
        )
        self.assertTrue(applied["applied"])
        self.assertTrue(any(item["name"] == "测试客户" for item in self.repository.query("Object")))

    def test_action_form_is_a_bound_presentation_tool(self) -> None:
        workspace = OmsWorkspaceService(self.oms_root, self.repository)
        actions = self.registry.get_resolver("oms_actions")
        harness = SimpleNamespace(tools=ToolRegistry())

        register_presentation_tools(harness, self.ontology, workspace, actions)

        tool = harness.tools.get("ui_open_action_form")
        self.assertIsNotNone(tool)
        self.assertEqual(["action_id"], tool.parameters["required"])
        result = json.loads(tool.handler({
            "action_id": "record_contract",
            "initial_inputs": {"name": "华星科技年度服务合同"},
        }))
        self.assertEqual("action_form", result["presentation"]["kind"])
        self.assertEqual(
            {"name": "华星科技年度服务合同"},
            result["presentation"]["initial_inputs"],
        )
        self.assertFalse(self.ontology.functions["preview_action"].user_visible)
        self.assertFalse(self.ontology.functions["apply_action"].user_visible)


if __name__ == "__main__":
    unittest.main()
