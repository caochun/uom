"""Compile a business-oriented UOM model into an OAG Ontology."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from oag.ontology.schema import Ontology

from uom.schema import DomainModel, PropertyUse


OAG_SCHEMA = "oag.ontology.v1"
_REPOSITORY_TYPES = {
    "sqlite_graph": "uom_sqlite_graph",
}
_OBJECT_BASE_PROPERTIES = {
    "id": {"type": "str", "required": True, "description": "稳定对象 ID"},
    "name": {"type": "str", "required": True, "description": "对象名称"},
}
_RELATION_BASE_PROPERTIES = {
    "id": {"type": "str", "required": True, "description": "稳定关系 ID"},
    "from": {"type": "str", "required": True, "description": "起点对象 ID"},
    "to": {"type": "str", "required": True, "description": "终点对象 ID"},
}


def compile_ontology_payload(model: DomainModel) -> dict[str, Any]:
    """Return the complete OAG payload generated from one UOM source model."""
    objects = {
        type_id: _compile_object(type_id, definition, model)
        for type_id, definition in model.objects.items()
    }
    relations = {
        type_id: _compile_relation(type_id, definition, model)
        for type_id, definition in model.relations.items()
    }
    functions = {
        function_id: _compile_function(definition)
        for function_id, definition in model.functions.items()
    }
    actions = {
        action_id: _compile_action(definition, model)
        for action_id, definition in model.actions.items()
    }
    payload = {
        "schema": OAG_SCHEMA,
        "name": model.name,
        "version": model.version,
        "description": model.description,
        "excluded_tools": list(model.agent.excluded_tools),
        "data_sources": {
            repository_id: _compile_repository(definition)
            for repository_id, definition in model.repositories.items()
        },
        "objects": objects,
        "relations": relations,
        "functions": functions,
        "actions": actions,
        "interaction_policies": {
            "user_chat": {
                "include_in_system_prompt": True,
                "instructions": list(model.agent.instructions),
            }
        },
    }
    return payload


def compile_ontology(model: DomainModel) -> Ontology:
    return Ontology.model_validate(compile_ontology_payload(model))


def _compile_repository(definition):
    return {
        "type": _REPOSITORY_TYPES.get(definition.type, definition.type),
        "mode": definition.mode,
        "config": deepcopy(definition.config),
    }


def _compile_object(type_id, definition, model: DomainModel):
    description = definition.description or definition.name
    repository = model.repositories[definition.repository or model.default_repository]
    return {
        "display_name": definition.name,
        "summary": description,
        "description": description,
        "aliases": [{"terms": [alias]} for alias in definition.aliases],
        "type_policy": "closed",
        "mutability": "mutable" if repository.mode == "writable" else "read_only",
        "data_source": "human_confirmed",
        "binding": {
            "source": definition.repository or model.default_repository,
            "selector": deepcopy(definition.selector)
            or {"kind": "object", "type": type_id},
            "mapping": deepcopy(definition.mapping),
        },
        "properties": {
            **deepcopy(_OBJECT_BASE_PROPERTIES),
            **_compile_properties(definition.properties, model),
        },
    }


def _compile_relation(type_id, definition, model: DomainModel):
    description = definition.description or definition.name
    repository = model.repositories[definition.repository or model.default_repository]
    return {
        "display_name": definition.name,
        "summary": description,
        "description": description,
        "aliases": list(definition.aliases),
        "from_types": list(definition.from_types),
        "to_types": list(definition.to_types),
        "directed": True,
        "acyclic": definition.acyclic,
        "type_policy": "closed",
        "mutability": "mutable" if repository.mode == "writable" else "read_only",
        "data_source": "human_confirmed",
        "binding": {
            "source": definition.repository or model.default_repository,
            "selector": deepcopy(definition.selector)
            or {"kind": "relation", "type": type_id},
            "mapping": deepcopy(definition.mapping),
        },
        "properties": {
            **deepcopy(_RELATION_BASE_PROPERTIES),
            **_compile_properties(definition.properties, model),
        },
    }


def _compile_properties(usages: dict[str, PropertyUse], model: DomainModel):
    result = {}
    for property_id, usage in usages.items():
        definition = model.properties[property_id]
        item = {
            "type": definition.type,
            "required": usage.required,
            "display_name": definition.name,
            "description": definition.description or definition.name,
            "aliases": list(definition.aliases),
        }
        if "default" in definition.model_fields_set:
            item["default"] = deepcopy(definition.default)
        result[property_id] = item
    return result


def _compile_function(definition):
    result = {
        "summary": definition.name,
        "description": definition.description,
        "usage_prompt": definition.usage_prompt,
        "user_visible": definition.user_visible,
        "reads_objects": list(definition.reads.objects),
        "reads_relations": list(definition.reads.relations),
        "params": {},
        "timeout_seconds": definition.timeout_seconds,
        "concurrency_safe": definition.concurrency_safe,
    }
    for input_id, input_definition in definition.inputs.items():
        item = {
            "type": input_definition.type,
            "description": input_definition.description,
        }
        if "default" in input_definition.model_fields_set:
            item["default"] = deepcopy(input_definition.default)
        result["params"][input_id] = item
    return result


def _compile_action(definition, model: DomainModel):
    changes = definition.changes
    result = {
        "display_name": definition.name,
        "summary": definition.description or definition.name,
        "description": definition.description or definition.name,
        "usage_prompt": definition.usage_prompt,
        "icon": definition.icon,
        "user_visible": definition.user_visible,
        "available_on": list(definition.on),
        "context_input": definition.context,
        "inputs": {},
        "preconditions": deepcopy(definition.requires),
        "side_effects": {
            "creates_objects": list(changes.create.objects),
            "updates_objects": list(changes.update.objects),
            "retires_objects": list(changes.retire.objects),
            "creates_relations": list(changes.create.relations),
            "updates_relations": list(changes.update.relations),
            "retires_relations": list(changes.retire.relations),
        },
        "confirmation": definition.confirmation,
        "idempotency": definition.idempotency,
    }
    for input_id, input_definition in definition.inputs.items():
        item = {
            "display_name": input_definition.name,
            "description": input_definition.description,
            "required": input_definition.required,
            "options": deepcopy(input_definition.options),
        }
        if input_definition.property:
            property_definition = model.properties[input_definition.property]
            item["type"] = property_definition.type
            if not item["description"]:
                item["description"] = property_definition.description
        elif input_definition.objects:
            item["type"] = "str"
            item["object_types"] = list(input_definition.objects)
        else:
            item["type"] = input_definition.type
        if "default" in input_definition.model_fields_set:
            item["default"] = deepcopy(input_definition.default)
        result["inputs"][input_id] = item
    return result
