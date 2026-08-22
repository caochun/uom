from __future__ import annotations

import unittest
from copy import deepcopy

from pydantic import ValidationError

from uom.compiler import compile_ontology
from uom.model import update_source_vocabulary, workspace_model
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
