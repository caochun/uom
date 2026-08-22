"""Load UOM source models and derive private runtime/editor projections."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from oag.ontology.schema import Ontology

from uom.compiler import compile_ontology, compile_ontology_payload
from uom.schema import DomainModel


ACTION_PLAN_SCHEMA = "uom.action_plans.v1"
MODEL_SCHEMA = "uom.domain.v1"
_OBJECT_BASE_PROPERTIES = {
    "id": {"type": "str", "required": True, "description": "稳定对象 ID"},
    "name": {"type": "str", "required": True, "description": "对象名称"},
}
_RELATION_BASE_PROPERTIES = {
    "id": {"type": "str", "required": True, "description": "稳定关系 ID"},
    "from": {"type": "str", "required": True, "description": "起点对象 ID"},
    "to": {"type": "str", "required": True, "description": "终点对象 ID"},
}
_SIDE_EFFECT_KEYS = (
    "creates_objects",
    "updates_objects",
    "retires_objects",
    "creates_relations",
    "updates_relations",
    "retires_relations",
)


def load_yaml_mapping(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def load_domain_model(domain_dir: str | Path) -> tuple[dict[str, Any], DomainModel]:
    payload = load_yaml_mapping(Path(domain_dir) / "model.yaml")
    if payload.get("schema") != MODEL_SCHEMA:
        raise ValueError(f"model.yaml schema must be {MODEL_SCHEMA}")
    return payload, DomainModel.model_validate(payload)


def load_public_ontology(domain_dir: str | Path) -> tuple[dict[str, Any], Ontology]:
    """Compile the UOM source model to the public OAG runtime ontology."""
    _, model = load_domain_model(domain_dir)
    return public_ontology(model)


def public_ontology(model: DomainModel) -> tuple[dict[str, Any], Ontology]:
    """Compile one already validated UOM source model exactly once."""
    payload = compile_ontology_payload(model)
    return payload, Ontology.model_validate(payload)


def load_action_plans(domain_dir: str | Path) -> dict[str, Any]:
    path = Path(domain_dir) / "action_plans.yaml"
    if not path.is_file():
        return {"schema": ACTION_PLAN_SCHEMA, "actions": {}}
    payload = load_yaml_mapping(path)
    if payload.get("schema") != ACTION_PLAN_SCHEMA:
        raise ValueError(f"action_plans.yaml schema must be {ACTION_PLAN_SCHEMA}")
    unknown = set(payload) - {"schema", "actions"}
    if unknown:
        raise ValueError(
            "action_plans.yaml contains unknown fields: " + ", ".join(sorted(unknown))
        )
    actions = payload.get("actions")
    if not isinstance(actions, dict):
        raise ValueError("action_plans.yaml actions must be a mapping")
    return payload


def validate_action_plans(
    public_model: dict[str, Any],
    action_plans: dict[str, Any],
) -> None:
    public_actions = _mapping(public_model.get("actions"))
    plans = _mapping(action_plans.get("actions"))
    missing = set(public_actions) - set(plans)
    unknown = set(plans) - set(public_actions)
    if missing or unknown:
        messages = []
        if missing:
            messages.append("missing plans: " + ", ".join(sorted(missing)))
        if unknown:
            messages.append("unknown plans: " + ", ".join(sorted(unknown)))
        raise ValueError("action_plans.yaml does not match model actions; " + "; ".join(messages))

    for action_id, plan in plans.items():
        if not isinstance(plan, dict):
            raise ValueError(f"action_plans.actions.{action_id} must be a mapping")
        extra = set(plan) - {"handler", "effects"}
        if extra:
            raise ValueError(
                f"action_plans.actions.{action_id} contains unknown fields: "
                + ", ".join(sorted(extra))
            )
        if plan.get("handler") != "changeset":
            raise ValueError(f"action_plans.actions.{action_id}.handler must be changeset")
        effects = plan.get("effects")
        if not isinstance(effects, list) or not effects:
            raise ValueError(f"action_plans.actions.{action_id}.effects must be a non-empty list")
        declared = {
            key: list(value or [])
            for key, value in _mapping(public_actions[action_id].get("side_effects")).items()
            if key in _SIDE_EFFECT_KEYS
        }
        actual = _side_effects_for_plan(
            effects,
            _mapping(public_actions[action_id].get("inputs")),
            _mapping(public_model.get("objects")),
        )
        if {key: declared.get(key, []) for key in _SIDE_EFFECT_KEYS} != actual:
            raise ValueError(
                f"action {action_id} public side_effects do not match its private plan"
            )


def workspace_model(
    public_model: dict[str, Any],
    action_plans: dict[str, Any],
    source_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the private UOM validation/editor view; OAG never sees this shape."""
    validate_action_plans(public_model, action_plans)
    properties = {
        property_id: _source_workspace_property(property_id, definition)
        for property_id, definition in _mapping(
            _mapping(source_model).get("properties")
        ).items()
    }
    objects = {
        type_id: _workspace_type(definition, properties, kind="object")
        for type_id, definition in _mapping(public_model.get("objects")).items()
    }
    relations = {
        type_id: _workspace_type(definition, properties, kind="relation")
        for type_id, definition in _mapping(public_model.get("relations")).items()
    }
    plans = _mapping(action_plans.get("actions"))
    actions = {
        action_id: _workspace_action(definition, plans[action_id])
        for action_id, definition in _mapping(public_model.get("actions")).items()
    }
    return {
        "schema": "uom.runtime_model.v1",
        "model": {
            "name": public_model.get("name", ""),
            "version": public_model.get("version", ""),
            "description": public_model.get("description", ""),
        },
        "runtime": {"functions": {}},
        "property_definitions": properties,
        "object_types": objects,
        "relation_types": relations,
        "actions": actions,
    }


def update_source_vocabulary(
    source_model: dict[str, Any],
    editor_model: dict[str, Any],
) -> dict[str, Any]:
    """Apply the model editor's vocabulary view back to a UOM source model."""
    result = deepcopy(source_model)
    metadata = _mapping(editor_model.get("model"))
    for key in ("name", "version", "description"):
        if key in metadata:
            result[key] = deepcopy(metadata[key])
    property_definitions = _mapping(editor_model.get("property_definitions"))
    result["properties"] = {
        property_id: _source_property(property_id, definition)
        for property_id, definition in property_definitions.items()
    }
    current_objects = _mapping(result.get("objects"))
    result["objects"] = {
        type_id: _source_type(
            type_id,
            definition,
            current_objects.get(type_id),
            kind="object",
        )
        for type_id, definition in _mapping(editor_model.get("object_types")).items()
    }
    current_relations = _mapping(result.get("relations"))
    result["relations"] = {
        type_id: _source_type(
            type_id,
            definition,
            current_relations.get(type_id),
            kind="relation",
        )
        for type_id, definition in _mapping(editor_model.get("relation_types")).items()
    }
    compile_ontology(DomainModel.model_validate(result))
    return result


def storage_contract_payload() -> dict[str, Any]:
    """Physical UOM graph record contract used only by storage validation."""
    return {
        "schema": "uom.storage_contract.v1",
        "name": "UOM SQLite graph storage contract",
        "description": "UOM SQLite 物理对象与关系记录的内部校验契约。",
        "objects": {
            "Object": {
                "display_name": "存储对象",
                "description": "SQLite 属性图中的通用对象记录。",
                "type_policy": "open",
                "binding": {"source": "uom_graph", "selector": {"kind": "object"}},
                "properties": {
                    "id": {"type": "str", "required": True},
                    "type": {"type": "str", "required": True},
                    "name": {"type": "str", "required": True},
                    "properties": {"type": "dict"},
                    "tags": {"type": "list"},
                    "source_refs": {"type": "list"},
                    "lifecycle": {"type": "dict"},
                },
            }
        },
        "relations": {
            "Relation": {
                "display_name": "存储关系",
                "description": "SQLite 属性图中的通用关系记录。",
                "type_policy": "open",
                "binding": {"source": "uom_graph", "selector": {"kind": "relation"}},
                "properties": {
                    "id": {"type": "str", "required": True},
                    "type": {"type": "str", "required": True},
                    "from": {"type": "str", "required": True},
                    "to": {"type": "str", "required": True},
                    "properties": {"type": "dict"},
                    "tags": {"type": "list"},
                    "source_refs": {"type": "list"},
                    "lifecycle": {"type": "dict"},
                },
            }
        },
    }


def _workspace_type(
    definition: Any,
    properties: dict[str, dict[str, Any]],
    *,
    kind: str,
) -> dict[str, Any]:
    definition = _mapping(definition)
    base = _OBJECT_BASE_PROPERTIES if kind == "object" else _RELATION_BASE_PROPERTIES
    usages = {}
    for property_id, property_definition in _mapping(definition.get("properties")).items():
        if property_id in base:
            continue
        normalized = _workspace_property(property_id, property_definition)
        current = properties.get(property_id)
        if current is not None and _property_signature(current) != _property_signature(normalized):
            raise ValueError(f"property {property_id} has inconsistent definitions across types")
        properties[property_id] = normalized
        usages[property_id] = {
            "required": bool(_mapping(property_definition).get("required")),
        }
    result = {
        "name": definition.get("display_name") or definition.get("summary") or "",
        "description": definition.get("description") or definition.get("summary") or "",
        "properties": usages,
    }
    aliases = definition.get("aliases") or []
    if kind == "object":
        terms = [term for item in aliases for term in (_mapping(item).get("terms") or [])]
        if terms:
            result["aliases"] = terms
    elif aliases:
        result["aliases"] = list(aliases)
    if kind == "relation":
        result["from_types"] = list(definition.get("from_types") or [])
        result["to_types"] = list(definition.get("to_types") or [])
        if definition.get("acyclic") is True:
            result["acyclic"] = True
    return result


def _workspace_property(property_id: str, definition: Any) -> dict[str, Any]:
    definition = _mapping(definition)
    result = {
        "name": definition.get("display_name") or definition.get("description") or property_id,
        "type": definition.get("type") or "string",
        "description": definition.get("description") or property_id,
    }
    for key in ("aliases", "default"):
        if key == "default" and key in definition and definition[key] is not None:
            result[key] = deepcopy(definition[key])
        elif key in definition and definition[key] not in (None, [], False):
            result[key] = deepcopy(definition[key])
    return result


def _source_workspace_property(property_id: str, definition: Any) -> dict[str, Any]:
    definition = _mapping(definition)
    result = {
        "name": definition.get("name") or property_id,
        "type": definition.get("type") or "string",
        "description": definition.get("description") or definition.get("name") or property_id,
    }
    for key in ("aliases", "default"):
        if key in definition and definition[key] not in (None, []):
            result[key] = deepcopy(definition[key])
    return result


def _workspace_action(definition: Any, plan: Any) -> dict[str, Any]:
    definition = _mapping(definition)
    plan = _mapping(plan)
    inputs = {}
    for input_id, input_definition in _mapping(definition.get("inputs")).items():
        input_definition = _mapping(input_definition)
        item = {
            "name": input_definition.get("display_name") or input_id,
            "required": bool(input_definition.get("required")),
        }
        object_types = list(input_definition.get("object_types") or [])
        if object_types:
            item["object_types"] = object_types
        else:
            item["type"] = input_definition.get("type") or "string"
        if "default" in input_definition and input_definition.get("default") is not None:
            item["default"] = deepcopy(input_definition["default"])
        inputs[input_id] = item
    result = {
        "name": definition.get("display_name") or definition.get("summary") or "",
        "description": definition.get("description") or definition.get("summary") or "",
        "icon": definition.get("icon", ""),
        "handler": plan.get("handler"),
        "confirmation": definition.get("confirmation", ""),
        "inputs": inputs,
        "effects": deepcopy(plan.get("effects") or []),
    }
    if definition.get("available_on"):
        result["available_on"] = list(definition["available_on"])
    if definition.get("context_input"):
        result["context_input"] = definition["context_input"]
    if definition.get("preconditions"):
        result["requires"] = deepcopy(definition["preconditions"])
    return result


def _source_type(
    type_id: str,
    definition: Any,
    current: Any,
    *,
    kind: str,
) -> dict[str, Any]:
    definition = _mapping(definition)
    current = deepcopy(_mapping(current))
    result = current or {}
    result["name"] = definition.get("name") or type_id
    result["description"] = definition.get("description") or ""
    if kind == "object":
        result["aliases"] = list(definition.get("aliases") or [])
    else:
        result["aliases"] = list(definition.get("aliases") or [])
        result["from"] = list(definition.get("from_types") or [])
        result["to"] = list(definition.get("to_types") or [])
        result["acyclic"] = bool(definition.get("acyclic"))
    result["properties"] = {}
    for property_id, usage in _mapping(definition.get("properties")).items():
        result["properties"][property_id] = (
            "required" if bool(_mapping(usage).get("required")) else "optional"
        )
    return result


def _source_property(property_id: str, definition: Any) -> dict[str, Any]:
    definition = _mapping(definition)
    result = {
        "name": definition.get("name") or property_id,
        "type": definition.get("type") or "string",
        "description": definition.get("description") or property_id,
    }
    for key in ("aliases", "default"):
        if key == "default" and key in definition and definition[key] is not None:
            result[key] = deepcopy(definition[key])
        elif key in definition and definition[key] not in (None, [], False):
            result[key] = deepcopy(definition[key])
    return result


def _side_effects_for_plan(
    effects: list[Any],
    inputs: dict[str, Any],
    object_types: dict[str, Any],
) -> dict[str, list[str]]:
    result = {key: [] for key in _SIDE_EFFECT_KEYS}
    for effect in effects:
        if not isinstance(effect, dict) or len(effect) != 1:
            continue
        operation, raw_payload = next(iter(effect.items()))
        payload = _mapping(raw_payload)
        if operation == "create_object":
            _append_unique(result["creates_objects"], payload.get("type"))
        elif operation == "create_relation":
            _append_unique(result["creates_relations"], payload.get("type"))
        elif operation == "update_object":
            for type_id in _object_types_for_reference(payload.get("id"), inputs, object_types):
                _append_unique(result["updates_objects"], type_id)
        elif operation in {"delete_object", "retire_object"}:
            for type_id in _object_types_for_reference(payload.get("id"), inputs, object_types):
                _append_unique(result["retires_objects"], type_id)
        elif operation == "update_relation":
            _append_unique(result["updates_relations"], payload.get("type"))
        elif operation in {"delete_relation", "retire_relation"}:
            _append_unique(result["retires_relations"], payload.get("type"))
    return result


def _object_types_for_reference(
    reference: Any,
    inputs: dict[str, Any],
    object_types: dict[str, Any],
) -> list[str]:
    if isinstance(reference, str) and reference.startswith("$input."):
        definition = _mapping(inputs.get(reference.removeprefix("$input.")))
        return list(definition.get("object_types") or [])
    return list(object_types) if reference == "*" else []


def _property_signature(definition: dict[str, Any]) -> tuple[Any, ...]:
    return (
        definition.get("type"),
        definition.get("name"),
        definition.get("description"),
        tuple(definition.get("aliases") or []),
    )


def _append_unique(values: list[str], value: Any) -> None:
    if isinstance(value, str) and value and value not in values:
        values.append(value)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
