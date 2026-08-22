"""Source schema for business-oriented UOM domain models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UomModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PropertyDef(UomModel):
    name: str
    type: str = "string"
    description: str = ""
    default: Any = None
    aliases: list[str] = Field(default_factory=list)


class PropertyUse(UomModel):
    required: bool = False

    @model_validator(mode="before")
    @classmethod
    def expand_short_form(cls, value: Any) -> Any:
        if value is None or value == "optional":
            return {}
        if value == "required":
            return {"required": True}
        if isinstance(value, bool):
            return {"required": value}
        return value


class ObjectDef(UomModel):
    name: str
    description: str = ""
    properties: dict[str, PropertyUse] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    repository: str = ""
    selector: dict[str, Any] = Field(default_factory=dict)
    mapping: dict[str, Any] = Field(default_factory=dict)


class RelationDef(UomModel):
    name: str
    description: str = ""
    from_types: list[str] = Field(default_factory=list, alias="from")
    to_types: list[str] = Field(default_factory=list, alias="to")
    properties: dict[str, PropertyUse] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    acyclic: bool = False
    repository: str = ""
    selector: dict[str, Any] = Field(default_factory=dict)
    mapping: dict[str, Any] = Field(default_factory=dict)


class RepositoryDef(UomModel):
    type: str
    mode: Literal["read_only", "writable"] = "read_only"
    config: dict[str, Any] = Field(default_factory=dict)


class FunctionInputDef(UomModel):
    type: str = "string"
    description: str = ""
    default: Any = None


class FunctionReadsDef(UomModel):
    objects: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)


class FunctionDef(UomModel):
    name: str
    description: str = ""
    usage_prompt: str = ""
    inputs: dict[str, FunctionInputDef] = Field(default_factory=dict)
    reads: FunctionReadsDef = Field(default_factory=FunctionReadsDef)
    user_visible: bool = True
    timeout_seconds: float | None = 30.0
    concurrency_safe: bool | None = None


class ActionInputDef(UomModel):
    name: str
    description: str = ""
    property: str = ""
    type: str = ""
    objects: list[str] = Field(default_factory=list)
    required: bool = False
    default: Any = None
    options: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source(self):
        sources = bool(self.property) + bool(self.type) + bool(self.objects)
        if sources != 1:
            raise ValueError("action input must define exactly one of property, type or objects")
        return self


class ChangeKinds(UomModel):
    objects: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)


class ActionChangesDef(UomModel):
    create: ChangeKinds = Field(default_factory=ChangeKinds)
    update: ChangeKinds = Field(default_factory=ChangeKinds)
    retire: ChangeKinds = Field(default_factory=ChangeKinds)


class ActionDef(UomModel):
    name: str
    description: str = ""
    usage_prompt: str = ""
    icon: str = ""
    user_visible: bool = True
    on: list[str] = Field(default_factory=list)
    context: str = ""
    inputs: dict[str, ActionInputDef] = Field(default_factory=dict)
    requires: list[dict[str, Any]] = Field(default_factory=list)
    changes: ActionChangesDef = Field(default_factory=ActionChangesDef)
    confirmation: str = ""
    idempotency: Literal["required", "optional", "none"] = "required"


class AgentDef(UomModel):
    instructions: list[str] = Field(default_factory=list)
    excluded_tools: list[str] = Field(default_factory=lambda: [
        "dispatch_workers",
    ])


class DomainModel(UomModel):
    schema_id: Literal["uom.domain.v1"] = Field(alias="schema")
    name: str
    version: str
    description: str = ""
    repositories: dict[str, RepositoryDef]
    default_repository: str
    properties: dict[str, PropertyDef] = Field(default_factory=dict)
    objects: dict[str, ObjectDef] = Field(default_factory=dict)
    relations: dict[str, RelationDef] = Field(default_factory=dict)
    functions: dict[str, FunctionDef] = Field(default_factory=dict)
    actions: dict[str, ActionDef] = Field(default_factory=dict)
    agent: AgentDef = Field(default_factory=AgentDef)

    @model_validator(mode="after")
    def validate_references(self):
        if self.default_repository not in self.repositories:
            raise ValueError(
                f"default_repository references unknown repository: {self.default_repository}"
            )
        known_properties = set(self.properties)
        known_objects = set(self.objects)
        known_relations = set(self.relations)
        for kind, definitions in (("object", self.objects), ("relation", self.relations)):
            for type_id, definition in definitions.items():
                unknown = set(definition.properties) - known_properties
                if unknown:
                    raise ValueError(
                        f"{kind} {type_id} references unknown properties: "
                        + ", ".join(sorted(unknown))
                    )
                repository = definition.repository or self.default_repository
                if repository not in self.repositories:
                    raise ValueError(
                        f"{kind} {type_id} references unknown repository: {repository}"
                    )
                if kind == "relation":
                    unknown_from = set(definition.from_types) - known_objects
                    unknown_to = set(definition.to_types) - known_objects
                    if unknown_from or unknown_to:
                        unknown_endpoints = sorted(unknown_from | unknown_to)
                        raise ValueError(
                            f"relation {type_id} references unknown object types: "
                            + ", ".join(unknown_endpoints)
                        )
        for function_id, function in self.functions.items():
            unknown_objects = set(function.reads.objects) - known_objects
            unknown_relations = set(function.reads.relations) - known_relations
            if unknown_objects or unknown_relations:
                raise ValueError(
                    f"function {function_id} references unknown graph types: "
                    + ", ".join(sorted(unknown_objects | unknown_relations))
                )
        for action_id, action in self.actions.items():
            unknown = {
                definition.property
                for definition in action.inputs.values()
                if definition.property and definition.property not in known_properties
            }
            if unknown:
                raise ValueError(
                    f"action {action_id} references unknown properties: "
                    + ", ".join(sorted(unknown))
                )
            referenced_objects = set(action.on)
            for definition in action.inputs.values():
                referenced_objects.update(definition.objects)
            for change in (
                action.changes.create,
                action.changes.update,
                action.changes.retire,
            ):
                referenced_objects.update(change.objects)
            referenced_relations = {
                type_id
                for change in (
                    action.changes.create,
                    action.changes.update,
                    action.changes.retire,
                )
                for type_id in change.relations
            }
            unknown_objects = referenced_objects - known_objects - {"*"}
            unknown_relations = referenced_relations - known_relations - {"*"}
            if unknown_objects or unknown_relations:
                raise ValueError(
                    f"action {action_id} references unknown graph types: "
                    + ", ".join(sorted(unknown_objects | unknown_relations))
                )
            if action.context and action.context not in action.inputs:
                raise ValueError(
                    f"action {action_id} context references unknown input: {action.context}"
                )
        return self
