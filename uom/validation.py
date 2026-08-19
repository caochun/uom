#!/usr/bin/env python3
"""Validate a UOM core ontology, domain model and object-relation data."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from oag.ontology.schema import FunctionDef, Ontology
from pydantic import ValidationError

from uom.composition import (
    compose_ontology_payload,
    domain_function_implementations,
)


TYPE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
INSTANCE_ID = re.compile(r"^[a-z][a-z0-9_:/.-]*$")
VALUE_TYPES = {"string", "number", "date", "datetime", "period", "money", "boolean", "json"}
CORE_ONTOLOGY_PATH = Path(__file__).with_name("ontology.yaml")


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


def load_data(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    database_path = root / "data" / "graph.db"
    if not database_path.exists():
        raise FileNotFoundError(
            f"UOM database not found: {database_path}"
        )

    connection = sqlite3.connect(database_path)
    try:
        objects = [
            json.loads(row[0])
            for row in connection.execute("SELECT payload FROM objects ORDER BY rowid")
        ]
        relations = [
            json.loads(row[0])
            for row in connection.execute("SELECT payload FROM relations ORDER BY rowid")
        ]
    finally:
        connection.close()
    return (
        {"schema": "uom.data.objects.v1", "objects": objects},
        {"schema": "uom.data.relations.v1", "relations": relations},
    )


class ModelValidator:
    def __init__(
        self,
        ontology: dict[str, Any],
        object_data: dict[str, Any],
        relation_data: dict[str, Any],
        domain_model: dict[str, Any] | None = None,
    ) -> None:
        self.ontology = ontology
        self.object_data = object_data
        self.relation_data = relation_data
        self.domain_model = domain_model
        self.result = ValidationResult()
        self.object_definitions = self._mapping(ontology.get("objects"))
        model = self._mapping(domain_model)
        self.property_definitions = self._mapping(model.get("property_definitions"))
        self.object_type_definitions = self._mapping(model.get("object_types"))
        self.relation_type_definitions = self._mapping(model.get("relation_types"))
        self.action_definitions = self._mapping(model.get("actions"))
        self.object_index: dict[str, dict[str, Any]] = {}
        self.relation_items: list[dict[str, Any]] = []

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def validate(self) -> ValidationResult:
        self._validate_ontology()
        self._validate_data()
        if self.domain_model is not None:
            self._validate_domain_model()
            self._validate_data_against_domain_model()
        self._validate_semantics()
        return self.result

    def validate_changes(
        self,
        object_ids: set[str],
        relation_ids: set[str],
        *,
        check_acyclic_types: set[str] | None = None,
    ) -> ValidationResult:
        """Validate records and endpoints affected by a data-only ChangeSet.

        The ontology and domain model are validated when loaded and whenever the
        model changes. Routine writes therefore need only re-check their records,
        endpoint contracts and any acyclic relation types they add to.
        """
        objects = self.object_data.get("objects")
        relations = self.relation_data.get("relations")
        if not isinstance(objects, list) or not isinstance(relations, list):
            return self.validate()
        self.object_index = {
            item.get("id"): item
            for item in objects
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        relation_index = {
            item.get("id"): item
            for item in relations
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        object_contract = self._record_contract("Object")
        for record_id in sorted(object_ids):
            item = self.object_index.get(record_id)
            if not isinstance(item, dict):
                self.result.error(f"data.objects.{record_id}", "unknown object")
                continue
            path = f"data.objects.{record_id}"
            self._validate_record_fields(item, object_contract, path)
            self._validate_instance_id(item.get("id"), f"{path}.id")
            self._validate_type_id(item.get("type"), f"{path}.type")
            self._validate_properties(item.get("properties", {}), f"{path}.properties")
            self._validate_tags(item.get("tags"), f"{path}.tags")
            self._validate_source_refs(item.get("source_refs"), f"{path}.source_refs")
            self._validate_lifecycle(item.get("lifecycle"), f"{path}.lifecycle")
            definition = self._mapping(self.object_type_definitions.get(item.get("type")))
            self._validate_typed_properties(
                item.get("properties", {}), definition, f"{path}.properties"
            )

        relation_contract = self._record_contract("Relation")
        for record_id in sorted(relation_ids):
            item = relation_index.get(record_id)
            if not isinstance(item, dict):
                self.result.error(f"data.relations.{record_id}", "unknown relation")
                continue
            path = f"data.relations.{record_id}"
            self._validate_record_fields(item, relation_contract, path)
            self._validate_instance_id(item.get("id"), f"{path}.id")
            self._validate_type_id(item.get("type"), f"{path}.type")
            source = self.object_index.get(item.get("from"))
            target = self.object_index.get(item.get("to"))
            if source is None:
                self.result.error(f"{path}.from", "unknown object")
            if target is None:
                self.result.error(f"{path}.to", "unknown object")
            if item.get("from") == item.get("to"):
                self.result.error(path, "self-relations are not allowed")
            self._validate_properties(item.get("properties", {}), f"{path}.properties")
            self._validate_tags(item.get("tags"), f"{path}.tags")
            self._validate_source_refs(item.get("source_refs"), f"{path}.source_refs")
            self._validate_lifecycle(item.get("lifecycle"), f"{path}.lifecycle")
            definition = self._mapping(self.relation_type_definitions.get(item.get("type")))
            if source is not None and definition.get("from_types"):
                if source.get("type") not in definition["from_types"]:
                    self.result.error(f"{path}.from", "object type does not match domain model")
            if target is not None and definition.get("to_types"):
                if target.get("type") not in definition["to_types"]:
                    self.result.error(f"{path}.to", "object type does not match domain model")
            self._validate_typed_properties(
                item.get("properties", {}), definition, f"{path}.properties"
            )

        acyclic_types = check_acyclic_types or set()
        if acyclic_types:
            self.relation_items = relations
            for relation_type in sorted(acyclic_types):
                definition = self._mapping(self.relation_type_definitions.get(relation_type))
                if definition.get("acyclic") is True:
                    self._validate_acyclic(relation_type)
        return self.result

    def _validate_domain_model(self) -> None:
        model = self.domain_model or {}
        if model.get("schema") != "uom.domain_model.v1":
            self.result.error("model.schema", "must be uom.domain_model.v1")
        metadata = self._mapping(model.get("model"))
        if not metadata.get("name") or not metadata.get("version"):
            self.result.error("model.model", "must contain name and version")

        if not isinstance(model.get("property_definitions"), dict):
            self.result.error("model.property_definitions", "must be a mapping")
        for property_id, definition in self.property_definitions.items():
            path = f"model.property_definitions.{property_id}"
            self._validate_type_id(property_id, path)
            if not isinstance(definition, dict):
                self.result.error(path, "must be a mapping")
                continue
            if not definition.get("name"):
                self.result.error(path, "must contain name")
            if definition.get("type") not in VALUE_TYPES:
                self.result.error(f"{path}.type", f"must be one of {', '.join(sorted(VALUE_TYPES))}")
            self._validate_evolution_metadata(definition, path)

        for kind in ("object", "relation"):
            section_name = f"{kind}_types"
            section = model.get(section_name)
            if not isinstance(section, dict):
                self.result.error(f"model.{section_name}", "must be a mapping")
                continue
            for type_id, definition in section.items():
                path = f"model.{section_name}.{type_id}"
                self._validate_type_id(type_id, path)
                if not isinstance(definition, dict):
                    self.result.error(path, "must be a mapping")
                    continue
                if not definition.get("name") or not definition.get("description"):
                    self.result.error(path, "must contain name and description")
                self._validate_evolution_metadata(definition, path)

                properties = definition.get("properties", {})
                if not isinstance(properties, dict):
                    self.result.error(f"{path}.properties", "must be a mapping")
                else:
                    for property_id, usage in properties.items():
                        property_path = f"{path}.properties.{property_id}"
                        self._validate_type_id(property_id, property_path)
                        if property_id not in self.property_definitions:
                            self.result.error(property_path, "references an unknown property definition")
                        if not isinstance(usage, dict):
                            self.result.error(property_path, "must be a mapping")
                            continue
                        if set(usage) - {"required"}:
                            self.result.error(property_path, "only required is supported")
                        if "required" in usage and not isinstance(usage["required"], bool):
                            self.result.error(f"{property_path}.required", "must be a boolean")

                for field_name in (["from_types", "to_types"] if kind == "relation" else []):
                    value = definition.get(field_name, [])
                    if not isinstance(value, list):
                        self.result.error(f"{path}.{field_name}", "must be a list")
                        continue
                    for index, item in enumerate(value):
                        self._validate_type_id(item, f"{path}.{field_name}[{index}]")
                if kind == "relation" and "acyclic" in definition and not isinstance(definition["acyclic"], bool):
                    self.result.error(f"{path}.acyclic", "must be a boolean")

        self._validate_runtime(model)
        self._validate_actions(model.get("actions"))

    def _validate_evolution_metadata(self, definition: dict[str, Any], path: str) -> None:
        if "deprecated" in definition and not isinstance(definition["deprecated"], bool):
            self.result.error(f"{path}.deprecated", "must be a boolean")
        aliases = definition.get("aliases")
        if aliases is None:
            return
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            self.result.error(f"{path}.aliases", "must be a list of non-empty strings")
        elif len(set(aliases)) != len(aliases):
            self.result.error(f"{path}.aliases", "must not contain duplicates")

    def _validate_runtime(self, model: dict[str, Any]) -> None:
        try:
            effective = compose_ontology_payload(self.ontology, model)
            implementations = domain_function_implementations(model)
            Ontology.model_validate(effective)
        except (TypeError, ValueError, ValidationError) as exc:
            self.result.error("model.runtime", str(exc))
            return

        functions = self._mapping(self._mapping(model.get("runtime")).get("functions"))
        allowed = set(FunctionDef.model_fields) | {"implementation"}
        for name, definition in functions.items():
            path = f"model.runtime.functions.{name}"
            self._validate_type_id(name, path)
            if not isinstance(definition, dict):
                continue
            unknown = set(definition) - allowed
            if unknown:
                self.result.error(
                    path,
                    f"contains unknown fields: {', '.join(sorted(unknown))}",
                )
            if name not in implementations:
                self.result.error(
                    f"{path}.implementation",
                    "must be module:function",
                )

    def _validate_actions(self, actions: Any) -> None:
        if not isinstance(actions, dict):
            self.result.error("model.actions", "must be a mapping")
            return
        for action_id, definition in actions.items():
            path = f"model.actions.{action_id}"
            self._validate_type_id(action_id, path)
            if not isinstance(definition, dict):
                self.result.error(path, "must be a mapping")
                continue
            allowed = {
                "name", "description", "icon", "handler", "confirmation",
                "available_on", "context_input", "requires", "inputs", "effects",
            }
            unknown = set(definition) - allowed
            if unknown:
                self.result.error(path, f"contains unknown fields: {', '.join(sorted(unknown))}")
            if not definition.get("name") or not definition.get("description"):
                self.result.error(path, "must contain name and description")
            if definition.get("handler") != "changeset":
                self.result.error(f"{path}.handler", "must be changeset")
            if "confirmation" in definition and not isinstance(definition["confirmation"], str):
                self.result.error(f"{path}.confirmation", "must be a string")
            if "icon" in definition and not isinstance(definition["icon"], str):
                self.result.error(f"{path}.icon", "must be a string")

            available_on = definition.get("available_on")
            if available_on is not None:
                if not isinstance(available_on, list) or not available_on:
                    self.result.error(f"{path}.available_on", "must be a non-empty list")
                else:
                    for index, type_id in enumerate(available_on):
                        item_path = f"{path}.available_on[{index}]"
                        if type_id == "*":
                            continue
                        self._validate_type_id(type_id, item_path)
                        if type_id not in self.object_type_definitions:
                            self.result.error(item_path, "references an unknown object type")
                    if "*" in available_on and available_on != ["*"]:
                        self.result.error(f"{path}.available_on", "* must be used alone")

            inputs = definition.get("inputs")
            if not isinstance(inputs, dict):
                self.result.error(f"{path}.inputs", "must be a mapping")
                inputs = {}
            for input_id, input_definition in inputs.items():
                self._validate_action_input(input_id, input_definition, f"{path}.inputs.{input_id}")

            context_input = definition.get("context_input")
            if context_input is not None:
                self._validate_type_id(context_input, f"{path}.context_input")
                context_definition = self._mapping(inputs.get(context_input))
                if context_input not in inputs:
                    self.result.error(f"{path}.context_input", "references an unknown input")
                elif "object_types" not in context_definition:
                    self.result.error(f"{path}.context_input", "must reference an object input")
                elif context_definition.get("required") is not True:
                    self.result.error(f"{path}.context_input", "must reference a required input")
                elif available_on is None:
                    self.result.error(f"{path}.context_input", "requires available_on")
                elif "*" not in available_on:
                    input_types = set(context_definition.get("object_types", []))
                    available_types = set(available_on)
                    if input_types != available_types:
                        self.result.error(
                            f"{path}.context_input",
                            "object_types must match available_on",
                        )

            self._validate_action_requirements(
                definition.get("requires", []),
                inputs,
                available_on is not None and context_input is None,
                f"{path}.requires",
            )

            effects = definition.get("effects")
            if not isinstance(effects, list) or not effects:
                self.result.error(f"{path}.effects", "must be a non-empty list")
                continue
            created_refs: set[str] = set()
            for index, effect in enumerate(effects):
                effect_path = f"{path}.effects[{index}]"
                if not isinstance(effect, dict) or len(effect) != 1:
                    self.result.error(effect_path, "must contain one effect")
                    continue
                effect_kind, effect_definition = next(iter(effect.items()))
                if effect_kind not in {"create_object", "update_object", "create_relation"}:
                    self.result.error(effect_path, "only create_object and create_relation are supported; update_object is also supported")
                    continue
                if not isinstance(effect_definition, dict):
                    self.result.error(f"{effect_path}.{effect_kind}", "must be a mapping")
                    continue
                if effect_kind == "create_object":
                    ref = effect_definition.get("ref")
                    self._validate_type_id(ref, f"{effect_path}.create_object.ref")
                    if isinstance(ref, str):
                        if ref in created_refs:
                            self.result.error(f"{effect_path}.create_object.ref", "must be unique")
                    object_type = effect_definition.get("type")
                    self._validate_type_id(object_type, f"{effect_path}.create_object.type")
                    if object_type not in self.object_type_definitions:
                        self.result.error(f"{effect_path}.create_object.type", "references an unknown object type")
                    self._validate_action_effect(
                        effect_definition,
                        {"ref", "type", "name", "properties", "tags"},
                        inputs,
                        created_refs,
                        available_on is not None and context_input is None,
                        effect_path,
                        self._mapping(self.object_type_definitions.get(object_type)),
                    )
                    if isinstance(ref, str):
                        created_refs.add(ref)
                elif effect_kind == "update_object":
                    self._validate_action_effect(
                        effect_definition,
                        {"id", "changes"},
                        inputs,
                        created_refs,
                        available_on is not None and context_input is None,
                        effect_path,
                        {"properties": {key: {} for key in self.property_definitions}},
                    )
                else:
                    relation_type = effect_definition.get("type")
                    self._validate_type_id(relation_type, f"{effect_path}.create_relation.type")
                    if relation_type not in self.relation_type_definitions:
                        self.result.error(f"{effect_path}.create_relation.type", "references an unknown relation type")
                    self._validate_action_effect(
                        effect_definition,
                        {"type", "from", "to", "properties", "tags"},
                        inputs,
                        created_refs,
                        available_on is not None and context_input is None,
                        effect_path,
                        self._mapping(self.relation_type_definitions.get(relation_type)),
                    )

    def _validate_action_requirements(
        self,
        requirements: Any,
        inputs: dict[str, Any],
        has_context: bool,
        path: str,
    ) -> None:
        if not isinstance(requirements, list):
            self.result.error(path, "must be a list")
            return
        for index, requirement in enumerate(requirements):
            requirement_path = f"{path}[{index}]"
            if not isinstance(requirement, dict) or len(requirement) != 1:
                self.result.error(requirement_path, "must contain one condition")
                continue
            kind, condition = next(iter(requirement.items()))
            if kind not in {"object_status", "related_object"}:
                self.result.error(requirement_path, "only object_status and related_object are supported")
                continue
            if not isinstance(condition, dict):
                self.result.error(f"{requirement_path}.{kind}", "must be a mapping")
                continue
            condition_path = f"{requirement_path}.{kind}"
            if kind == "object_status":
                allowed = {"object", "in", "message"}
                required = {"object", "in"}
            else:
                allowed = {
                    "from", "to", "from_type", "to_type", "relation", "role",
                    "properties", "message",
                }
                required = {"relation"}
            unknown = set(condition) - allowed
            if unknown:
                self.result.error(condition_path, f"contains unknown fields: {', '.join(sorted(unknown))}")
            for field in required:
                if field not in condition:
                    self.result.error(condition_path, f"missing required field {field}")
            if "message" in condition and not isinstance(condition["message"], str):
                self.result.error(f"{condition_path}.message", "must be a string")
            if kind == "object_status":
                self._validate_action_value(
                    condition.get("object"), inputs, set(), has_context,
                    f"{condition_path}.object",
                )
                statuses = condition.get("in")
                if not isinstance(statuses, list) or not statuses or not all(isinstance(item, str) and item for item in statuses):
                    self.result.error(f"{condition_path}.in", "must be a non-empty string list")
                continue

            relation_type = condition.get("relation")
            self._validate_type_id(relation_type, f"{condition_path}.relation")
            if relation_type not in self.relation_type_definitions:
                self.result.error(f"{condition_path}.relation", "references an unknown relation type")
            if "from" not in condition and "to" not in condition:
                self.result.error(condition_path, "must contain from or to")
            for side in ("from", "to"):
                if side in condition:
                    self._validate_action_value(
                        condition[side], inputs, set(), has_context,
                        f"{condition_path}.{side}",
                    )
            for field in ("from_type", "to_type"):
                if field in condition:
                    type_id = condition[field]
                    self._validate_type_id(type_id, f"{condition_path}.{field}")
                    if type_id not in self.object_type_definitions:
                        self.result.error(f"{condition_path}.{field}", "references an unknown object type")
            properties = condition.get("properties", {})
            if not isinstance(properties, dict):
                self.result.error(f"{condition_path}.properties", "must be a mapping")
            elif properties and "from_type" not in condition:
                self.result.error(
                    f"{condition_path}.properties",
                    "requires from_type",
                )
            elif "from_type" in condition:
                source_definition = self._mapping(
                    self.object_type_definitions.get(condition["from_type"])
                )
                allowed_properties = self._mapping(source_definition.get("properties"))
                for property_id in properties:
                    if property_id not in allowed_properties:
                        self.result.error(
                            f"{condition_path}.properties.{property_id}",
                            "is not defined for from_type",
                        )

    def _validate_action_input(self, input_id: Any, definition: Any, path: str) -> None:
        self._validate_type_id(input_id, path)
        if not isinstance(definition, dict):
            self.result.error(path, "must be a mapping")
            return
        allowed = {"name", "required", "property", "type", "object_types", "default"}
        unknown = set(definition) - allowed
        if unknown:
            self.result.error(path, f"contains unknown fields: {', '.join(sorted(unknown))}")
        if not definition.get("name"):
            self.result.error(path, "must contain name")
        if "required" not in definition or not isinstance(definition.get("required"), bool):
            self.result.error(f"{path}.required", "must be a boolean")
        source_fields = [key for key in ("property", "type", "object_types") if key in definition]
        if len(source_fields) != 1:
            self.result.error(path, "must contain exactly one of property, type or object_types")
            return
        if "property" in definition:
            property_id = definition.get("property")
            self._validate_type_id(property_id, f"{path}.property")
            if property_id not in self.property_definitions:
                self.result.error(f"{path}.property", "references an unknown property definition")
            value_type = self._mapping(self.property_definitions.get(property_id)).get("type")
        elif "type" in definition:
            value_type = definition.get("type")
            if value_type not in VALUE_TYPES:
                self.result.error(f"{path}.type", f"must be one of {', '.join(sorted(VALUE_TYPES))}")
        else:
            value_type = None
            object_types = definition.get("object_types")
            if not isinstance(object_types, list) or not object_types:
                self.result.error(f"{path}.object_types", "must be a non-empty list")
            else:
                for index, type_id in enumerate(object_types):
                    item_path = f"{path}.object_types[{index}]"
                    self._validate_type_id(type_id, item_path)
                    if type_id not in self.object_type_definitions:
                        self.result.error(item_path, "references an unknown object type")
        if "default" in definition and value_type in VALUE_TYPES:
            self._validate_value(definition["default"], value_type, f"{path}.default")

    def _validate_action_effect(
        self,
        definition: dict[str, Any],
        allowed: set[str],
        inputs: dict[str, Any],
        created_refs: set[str],
        has_context: bool,
        path: str,
        type_definition: dict[str, Any],
    ) -> None:
        unknown = set(definition) - allowed
        if unknown:
            self.result.error(path, f"contains unknown fields: {', '.join(sorted(unknown))}")
        if "id" in allowed:
            required_fields = {"id", "changes"}
        else:
            required_fields = {"type", "name"} if "name" in allowed else {"type", "from", "to"}
        for required in required_fields:
            if required not in definition:
                self.result.error(path, f"missing required field {required}")
        properties = definition.get("properties", {})
        if not isinstance(properties, dict):
            self.result.error(f"{path}.properties", "must be a mapping")
        else:
            allowed_properties = self._mapping(type_definition.get("properties"))
            for property_id in properties:
                if property_id not in allowed_properties:
                    self.result.error(f"{path}.properties.{property_id}", "is not defined for this type")
        for field, value in definition.items():
            if field in {"ref", "type"}:
                continue
            self._validate_action_value(value, inputs, created_refs, has_context, f"{path}.{field}")

    def _validate_action_value(
        self,
        value: Any,
        inputs: dict[str, Any],
        created_refs: set[str],
        has_context: bool,
        path: str,
    ) -> None:
        if isinstance(value, str) and value.startswith("$"):
            if value == "$context":
                if not has_context:
                    self.result.error(
                        path,
                        "$context requires available_on without context_input; "
                        "use the explicit context input instead",
                    )
                return
            if value.startswith("$input."):
                if value[7:] not in inputs:
                    self.result.error(path, "references an unknown input")
                return
            if value[1:] not in created_refs:
                self.result.error(path, "references an unknown or future object ref")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                self._validate_action_value(item, inputs, created_refs, has_context, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._validate_action_value(item, inputs, created_refs, has_context, f"{path}[{index}]")

    def _validate_data_against_domain_model(self) -> None:
        for index, item in enumerate(self.object_index.values()):
            definition = self._mapping(self.object_type_definitions.get(item.get("type")))
            self._validate_typed_properties(
                item.get("properties", {}),
                definition,
                f"data.objects[{index}].properties",
            )

        for index, relation in enumerate(self.relation_items):
            definition = self._mapping(self.relation_type_definitions.get(relation.get("type")))
            path = f"data.relations[{index}]"
            source = self.object_index.get(relation.get("from"), {})
            target = self.object_index.get(relation.get("to"), {})
            from_types = definition.get("from_types", [])
            to_types = definition.get("to_types", [])
            if from_types and source.get("type") not in from_types:
                self.result.error(f"{path}.from", "object type does not match domain model")
            if to_types and target.get("type") not in to_types:
                self.result.error(f"{path}.to", "object type does not match domain model")
            self._validate_typed_properties(
                relation.get("properties", {}),
                definition,
                f"{path}.properties",
            )

    def _validate_ontology(self) -> None:
        if self.ontology.get("schema") != "uom.ontology.v1":
            self.result.error("ontology.schema", "must be uom.ontology.v1")
        if not self.ontology.get("name") or not self.ontology.get("description"):
            self.result.error("ontology", "must contain OAG name and description")

        expected_objects = {
            "Object": {
                "id": ("str", True),
                "type": ("str", True),
                "name": ("str", True),
                "properties": ("dict", False),
                "tags": ("list", False),
                "source_refs": ("list", False),
                "lifecycle": ("dict", False),
            },
            "Relation": {
                "id": ("str", True),
                "type": ("str", True),
                "from": ("str", True),
                "to": ("str", True),
                "properties": ("dict", False),
                "tags": ("list", False),
                "source_refs": ("list", False),
                "lifecycle": ("dict", False),
            },
        }
        if set(self.object_definitions) != set(expected_objects):
            self.result.error("ontology.objects", "must contain only Object and Relation")
        for object_name, expected_properties in expected_objects.items():
            definition = self._mapping(self.object_definitions.get(object_name))
            path = f"ontology.objects.{object_name}"
            if not definition.get("display_name") or not definition.get("description"):
                self.result.error(path, "must contain display_name and description")
            if definition.get("type_policy") != "open":
                self.result.error(f"{path}.type_policy", "must be open")
            source = self._mapping(definition.get("source"))
            source_config = self._mapping(source.get("config"))
            expected_kind = "object" if object_name == "Object" else "relation"
            if (
                source.get("type") != "uom_sqlite"
                or source.get("id_field") != "id"
                or source_config.get("database") != "data/graph.db"
                or source_config.get("kind") != expected_kind
            ):
                self.result.error(
                    f"{path}.source",
                    "must declare the matching UOM SQLite adapter source",
                )
            properties = self._mapping(definition.get("properties"))
            if set(properties) != set(expected_properties):
                self.result.error(
                    f"{path}.properties",
                    "does not match the UOM record contract",
                )
            for property_name, (value_type, required) in expected_properties.items():
                property_definition = self._mapping(properties.get(property_name))
                property_path = f"{path}.properties.{property_name}"
                if property_definition.get("type") != value_type:
                    self.result.error(property_path, f"type must be {value_type}")
                if bool(property_definition.get("required", False)) != required:
                    self.result.error(property_path, f"required must be {str(required).lower()}")

    def _validate_data(self) -> None:
        if self.object_data.get("schema") != "uom.data.objects.v1":
            self.result.error("data.objects.schema", "must be uom.data.objects.v1")
        if self.relation_data.get("schema") != "uom.data.relations.v1":
            self.result.error("data.relations.schema", "must be uom.data.relations.v1")

        object_contract = self._record_contract("Object")
        objects = self.object_data.get("objects")
        if not isinstance(objects, list):
            self.result.error("data.objects", "must be a list")
            objects = []
        for index, item in enumerate(objects):
            path = f"data.objects[{index}]"
            if not isinstance(item, dict):
                self.result.error(path, "must be a mapping")
                continue
            self._validate_record_fields(item, object_contract, path)
            object_id = item.get("id")
            self._validate_instance_id(object_id, f"{path}.id")
            self._validate_type_id(item.get("type"), f"{path}.type")
            if object_id in self.object_index:
                self.result.error(f"{path}.id", "duplicate object ID")
            elif isinstance(object_id, str):
                self.object_index[object_id] = item
            self._validate_properties(item.get("properties", {}), f"{path}.properties")
            self._validate_tags(item.get("tags"), f"{path}.tags")
            self._validate_source_refs(item.get("source_refs"), f"{path}.source_refs")
            self._validate_lifecycle(item.get("lifecycle"), f"{path}.lifecycle")

        relation_contract = self._record_contract("Relation")
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
            self._validate_record_fields(item, relation_contract, path)
            relation_id = item.get("id")
            self._validate_instance_id(relation_id, f"{path}.id")
            self._validate_type_id(item.get("type"), f"{path}.type")
            if relation_id in relation_ids:
                self.result.error(f"{path}.id", "duplicate relation ID")
            elif isinstance(relation_id, str):
                relation_ids.add(relation_id)
            source = self.object_index.get(item.get("from"))
            target = self.object_index.get(item.get("to"))
            if source is None:
                self.result.error(f"{path}.from", "unknown object")
            if target is None:
                self.result.error(f"{path}.to", "unknown object")
            if item.get("from") == item.get("to"):
                self.result.error(path, "self-relations are not allowed")
            self._validate_properties(item.get("properties", {}), f"{path}.properties")
            self._validate_tags(item.get("tags"), f"{path}.tags")
            self._validate_source_refs(item.get("source_refs"), f"{path}.source_refs")
            self._validate_lifecycle(item.get("lifecycle"), f"{path}.lifecycle")

    def _validate_lifecycle(self, value: Any, path: str) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            self.result.error(path, "must be a mapping")
            return
        allowed = {"revision", "created_at", "updated_at", "retired_at"}
        unknown = set(value) - allowed
        if unknown:
            self.result.error(path, f"contains unknown fields: {', '.join(sorted(unknown))}")
        revision = value.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            self.result.error(f"{path}.revision", "must be a positive integer")
        for field in ("created_at", "updated_at", "retired_at"):
            timestamp = value.get(field)
            if timestamp is None and field == "retired_at":
                continue
            try:
                if not isinstance(timestamp, str):
                    raise ValueError
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                self.result.error(f"{path}.{field}", "must be an ISO datetime")

    def _validate_record_fields(
        self,
        item: dict[str, Any],
        contract: dict[str, Any],
        path: str,
    ) -> None:
        required = contract.get("required", [])
        optional = contract.get("optional", [])
        for field_name in required:
            if field_name not in item:
                self.result.error(path, f"missing required field {field_name}")
        allowed = set(required) | set(optional)
        unknown = set(item) - allowed
        if unknown:
            self.result.error(path, f"contains unknown fields: {', '.join(sorted(unknown))}")

    def _record_contract(self, object_name: str) -> dict[str, list[str]]:
        definition = self._mapping(self.object_definitions.get(object_name))
        properties = self._mapping(definition.get("properties"))
        required = [
            name
            for name, property_definition in properties.items()
            if self._mapping(property_definition).get("required") is True
        ]
        return {
            "required": required,
            "optional": [name for name in properties if name not in required],
        }

    def _validate_properties(self, properties: Any, path: str) -> None:
        if not isinstance(properties, dict):
            self.result.error(path, "must be a mapping")
            return
        for property_name, value in properties.items():
            self._validate_type_id(property_name, f"{path}.{property_name}")
            self._validate_json_value(value, f"{path}.{property_name}")

    def _validate_typed_properties(
        self,
        properties: Any,
        type_definition: dict[str, Any],
        path: str,
    ) -> None:
        if not isinstance(properties, dict):
            return
        usages = self._mapping(type_definition.get("properties"))
        for property_name, usage in usages.items():
            if self._mapping(usage).get("required") is True and property_name not in properties:
                self.result.error(path, f"missing required property {property_name}")
        for property_name, value in properties.items():
            definition = self._mapping(self.property_definitions.get(property_name))
            value_type = definition.get("type")
            if value_type in VALUE_TYPES:
                self._validate_value(value, value_type, f"{path}.{property_name}")
        longitude = properties.get("longitude")
        latitude = properties.get("latitude")
        coordinate_system = properties.get("coordinate_system")
        coordinate_fields = (longitude, latitude, coordinate_system)
        if any(value is not None for value in coordinate_fields):
            if longitude is None or latitude is None or coordinate_system is None:
                self.result.error(
                    path,
                    "longitude, latitude and coordinate_system must be provided together",
                )
            if self._is_number(longitude) and not -180 <= longitude <= 180:
                self.result.error(f"{path}.longitude", "must be between -180 and 180")
            if self._is_number(latitude) and not -90 <= latitude <= 90:
                self.result.error(f"{path}.latitude", "must be between -90 and 90")

    def _validate_tags(self, value: Any, path: str) -> None:
        if value is None:
            return
        if not isinstance(value, list):
            self.result.error(path, "must be a list")
            return
        seen: set[str] = set()
        has_duplicates = False
        for index, tag in enumerate(value):
            self._validate_type_id(tag, f"{path}[{index}]")
            if isinstance(tag, str):
                if tag in seen:
                    has_duplicates = True
                seen.add(tag)
        if has_duplicates:
            self.result.error(path, "must not contain duplicates")

    def _validate_source_refs(self, value: Any, path: str) -> None:
        if value is None:
            return
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            self.result.error(path, "must be a list of non-empty strings")

    def _validate_value(self, value: Any, value_type: str, path: str) -> None:
        if value_type == "string" and not isinstance(value, str):
            self.result.error(path, "must be a string")
        elif value_type == "number" and not self._is_number(value):
            self.result.error(path, "must be a number")
        elif value_type == "boolean" and not isinstance(value, bool):
            self.result.error(path, "must be a boolean")
        elif value_type == "date":
            if not isinstance(value, str):
                self.result.error(path, "must be an ISO date")
            else:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    self.result.error(path, "must be an ISO date")
        elif value_type == "datetime":
            if not isinstance(value, str):
                self.result.error(path, "must be an ISO datetime")
            else:
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    self.result.error(path, "must be an ISO datetime")
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
        elif value_type == "json":
            self._validate_json_value(value, path)

    def _validate_json_value(self, value: Any, path: str) -> None:
        if value is None or isinstance(value, (str, int, float, bool)):
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                self._validate_json_value(item, f"{path}[{index}]")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    self.result.error(path, "mapping keys must be strings")
                self._validate_json_value(item, f"{path}.{key}")
            return
        self.result.error(path, "must be JSON-compatible")

    def _validate_semantics(self) -> None:
        for relation_type, definition in self.relation_type_definitions.items():
            if self._mapping(definition).get("acyclic") is True:
                self._validate_acyclic(relation_type)

    def _validate_acyclic(self, relation_type: str) -> None:
        graph: dict[str, list[str]] = {}
        for item in self.relation_items:
            if item.get("type") == relation_type:
                graph.setdefault(str(item.get("from")), []).append(str(item.get("to")))

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(target) for target in graph.get(node, [])):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        if any(visit(node) for node in list(graph)):
            self.result.error(f"relation.{relation_type}", "must not contain a cycle")

    def _validate_type_id(self, value: Any, path: str) -> None:
        if not isinstance(value, str) or not TYPE_ID.fullmatch(value):
            self.result.error(path, "must be an ASCII snake_case identifier")

    def _validate_instance_id(self, value: Any, path: str) -> None:
        if not isinstance(value, str) or not INSTANCE_ID.fullmatch(value):
            self.result.error(path, "invalid instance ID")

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_model(root: Path) -> ValidationResult:
    model_path = root / "model.yaml"
    object_data, relation_data = load_data(root)
    return ModelValidator(
        load_yaml(CORE_ONTOLOGY_PATH),
        object_data,
        relation_data,
        load_yaml(model_path) if model_path.exists() else None,
    ).validate()


def main(default_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root or Path.cwd())
    args = parser.parse_args()
    result = validate_model(args.root.resolve())
    for error in result.errors:
        print(f"ERROR: {error}")
    if result.valid:
        print("UOM domain model is valid")
        return 0
    print(f"UOM domain model validation failed with {len(result.errors)} error(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
