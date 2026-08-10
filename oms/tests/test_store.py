from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from oms.store import OmsStore


ROOT = Path(__file__).resolve().parents[2]


class OmsStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.oms_root = Path(self.temp_dir.name) / "oms"
        shutil.copytree(
            ROOT / "oms",
            self.oms_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db-*"),
        )
        self.store = OmsStore(self.oms_root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bootstrap_contains_model_and_usage(self) -> None:
        data = self.store.bootstrap()
        self.assertEqual({"Object", "Relation"}, set(data["ontology"]["objects"]))
        self.assertIn("revenue", data["model"]["object_types"])
        self.assertGreater(data["model_usage"]["object"]["revenue"]["count"], 0)

    def test_tracked_database_contains_object_relation_graph(self) -> None:
        self.assertTrue(self.store.database_path.is_file())
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            object_count = connection.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
            relation_count = connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        self.assertTrue({"metadata", "objects", "relations"}.issubset(tables))
        self.assertEqual(len(self.store.list_objects()), object_count)
        self.assertEqual(len(self.store.list_relations()), relation_count)

    def test_missing_database_is_initialized_empty(self) -> None:
        empty_database = self.oms_root / "data" / "empty.db"
        empty_store = OmsStore(self.oms_root, database_path=empty_database)

        self.assertEqual([], empty_store.list_objects())
        self.assertEqual([], empty_store.list_relations())

    def test_preview_does_not_write(self) -> None:
        before = self.store.snapshot()
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            revision_before = connection.execute(
                "SELECT value FROM metadata WHERE key = 'data_revision'"
            ).fetchone()[0]
        result = self.store.preview_changes([{
            "action": "create_object",
            "record": {"id": "note:preview", "type": "note", "name": "预览对象"},
        }])
        self.assertTrue(result["valid"])
        self.assertEqual(before, self.store.snapshot())
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            revision_after = connection.execute(
                "SELECT value FROM metadata WHERE key = 'data_revision'"
            ).fetchone()[0]
        self.assertEqual(revision_before, revision_after)

    def test_apply_requires_the_same_changeset_to_be_previewed(self) -> None:
        operation = {
            "action": "create_object",
            "record": {"id": "note:no-preview", "type": "note", "name": "未预览对象"},
        }
        with self.assertRaisesRegex(ValueError, "必须基于当前数据先完成"):
            self.store.apply_changes([operation])

    def test_model_extension_and_object_can_be_applied_together(self) -> None:
        operations = [
            {
                "action": "upsert_property_definition",
                "property_id": "commission_rate",
                "definition": {
                    "name": "返佣比例",
                    "type": "number",
                    "description": "渠道返佣占相关金额的比例。",
                },
            },
            {
                "action": "upsert_object_type",
                "type_id": "channel_commission",
                "definition": {
                    "name": "渠道返佣",
                    "description": "按渠道合作约定形成的返佣成本。",
                    "properties": {
                        "amount": {"required": False},
                        "period": {"required": False},
                        "status": {"required": False},
                        "commission_rate": {"required": False},
                    },
                },
            },
            {
                "action": "create_object",
                "record": {
                    "id": "commission:2026-08",
                    "type": "channel_commission",
                    "name": "2026 年 8 月渠道返佣",
                    "properties": {
                        "status": "recognized",
                        "amount": {"amount": 10000, "currency": "CNY"},
                        "period": "2026-08",
                        "commission_rate": 0.1,
                    },
                },
            },
        ]
        self.assertTrue(self.store.preview_changes(operations)["valid"])
        result = self.store.apply_changes(operations)
        self.assertEqual(
            "number",
            self.store.snapshot()["model"]["property_definitions"]["commission_rate"]["type"],
        )
        self.assertIn("channel_commission", self.store.snapshot()["model"]["object_types"])
        self.assertTrue(any(item["id"] == "commission:2026-08" for item in self.store.list_objects()))
        self.assertEqual(["data/oms.db", "model.yaml"], result["changed_files"])

        reopened = OmsStore(self.oms_root)
        self.assertTrue(any(item["id"] == "commission:2026-08" for item in reopened.list_objects()))

    def test_object_and_relation_are_committed_in_one_database(self) -> None:
        operations = [
            {
                "action": "create_object",
                "record": {"id": "note:sqlite", "type": "note", "name": "SQLite 记录"},
            },
            {
                "action": "create_relation",
                "record": {
                    "id": "rel:sqlite-enterprise",
                    "type": "owned_by",
                    "from": "note:sqlite",
                    "to": "enterprise:oms",
                },
            },
        ]
        self.assertTrue(self.store.preview_changes(operations)["valid"])
        result = self.store.apply_changes(operations)

        self.assertEqual(["data/oms.db"], result["changed_files"])
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            object_row = connection.execute(
                "SELECT type FROM objects WHERE id = 'note:sqlite'"
            ).fetchone()
            relation_row = connection.execute(
                "SELECT source_id, target_id FROM relations WHERE id = 'rel:sqlite-enterprise'"
            ).fetchone()
        self.assertEqual(("note",), object_row)
        self.assertEqual(("note:sqlite", "enterprise:oms"), relation_row)

    def test_user_relation_constraints_are_enforced(self) -> None:
        operation = {
            "action": "create_relation",
            "record": {
                "id": "rel:invalid-attribution",
                "type": "cost_attribution",
                "from": "revenue:a-2026-07",
                "to": "cost:people-a",
                "properties": {
                    "amount": {"amount": 10, "currency": "CNY"},
                    "basis": "invalid",
                    "status": "confirmed",
                    "period": "2026-07",
                },
            },
        }
        result = self.store.preview_changes([operation])
        self.assertFalse(result["valid"])
        self.assertTrue(any("business model" in error for error in result["errors"]))

    def test_revenue_contribution_and_pending_cost_are_deterministic(self) -> None:
        contribution = self.store.revenue_contribution("revenue:a-2026-07")
        self.assertEqual(550000, contribution["contribution"])
        pending_ids = {item["id"] for item in self.store.find_unattributed_costs()}
        self.assertEqual({"cost:presales-pending"}, pending_ids)


if __name__ == "__main__":
    unittest.main()
