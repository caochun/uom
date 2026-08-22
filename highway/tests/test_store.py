from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from uom.loader import load_domain  # noqa: E402


class UomWorkspaceServiceTest(unittest.TestCase):
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
        self.graph = runtime.change_store
        self.store = runtime.workspace

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def test_bootstrap_contains_model_and_usage(self) -> None:
        data = self.store.bootstrap()
        self.assertEqual("oag.ontology.v1", data["ontology"]["schema"])
        self.assertIn("passage", data["ontology"]["objects"])
        self.assertIn("derives", data["ontology"]["relations"])
        self.assertIn("passage", data["model"]["object_types"])
        self.assertIn("clearing_result", data["model"]["object_types"])
        self.assertTrue(data["model"]["actions"])
        self.assertTrue(all(
            "handler" not in action and "effects" not in action
            for action in data["model"]["actions"].values()
        ))
        self.assertIn("effects", self.store.load_model()["actions"]["register_party"])
        self.assertEqual(0, data["stats"]["object_count"])
        self.assertEqual(0, data["stats"]["relation_count"])
        self.assertNotIn("passage", data["model_usage"]["object"])

    def test_summary_bootstrap_and_paged_query(self) -> None:
        self.graph.create_object(
            {"id": "note:page-1", "type": "note", "name": "第一页"},
        )
        self.graph.create_object(
            {"id": "note:page-2", "type": "note", "name": "第二页"},
        )
        summary = self.store.bootstrap(include_graph=False)
        self.assertNotIn("objects", summary)
        self.assertNotIn("relations", summary)
        self.assertFalse(summary["graph_loaded"])
        self.assertEqual(2, summary["stats"]["object_count"])
        page = self.store.query_records(
            "object", filters={"type": "note"}, limit=1, offset=1, order_by="id",
        )
        self.assertEqual(2, page["total"])
        self.assertEqual(["note:page-2"], [item["id"] for item in page["records"]])
        self.assertFalse(page["has_more"])

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
        self.assertTrue({
            "metadata", "objects", "relations", "action_log", "action_changes",
        }.issubset(tables))
        self.assertEqual(len(self.store.list_objects()), object_count)
        self.assertEqual(len(self.store.list_relations()), relation_count)

    def test_missing_database_is_initialized_empty(self) -> None:
        empty_database = self.domain_root / "data" / "empty.db"
        model_path = self.domain_root / "model.yaml"
        model_text = model_path.read_text(encoding="utf-8")
        model_path.write_text(
            model_text.replace("database: data/graph.db", "database: data/empty.db"),
            encoding="utf-8",
        )
        empty_repository = None
        try:
            empty_runtime = load_domain(self.domain_root)
            empty_repository = empty_runtime.repository
            empty_store = empty_runtime.workspace
            self.assertEqual([], empty_store.list_objects())
            self.assertEqual([], empty_store.list_relations())
            self.assertEqual(empty_database.resolve(), empty_store.database_path)
        finally:
            if empty_repository is not None:
                empty_repository.close()
            model_path.write_text(model_text, encoding="utf-8")

    def test_legacy_database_schema_is_rejected(self) -> None:
        legacy_database = self.domain_root / "data" / "legacy.db"
        with closing(sqlite3.connect(legacy_database)) as connection:
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('schema_version', '3')"
            )

        model_path = self.domain_root / "model.yaml"
        model_text = model_path.read_text(encoding="utf-8")
        model_path.write_text(
            model_text.replace("database: data/graph.db", "database: data/legacy.db"),
            encoding="utf-8",
        )
        try:
            with self.assertRaisesRegex(ValueError, "expected 4"):
                load_domain(self.domain_root)
        finally:
            model_path.write_text(model_text, encoding="utf-8")

    def test_sqlite_queries_filter_sort_page_and_count_without_full_graph(self) -> None:
        for index, name in enumerate(("Bravo", "Alpha", "Charlie"), start=1):
            self.graph.create_object(
                {
                    "id": f"note:query-{index}",
                    "type": "note",
                    "name": name,
                    "properties": {"sequence": index},
                },
            )

        page = self.graph.query_objects(            filters={"type": "note", "properties.sequence__gte": 2},
            order_by="name",
            limit=1,
            offset=1,
        )
        self.assertEqual(["note:query-3"], [item["id"] for item in page])
        self.assertEqual(2, self.graph.count_objects(            filters={"type": "note", "properties.sequence__gte": 2},
        ))
        self.assertEqual(
            ["note:query-2"],
            [item["id"] for item in self.graph.query_objects(                filters={"name__like": "lph"},
            )],
        )
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            self.assertEqual("wal", connection.execute("PRAGMA journal_mode").fetchone()[0])

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

    def test_empty_preview_returns_validation_error(self) -> None:
        result = self.store.preview_changes([])
        self.assertFalse(result["valid"])
        self.assertIn("至少需要一个操作", result["errors"][0])

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
        self.assertEqual(["data/graph.db", "model.yaml"], result["changed_files"])
        with self.store.model_path.open(encoding="utf-8") as stream:
            written_model = yaml.safe_load(stream)
        self.assertEqual("uom.domain.v1", written_model["schema"])
        self.assertIn("properties", written_model)
        self.assertNotIn("data_sources", written_model)

        reopened_runtime = load_domain(self.domain_root)
        reopened_ontology = reopened_runtime.ontology
        reopened_repository = reopened_runtime.repository
        reopened = reopened_runtime.workspace
        self.assertTrue(any(item["id"] == "commission:2026-08" for item in reopened.list_objects()))
        self.assertEqual(self.ontology.name, reopened_ontology.name)
        reopened_repository.close()

    def test_object_and_relation_are_committed_in_one_database(self) -> None:
        operations = [
            {
                "action": "create_object",
                "record": {"id": "note:sqlite", "type": "note", "name": "SQLite 记录"},
            },
            {
                "action": "create_object",
                "record": {"id": "context:sqlite", "type": "context", "name": "SQLite 上下文"},
            },
            {
                "action": "create_relation",
                "record": {
                    "id": "rel:sqlite-context",
                    "type": "observed_by",
                    "from": "note:sqlite",
                    "to": "context:sqlite",
                },
            },
        ]
        self.assertTrue(self.store.preview_changes(operations)["valid"])
        result = self.store.apply_changes(operations)

        self.assertEqual(["data/graph.db"], result["changed_files"])
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            object_row = connection.execute(
                "SELECT type FROM objects WHERE id = 'note:sqlite'"
            ).fetchone()
            relation_row = connection.execute(
                "SELECT source_id, target_id FROM relations WHERE id = 'rel:sqlite-context'"
            ).fetchone()
        self.assertEqual(("note",), object_row)
        self.assertEqual(("note:sqlite", "context:sqlite"), relation_row)

    def test_incremental_changeset_accepts_relation_before_new_endpoints(self) -> None:
        operations = [
            {
                "action": "create_relation",
                "record": {
                    "id": "rel:declared-first",
                    "type": "observed_by",
                    "from": "note:declared-later",
                    "to": "context:declared-later",
                },
            },
            {
                "action": "create_object",
                "record": {
                    "id": "note:declared-later",
                    "type": "note",
                    "name": "后声明的记录",
                },
            },
            {
                "action": "create_object",
                "record": {
                    "id": "context:declared-later",
                    "type": "context",
                    "name": "后声明的上下文",
                },
            },
        ]
        self.assertTrue(self.store.preview_changes(operations)["valid"])
        self.store.apply_changes(operations)
        self.assertIsNotNone(
            self.graph.get_relation("rel:declared-first")
        )

    def test_acyclic_relation_is_rechecked_inside_write_transaction(self) -> None:
        for record_id in ("bill:cycle-a", "bill:cycle-b"):
            self.graph.create_object(
                {"id": record_id, "type": "bill", "name": record_id},
            )
        self.graph.create_relation(
            {
                "id": "rel:cycle-concurrent",
                "type": "derives",
                "from": "bill:cycle-a",
                "to": "bill:cycle-b",
            },
        )
        operation = [{
            "action": "create_relation",
            "record": {
                "id": "rel:cycle-write",
                "type": "derives",
                "from": "bill:cycle-b",
                "to": "bill:cycle-a",
            },
        }]
        with self.assertRaisesRegex(ValueError, "不允许形成环"):
            self.graph.apply_changeset(
                operation,
                acyclic_relation_types={"derives"},
            )

    def test_user_relation_constraints_are_enforced(self) -> None:
        operations = [
            {
                "action": "create_object",
                "record": {
                    "id": "road:invalid",
                    "type": "toll_road",
                    "name": "测试公路",
                    "properties": {"code": "G99"},
                },
            },
            {
                "action": "create_object",
                "record": {
                    "id": "vehicle:invalid",
                    "type": "vehicle",
                    "name": "测试车辆",
                    "properties": {
                        "plate_no": "川A00001",
                        "vehicle_type": "客车一类",
                    },
                },
            },
            {
                "action": "create_relation",
                "record": {
                    "id": "rel:invalid-contains",
                    "type": "contains",
                    "from": "road:invalid",
                    "to": "vehicle:invalid",
                },
            },
        ]
        result = self.store.preview_changes(operations)
        self.assertFalse(result["valid"])
        self.assertTrue(any("domain model" in error for error in result["errors"]))

    def test_lifecycle_revision_and_history_are_maintained_by_uom(self) -> None:
        create = [{
            "action": "create_object",
            "record": {"id": "note:lifecycle", "type": "note", "name": "初始记录"},
        }]
        self.assertTrue(self.store.preview_changes(create)["valid"])
        self.store.apply_changes(
            create,
            reason="创建测试记录",
            actor="tester",
            channel="test",
        )
        created = self.graph.get_object("note:lifecycle")
        self.assertEqual(1, created["lifecycle"]["revision"])
        self.assertEqual(
            created["lifecycle"]["created_at"],
            created["lifecycle"]["updated_at"],
        )

        update = [{
            "action": "update_object",
            "id": "note:lifecycle",
            "changes": {"name": "更新后记录"},
        }]
        self.assertTrue(self.store.preview_changes(update)["valid"])
        self.store.apply_changes(
            update,
            reason="更正名称",
            actor="tester",
            channel="test",
        )
        updated = self.graph.get_object("note:lifecycle")
        self.assertEqual(2, updated["lifecycle"]["revision"])
        self.assertEqual(created["lifecycle"]["created_at"], updated["lifecycle"]["created_at"])

        history = self.store.get_record_history("object", "note:lifecycle")["history"]
        self.assertEqual(2, len(history))
        self.assertEqual("update_object", history[0]["change"]["operation"])
        self.assertEqual("更正名称", history[0]["reason"])
        self.assertEqual("初始记录", history[0]["change"]["before"]["name"])
        self.assertEqual("更新后记录", history[0]["change"]["after"]["name"])
        self.assertEqual("create_object", history[1]["change"]["operation"])
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            indexed_changes = connection.execute(
                "SELECT operation FROM action_changes "
                "WHERE kind = 'object' AND record_id = 'note:lifecycle' ORDER BY id"
            ).fetchall()
        self.assertEqual(
            [("create_object",), ("update_object",)],
            indexed_changes,
        )

    def test_preview_read_set_allows_unrelated_write_but_rejects_target_write(self) -> None:
        create = [
            {
                "action": "create_object",
                "record": {"id": "note:read-set", "type": "note", "name": "待更新"},
            },
            {
                "action": "create_object",
                "record": {"id": "note:unrelated", "type": "note", "name": "无关记录"},
            },
        ]
        self.store.preview_changes(create)
        self.store.apply_changes(create)

        update = [{
            "action": "update_object",
            "id": "note:read-set",
            "changes": {"name": "目标更新"},
        }]
        self.assertTrue(self.store.preview_changes(update)["valid"])
        self.graph.update_object( "note:unrelated", {"name": "无关并发更新"},
        )
        self.store.apply_changes(update)
        self.assertEqual(
            "目标更新",
            self.graph.get_object("note:read-set")["name"],
        )

        second_update = [{
            "action": "update_object",
            "id": "note:read-set",
            "changes": {"name": "不应提交"},
        }]
        self.assertTrue(self.store.preview_changes(second_update)["valid"])
        self.graph.update_object( "note:read-set", {"name": "并发目标更新"},
        )
        with self.assertRaisesRegex(ValueError, "其他操作修改"):
            self.store.apply_changes(second_update)

    def test_delete_retires_record_and_stable_id_cannot_be_reused(self) -> None:
        create = [{
            "action": "create_object",
            "record": {"id": "note:retired", "type": "note", "name": "待退役记录"},
        }]
        self.store.preview_changes(create)
        self.store.apply_changes(create)

        retire = [{"action": "delete_object", "id": "note:retired"}]
        self.assertTrue(self.store.preview_changes(retire)["valid"])
        self.store.apply_changes(retire, reason="记录不再有效")
        self.assertIsNone(self.graph.get_object("note:retired"))
        self.assertFalse(any(item["id"] == "note:retired" for item in self.store.list_objects()))

        with closing(sqlite3.connect(self.store.database_path)) as connection:
            row = connection.execute(
                "SELECT revision, retired_at FROM objects WHERE id = 'note:retired'"
            ).fetchone()
        self.assertEqual(2, row[0])
        self.assertTrue(row[1])

        reused = self.store.preview_changes(create)
        self.assertFalse(reused["valid"])
        self.assertTrue(any("曾经使用" in error for error in reused["errors"]))

    def test_relation_identity_fields_are_immutable(self) -> None:
        create = [
            {
                "action": "create_object",
                "record": {"id": "note:left", "type": "note", "name": "Left"},
            },
            {
                "action": "create_object",
                "record": {"id": "context:right", "type": "context", "name": "Right"},
            },
            {
                "action": "create_relation",
                "record": {
                    "id": "rel:immutable",
                    "type": "observed_by",
                    "from": "note:left",
                    "to": "context:right",
                },
            },
        ]
        self.store.preview_changes(create)
        self.store.apply_changes(create)

        result = self.store.preview_changes([{
            "action": "update_relation",
            "id": "rel:immutable",
            "changes": {"to": "note:left"},
        }])
        self.assertFalse(result["valid"])
        self.assertTrue(any("稳定身份字段" in error for error in result["errors"]))

    def test_used_property_type_requires_explicit_migration(self) -> None:
        create = [{
            "action": "create_object",
            "record": {
                "id": "road:typed-property",
                "type": "toll_road",
                "name": "属性迁移测试公路",
                "properties": {"code": "G99"},
            },
        }]
        self.store.preview_changes(create)
        self.store.apply_changes(create)
        definition = dict(
            self.store.snapshot()["model"]["property_definitions"]["code"]
        )
        definition["type"] = "number"
        result = self.store.preview_changes([{
            "action": "upsert_property_definition",
            "property_id": "code",
            "definition": definition,
        }])
        self.assertFalse(result["valid"])
        self.assertTrue(any("显式数据迁移" in error for error in result["errors"]))

    def test_highway_overview_reports_incomplete_passages(self) -> None:
        self.graph.create_object(
            {
                "id": "passage:test",
                "type": "passage",
                "name": "测试通行",
                "properties": {
                    "reference_no": "P-001",
                    "occurred_on": "2026-08-10",
                },
            },
        )
        overview = self.bindings.call("get_business_overview")
        self.assertEqual(1, overview["incomplete_passage_count"])
        self.assertEqual(1, overview["object_types"]["passage"])


if __name__ == "__main__":
    unittest.main()
