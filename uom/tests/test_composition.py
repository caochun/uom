from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from uom.composition import compose_domain_models  # noqa: E402
from uom.loader import load_composed_domain  # noqa: E402


class CompositionTest(unittest.TestCase):
    domain_roots = (
        ROOT / "highway" / "domains" / "passage_charging",
        ROOT / "highway" / "domains" / "customer_accounts",
        ROOT / "highway" / "domains" / "clearing_settlement",
        ROOT / "highway" / "domains" / "facility_operations",
        ROOT / "highway" / "domains" / "pricing_control",
    )

    def test_domains_share_one_vocabulary(self) -> None:
        model = compose_domain_models(self.domain_roots)

        self.assertEqual(21, len(model.objects))
        self.assertEqual(5, len(model.relations))
        self.assertIn("account_entry", model.objects)
        self.assertTrue(
            {"party", "vehicle", "passage", "payment", "account", "settlement"}
            .issubset(model.relations["associates"].from_types)
        )
        self.assertTrue(
            {"vehicle", "toll_medium", "account", "party", "equipment"}
            .issubset(model.relations["associates"].to_types)
        )
        self.assertNotIn("charge", model.relations["associates"].from_types)
        self.assertIn("流水号", model.properties["reference_no"].aliases)
        self.assertIn("get_facility_overview", model.functions)

    def test_composed_runtime_is_read_only_and_binds_all_functions(self) -> None:
        runtime = load_composed_domain(self.domain_roots)
        model_root = runtime.workspace.root
        try:
            self.assertEqual([], runtime.actions.list_actions()["actions"])
            self.assertEqual(
                {
                    "get_business_overview",
                    "get_passage_trace",
                    "find_incomplete_passages",
                    "get_passage_economics",
                    "get_passage_fare_basis",
                    "get_account_ledger",
                    "get_settlement_trace",
                    "get_facility_overview",
                    "get_pricing_control_overview",
                },
                {name for name, _definition in runtime.bindings.list_functions()},
            )
            self.assertIsNotNone(
                runtime.repository.get_object("charge", "charge:etc_001")
            )
            with self.assertRaisesRegex(ValueError, "只读"):
                runtime.change_store.create_object({
                    "id": "party:composed-write",
                    "type": "party",
                    "name": "不应写入",
                })
        finally:
            runtime.close()
        self.assertFalse(model_root.exists())

    def test_composed_actions_route_to_their_source_runtime(self) -> None:
        runtime = load_composed_domain(self.domain_roots, expose_actions=True)
        try:
            self.assertEqual(23, len(runtime.ontology.actions))
            available = runtime.actions.list_actions()["actions"]
            self.assertIn("register_account", {item["id"] for item in available})
            prepared = runtime.actions.prepare_action(
                "register_account",
                initial_inputs={
                    "name": "组合测试账户",
                    "account_kind": "etc_debit",
                    "code": "COMPOSED-ACCOUNT",
                },
            )
            self.assertEqual("register_account", prepared["action"]["id"])
            preview = runtime.actions.preview_action(
                "register_account",
                inputs={
                    "name": "组合测试账户",
                    "account_kind": "etc_debit",
                    "code": "COMPOSED-ACCOUNT",
                },
            )
            self.assertTrue(preview["valid"])
            self.assertTrue(preview["preview_token"].startswith("composed:"))
        finally:
            runtime.close()

    def test_composed_runtime_accepts_a_generator(self) -> None:
        runtime = load_composed_domain((item for item in self.domain_roots[:2]))
        try:
            self.assertIn("account", runtime.ontology.objects)
            self.assertIn("get_account_ledger", runtime.ontology.functions)
        finally:
            runtime.close()

    def test_conflicting_property_types_are_rejected(self) -> None:
        base = {
            "schema": "uom.domain.v1",
            "name": "测试域",
            "version": "1.0.0",
            "repositories": {
                "graph": {
                    "type": "sqlite_graph",
                    "mode": "read_only",
                    "config": {"database": "graph.db"},
                },
            },
            "default_repository": "graph",
            "properties": {"status": {"name": "状态", "type": "string"}},
            "objects": {"item": {"name": "对象", "properties": {"status": "optional"}}},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "model.yaml").write_text(
                yaml.safe_dump(base, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            conflicting = {**base, "properties": {"status": {"name": "状态", "type": "number"}}}
            (second / "model.yaml").write_text(
                yaml.safe_dump(conflicting, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "类型冲突"):
                compose_domain_models([first, second])


if __name__ == "__main__":
    unittest.main()
