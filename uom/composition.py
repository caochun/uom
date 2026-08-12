"""Compose a UOM core ontology with domain runtime semantics."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


IMPLEMENTATION_REF = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$"
)
RUNTIME_SECTIONS = frozenset({
    "functions",
    "presentation_tools",
    "interaction_policies",
})


def compose_ontology_payload(
    core: dict[str, Any],
    domain_model: dict[str, Any],
) -> dict[str, Any]:
    """Return the effective OAG ontology without leaking UOM implementation fields."""
    effective = deepcopy(core)
    metadata = domain_model.get("model") or {}
    if metadata.get("name"):
        effective["name"] = metadata["name"]
    if metadata.get("description"):
        effective["description"] = metadata["description"]

    runtime = domain_model.get("runtime") or {}
    if not isinstance(runtime, dict):
        raise ValueError("model.runtime must be a mapping")
    unknown_sections = set(runtime) - RUNTIME_SECTIONS
    if unknown_sections:
        raise ValueError(
            "model.runtime contains unknown sections: "
            + ", ".join(sorted(unknown_sections))
        )
    for section in ("functions", "presentation_tools"):
        additions = runtime.get(section) or {}
        if not isinstance(additions, dict):
            raise ValueError(f"model.runtime.{section} must be a mapping")
        target = effective.setdefault(section, {})
        collisions = set(target) & set(additions)
        if collisions:
            raise ValueError(
                f"model.runtime.{section} cannot override core definitions: "
                + ", ".join(sorted(collisions))
            )
        for name, definition in additions.items():
            if not isinstance(definition, dict):
                raise ValueError(f"model.runtime.{section}.{name} must be a mapping")
            public_definition = deepcopy(definition)
            public_definition.pop("implementation", None)
            target[name] = public_definition

    policies = runtime.get("interaction_policies") or {}
    if not isinstance(policies, dict):
        raise ValueError("model.runtime.interaction_policies must be a mapping")
    for name, policy in policies.items():
        if not isinstance(policy, dict):
            raise ValueError(
                f"model.runtime.interaction_policies.{name} must be a mapping"
            )
        target = effective.setdefault("interaction_policies", {}).setdefault(name, {})
        incoming = deepcopy(policy)
        instructions = incoming.pop("instructions", []) or []
        include_in_system_prompt = incoming.pop(
            "include_in_system_prompt",
            False,
        )
        if not isinstance(instructions, list):
            raise ValueError(
                f"model.runtime.interaction_policies.{name}.instructions must be a list"
            )
        target["include_in_system_prompt"] = bool(
            target.get("include_in_system_prompt")
            or include_in_system_prompt
        )
        target["instructions"] = [
            *(target.get("instructions") or []),
            *instructions,
        ]
        target.update(incoming)
    return effective


def domain_function_implementations(domain_model: dict[str, Any]) -> dict[str, str]:
    result = {}
    runtime = domain_model.get("runtime") or {}
    functions = runtime.get("functions") or {}
    for name, definition in functions.items():
        implementation = definition.get("implementation")
        if not isinstance(implementation, str) or not IMPLEMENTATION_REF.fullmatch(
            implementation
        ):
            raise ValueError(
                f"model.runtime.functions.{name}.implementation must be module:function"
            )
        result[name] = implementation
    return result
