#!/usr/bin/env python3
"""Validate the minimal OMS metamodel, ontology, data, and money allocations."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


DEFINITION_ID = re.compile(r"^[a-z][a-z0-9_]*$")
INSTANCE_ID = re.compile(r"^[a-z][a-z0-9_:/.-]*$")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


class ModelValidator:
    def __init__(
        self,
        metamodel: dict[str, Any],
        ontology: dict[str, Any],
        object_data: dict[str, Any],
        relation_data: dict[str, Any],
    ) -> None:
        self.meta = metamodel
        self.ontology = ontology
        self.object_data = object_data
        self.relation_data = relation_data
        self.result = ValidationResult()
        self.concepts = self._mapping(ontology.get("concepts"))
        self.relations = self._mapping(ontology.get("relations"))
        self.functions = self._mapping(ontology.get("functions"))
        self.value_types = set(self._mapping(metamodel.get("value_types")))
        self.object_index: dict[str, dict[str, Any]] = {}
        self.relation_items: list[dict[str, Any]] = []

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else [value]

    def validate(self) -> ValidationResult:
        self._validate_metamodel()
        self._validate_ontology()
        self._validate_data()
        self._validate_money_allocations()
        return self.result

    def _validate_metamodel(self) -> None:
        if self.meta.get("schema") != "oms.metamodel.v1":
            self.result.error("metamodel.schema", "must be oms.metamodel.v1")
        elements = self._mapping(self.meta.get("elements"))
        expected = {"Concept", "Relation", "Property", "Function"}
        if set(elements) != expected:
            self.result.error("metamodel.elements", "must contain only Concept, Relation, Property, Function")
        for name in expected:
            if not self._mapping(elements.get(name)).get("purpose"):
                self.result.error(f"metamodel.elements.{name}", "missing purpose")
        for section in ("value_types", "cardinalities", "data_contract"):
            if section not in self.meta:
                self.result.error("metamodel", f"missing {section}")

    def _validate_ontology(self) -> None:
        if self.ontology.get("schema") != "oms.ontology.v1":
            self.result.error("ontology.schema", "must be oms.ontology.v1")
        if not self.concepts:
            self.result.error("ontology.concepts", "must not be empty")
        if not self.relations:
            self.result.error("ontology.relations", "must not be empty")
        if not self.functions:
            self.result.error("ontology.functions", "must not be empty")

        elements = self._mapping(self.meta.get("elements"))
        concept_contract = self._mapping(elements.get("Concept"))
        for concept_id, concept in self.concepts.items():
            path = f"ontology.concepts.{concept_id}"
            self._validate_definition_id(concept_id, path)
            if not isinstance(concept, dict):
                self.result.error(path, "must be a mapping")
                continue
            self._require_fields(concept, concept_contract.get("required"), path)
            self._validate_property_definitions(concept.get("properties", {}), f"{path}.properties")

        relation_contract = self._mapping(elements.get("Relation"))
        cardinalities = set(self.meta.get("cardinalities") or [])
        default_cardinality = self._mapping(relation_contract.get("defaults")).get(
            "cardinality", "many_to_many"
        )
        for relation_id, relation in self.relations.items():
            path = f"ontology.relations.{relation_id}"
            self._validate_definition_id(relation_id, path)
            if not isinstance(relation, dict):
                self.result.error(path, "must be a mapping")
                continue
            self._require_fields(relation, relation_contract.get("required"), path)
            for endpoint in ("from", "to"):
                refs = self._as_list(relation.get(endpoint))
                if not refs or any(ref not in self.concepts for ref in refs):
                    self.result.error(f"{path}.{endpoint}", "references an unknown concept")
            if relation.get("cardinality", default_cardinality) not in cardinalities:
                self.result.error(f"{path}.cardinality", "unknown cardinality")
            self._validate_property_definitions(relation.get("properties", {}), f"{path}.properties")

        function_contract = self._mapping(elements.get("Function"))
        model_elements = set(self.concepts) | set(self.relations)
        for function_id, function in self.functions.items():
            path = f"ontology.functions.{function_id}"
            self._validate_definition_id(function_id, path)
            if not isinstance(function, dict):
                self.result.error(path, "must be a mapping")
                continue
            self._require_fields(function, function_contract.get("required"), path)
            for input_name, value_type in self._mapping(function.get("inputs")).items():
                if value_type not in self.value_types:
                    self.result.error(f"{path}.inputs.{input_name}", "unknown value type")
            reads = function.get("reads")
            if not isinstance(reads, list) or any(item not in model_elements for item in reads):
                self.result.error(f"{path}.reads", "must contain known concepts or relations")

    def _validate_property_definitions(self, properties: Any, path: str) -> None:
        if not isinstance(properties, dict):
            self.result.error(path, "must be a property-to-type mapping")
            return
        for property_id, value_type in properties.items():
            self._validate_definition_id(property_id, f"{path}.{property_id}")
            if value_type not in self.value_types:
                self.result.error(f"{path}.{property_id}", f"unknown value type {value_type}")

    def _validate_data(self) -> None:
        if self.object_data.get("schema") != "oms.data.objects.v1":
            self.result.error("data.objects.schema", "must be oms.data.objects.v1")
        if self.relation_data.get("schema") != "oms.data.relations.v1":
            self.result.error("data.relations.schema", "must be oms.data.relations.v1")

        object_contract = self._mapping(self._mapping(self.meta.get("data_contract")).get("object"))
        objects = self.object_data.get("objects")
        if not isinstance(objects, list):
            self.result.error("data.objects", "must be a list")
            objects = []
        for index, item in enumerate(objects):
            path = f"data.objects[{index}]"
            if not isinstance(item, dict):
                self.result.error(path, "must be a mapping")
                continue
            self._require_fields(item, object_contract.get("required"), path)
            object_id = item.get("id")
            self._validate_instance_id(object_id, f"{path}.id")
            if object_id in self.object_index:
                self.result.error(f"{path}.id", "duplicate object ID")
            elif isinstance(object_id, str):
                self.object_index[object_id] = item
            concept_id = item.get("type")
            if concept_id not in self.concepts:
                self.result.error(f"{path}.type", "unknown concept")
                continue
            properties = self._mapping(self._mapping(self.concepts[concept_id]).get("properties"))
            self._validate_facts(item.get("facts", {}), properties, f"{path}.facts")
            self._validate_source_refs(item.get("source_refs"), f"{path}.source_refs")

        relation_contract = self._mapping(self._mapping(self.meta.get("data_contract")).get("relation"))
        relations = self.relation_data.get("relations")
        if not isinstance(relations, list):
            self.result.error("data.relations", "must be a list")
            relations = []
        relation_ids: set[str] = set()
        for index, item in enumerate(relations):
            path = f"data.relations[{index}]"
            if not isinstance(item, dict):
                self.result.error(path, "must be a mapping")
                continue
            self.relation_items.append(item)
            self._require_fields(item, relation_contract.get("required"), path)
            relation_id = item.get("id")
            self._validate_instance_id(relation_id, f"{path}.id")
            if relation_id in relation_ids:
                self.result.error(f"{path}.id", "duplicate relation ID")
            elif isinstance(relation_id, str):
                relation_ids.add(relation_id)
            definition = self._mapping(self.relations.get(item.get("type")))
            if not definition:
                self.result.error(f"{path}.type", "unknown relation type")
                continue
            source = self.object_index.get(item.get("from"))
            target = self.object_index.get(item.get("to"))
            if source is None:
                self.result.error(f"{path}.from", "unknown object")
            elif source.get("type") not in self._as_list(definition.get("from")):
                self.result.error(f"{path}.from", "object type is not allowed by relation")
            if target is None:
                self.result.error(f"{path}.to", "unknown object")
            elif target.get("type") not in self._as_list(definition.get("to")):
                self.result.error(f"{path}.to", "object type is not allowed by relation")
            properties = self._mapping(definition.get("properties"))
            self._validate_facts(item.get("facts", {}), properties, f"{path}.facts")
            self._validate_source_refs(item.get("source_refs"), f"{path}.source_refs")

    def _validate_source_refs(self, value: Any, path: str) -> None:
        if value is None:
            return
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            self.result.error(path, "must be a list of non-empty strings")

    def _validate_facts(self, facts: Any, definitions: dict[str, Any], path: str) -> None:
        if not isinstance(facts, dict):
            self.result.error(path, "must be a mapping")
            return
        for property_id, value in facts.items():
            value_type = definitions.get(property_id)
            if value_type is None:
                self.result.error(f"{path}.{property_id}", "property is not declared")
            else:
                self._validate_value(value, value_type, f"{path}.{property_id}")

    def _validate_value(self, value: Any, value_type: str, path: str) -> None:
        if value_type == "string" and not isinstance(value, str):
            self.result.error(path, "must be a string")
        elif value_type == "number" and not self._is_number(value):
            self.result.error(path, "must be a number")
        elif value_type == "date":
            if not isinstance(value, str):
                self.result.error(path, "must be an ISO date")
            else:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    self.result.error(path, "must be an ISO date")
        elif value_type == "period" and (
            not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value)
        ):
            self.result.error(path, "must be YYYY-MM")
        elif value_type == "money":
            if not isinstance(value, dict) or set(value) != {"amount", "currency"}:
                self.result.error(path, "must contain amount and currency")
            elif not self._is_number(value["amount"]):
                self.result.error(f"{path}.amount", "must be a number")
            elif not isinstance(value["currency"], str) or not re.fullmatch(r"[A-Z]{3}", value["currency"]):
                self.result.error(f"{path}.currency", "must be an ISO currency code")

    def _validate_money_allocations(self) -> None:
        groups = [
            ("expenditure disposition", {"expenditure_recognized_as_cost": "recognized_amount", "expenditure_capitalized_as_asset": "capitalized_amount"}, "from", set()),
            ("cost disposition", {"cost_attributed_to_revenue": "allocated_amount", "cost_absorbed_by_enterprise": "absorbed_amount"}, "from", {"cost_attributed_to_revenue"}),
            ("revenue receivable", {"revenue_creates_receivable": "linked_amount"}, "from", set()),
            ("receivable creation", {"revenue_creates_receivable": "linked_amount"}, "to", set()),
            ("receipt settlement", {"cash_receipt_settles_receivable": "settled_amount"}, "from", set()),
            ("receivable settlement", {"cash_receipt_settles_receivable": "settled_amount"}, "to", set()),
            ("expenditure payable", {"expenditure_creates_payable": "linked_amount"}, "from", set()),
            ("payable creation", {"expenditure_creates_payable": "linked_amount"}, "to", set()),
            ("payment settlement", {"cash_payment_settles_payable": "settled_amount"}, "from", set()),
            ("payable settlement", {"cash_payment_settles_payable": "settled_amount"}, "to", set()),
        ]
        for name, relation_properties, endpoint, confirmed_only in groups:
            self._validate_amount_group(name, relation_properties, endpoint, confirmed_only)

    def _validate_amount_group(
        self,
        name: str,
        relation_properties: dict[str, str],
        endpoint: str,
        confirmed_only: set[str],
    ) -> None:
        totals: dict[tuple[str, str], float] = {}
        for item in self.relation_items:
            relation_type = item.get("type")
            property_name = relation_properties.get(relation_type)
            if property_name is None:
                continue
            if relation_type in confirmed_only and self._mapping(item.get("facts")).get("status") != "confirmed":
                continue
            money = self._mapping(self._mapping(item.get("facts")).get(property_name))
            amount = money.get("amount")
            currency = money.get("currency")
            object_id = item.get(endpoint)
            if not self._is_number(amount) or not isinstance(currency, str) or not isinstance(object_id, str):
                continue
            key = (object_id, currency)
            totals[key] = totals.get(key, 0.0) + float(amount)

        for (object_id, currency), total in totals.items():
            item = self.object_index.get(object_id)
            object_money = self._mapping(self._mapping(item).get("facts")).get("amount")
            object_money = self._mapping(object_money)
            object_amount = object_money.get("amount")
            object_currency = object_money.get("currency")
            if not self._is_number(object_amount):
                continue
            if object_currency != currency:
                self.result.error(f"money.{name}.{object_id}", "currency differs from object amount")
            elif total > float(object_amount) + 1e-9:
                self.result.error(
                    f"money.{name}.{object_id}",
                    f"allocated {total:g} exceeds object amount {float(object_amount):g}",
                )

    def _require_fields(self, value: dict[str, Any], required: Any, path: str) -> None:
        for field_name in required or []:
            if field_name not in value:
                self.result.error(path, f"missing required field {field_name}")

    def _validate_definition_id(self, value: Any, path: str) -> None:
        if not isinstance(value, str) or not DEFINITION_ID.fullmatch(value):
            self.result.error(path, "invalid definition ID")

    def _validate_instance_id(self, value: Any, path: str) -> None:
        if not isinstance(value, str) or not INSTANCE_ID.fullmatch(value):
            self.result.error(path, "invalid instance ID")

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_model(root: Path) -> ValidationResult:
    return ModelValidator(
        load_yaml(root / "metamodel.yaml"),
        load_yaml(root / "ontology.yaml"),
        load_yaml(root / "data" / "objects.yaml"),
        load_yaml(root / "data" / "relations.yaml"),
    ).validate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = validate_model(args.root.resolve())
    for error in result.errors:
        print(f"ERROR: {error}")
    if result.valid:
        print("OMS model is valid")
        return 0
    print(f"OMS model validation failed with {len(result.errors)} error(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
