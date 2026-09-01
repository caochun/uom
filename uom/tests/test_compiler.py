from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError
import yaml

from uom.compiler import compile_ontology
from uom.model import load_domain_model, update_source_vocabulary, workspace_model
from uom.schema import DomainModel


BASE_MODEL = {
    "schema": "uom.domain.v1",
    "name": "Example",
    "version": "1.0.0",
    "repositories": {
        "graph": {
            "type": "sqlite_graph",
            "mode": "writable",
            "config": {"database": "data/graph.db"},
        },
        "crm": {
            "type": "crm_api",
            "mode": "read_only",
            "config": {"endpoint": "https://crm.example.test"},
        },
    },
    "default_repository": "graph",
    "properties": {
        "status": {"name": "状态", "type": "string"},
    },
    "objects": {
        "contract": {
            "name": "合同",
            "properties": {"status": "required"},
        },
        "customer": {
            "name": "客户",
            "repository": "crm",
            "selector": {"resource": "accounts"},
            "mapping": {"id": "account_id"},
        },
    },
    "relations": {
        "signed_by": {
            "name": "签约方",
            "from": ["contract"],
            "to": ["customer"],
        },
    },
    "actions": {
        "sign_contract": {
            "name": "签订合同",
            "inputs": {
                "customer_id": {
                    "name": "客户",
                    "objects": ["customer"],
                    "required": True,
                },
            },
            "changes": {
                "create": {
                    "objects": ["contract"],
                    "relations": ["signed_by"],
                },
            },
        },
    },
}


class CompilerTest(unittest.TestCase):
    def test_contract_import_is_composed_without_expanding_source_model(self):
        contract = {
            "schema": "uom.contract.v1",
            "name": "共享测试契约",
            "version": "1.0.0",
            "properties": {
                "shared_code": {"name": "共享编码", "type": "string"},
            },
            "objects": {
                "shared_party": {
                    "name": "共享主体",
                    "description": "跨域主体",
                    "properties": {"shared_code": "required"},
                },
            },
            "relations": {
                "shared_link": {
                    "name": "共享关联",
                    "description": "跨域关联",
                    "from": [],
                    "to": [],
                },
            },
        }
        model = deepcopy(BASE_MODEL)
        model["imports"] = [{
            "path": "shared.yaml",
            "properties": ["shared_code"],
            "objects": ["shared_party"],
            "relations": ["shared_link"],
        }]
        model["actions"] = {}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shared.yaml").write_text(
                yaml.safe_dump(contract, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            (root / "model.yaml").write_text(
                yaml.safe_dump(model, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            source, parsed = load_domain_model(root)
            self.assertNotIn("shared_party", source["objects"])
            self.assertIn("shared_party", parsed.objects)
            public = compile_ontology(parsed).model_dump(by_alias=True)
            editor = workspace_model(
                public,
                {"schema": "uom.action_plans.v1", "actions": {}},
                source,
            )
            updated = update_source_vocabulary(source, editor)
            self.assertNotIn("shared_party", updated["objects"])
            self.assertIn("shared_party", public["objects"])

    def test_contract_import_rejects_property_type_conflict(self):
        contract = {
            "schema": "uom.contract.v1",
            "name": "冲突契约",
            "version": "1.0.0",
            "properties": {"status": {"name": "状态", "type": "number"}},
        }
        model = deepcopy(BASE_MODEL)
        model["imports"] = [{
            "path": "shared.yaml",
            "properties": ["status"],
            "objects": [],
            "relations": [],
        }]
        model["actions"] = {}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shared.yaml").write_text(
                yaml.safe_dump(contract, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            (root / "model.yaml").write_text(
                yaml.safe_dump(model, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "conflicts with imported contract type"):
                load_domain_model(root)

    def test_compiler_expands_uom_model_to_oag_bindings(self):
        ontology = compile_ontology(DomainModel.model_validate(BASE_MODEL))

        self.assertEqual("oag.ontology.v1", ontology.schema_id)
        self.assertEqual("uom_sqlite_graph", ontology.data_sources["graph"].type)
        self.assertEqual("graph", ontology.objects["contract"].binding.source)
        self.assertEqual(
            {"kind": "object", "type": "contract"},
            ontology.objects["contract"].binding.selector,
        )
        self.assertEqual("mutable", ontology.objects["contract"].mutability)

    def test_explicit_external_repository_keeps_selector_and_mapping(self):
        ontology = compile_ontology(DomainModel.model_validate(BASE_MODEL))
        customer = ontology.objects["customer"]

        self.assertEqual("crm", customer.binding.source)
        self.assertEqual(
            {"resource": "accounts"},
            customer.binding.selector,
        )
        self.assertEqual({"id": "account_id"}, customer.binding.mapping)
        self.assertEqual("read_only", customer.mutability)

    def test_unknown_graph_type_is_rejected_by_uom_schema(self):
        invalid = {**BASE_MODEL, "relations": {
            "signed_by": {
                "name": "签约方",
                "from": ["missing"],
                "to": ["customer"],
            },
        }}

        with self.assertRaisesRegex(ValidationError, "unknown object types: missing"):
            DomainModel.model_validate(invalid)

    def test_deprecated_is_not_part_of_the_uom_schema(self):
        mutations = (
            lambda model: model["properties"]["status"].update(deprecated=True),
            lambda model: model["objects"]["contract"].update(deprecated=True),
            lambda model: model["relations"]["signed_by"].update(deprecated=True),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                invalid = deepcopy(BASE_MODEL)
                mutate(invalid)
                with self.assertRaisesRegex(ValidationError, "Extra inputs are not permitted"):
                    DomainModel.model_validate(invalid)

    def test_false_property_default_survives_editor_round_trip(self):
        source = deepcopy(BASE_MODEL)
        source["properties"]["enabled"] = {
            "name": "是否启用",
            "type": "boolean",
            "default": False,
        }
        source["objects"]["contract"]["properties"]["enabled"] = "optional"
        source["actions"] = {}
        public = compile_ontology(DomainModel.model_validate(source)).model_dump(
            by_alias=True,
        )
        editor = workspace_model(
            public,
            {"schema": "uom.action_plans.v1", "actions": {}},
            source,
        )

        updated = update_source_vocabulary(source, editor)

        self.assertIs(updated["properties"]["enabled"]["default"], False)

    def test_unused_source_property_survives_editor_round_trip(self):
        source = deepcopy(BASE_MODEL)
        source["properties"]["future_field"] = {
            "name": "预留属性",
            "type": "string",
        }
        source["actions"] = {}
        public = compile_ontology(DomainModel.model_validate(source)).model_dump(
            by_alias=True,
        )
        editor = workspace_model(
            public,
            {"schema": "uom.action_plans.v1", "actions": {}},
            source,
        )

        updated = update_source_vocabulary(source, editor)

        self.assertIn("future_field", updated["properties"])


if __name__ == "__main__":
    unittest.main()
