"""Compile model-driven business actions to validated UOM ChangeSets."""

from __future__ import annotations

import re
import threading
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from uom.workspace import ChangeValidationError, UomWorkspaceService


_MISSING = object()
_PERIOD = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")


class ModelActionService:
    """Resolve private action plans into validated UOM ChangeSets."""

    def __init__(self, workspace: UomWorkspaceService):
        self.workspace = workspace
        self._previews: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def list_actions(self, context_id: str = "") -> dict[str, Any]:
        model = self.workspace.load_model()
        context = self._context(context_id) if context_id else None
        actions = []
        for action_id, definition in model.get("actions", {}).items():
            available_on = definition.get("available_on")
            if available_on is not None:
                if context is None:
                    continue
                if "*" not in available_on and context.get("type") not in available_on:
                    continue
            condition_inputs = {}
            context_input = definition.get("context_input")
            if context is not None and context_input:
                condition_inputs[context_input] = context["id"]
            blocked_reasons = self._requirement_errors(
                definition.get("requires", []),
                condition_inputs,
                context,
                allow_unresolved=True,
            )
            actions.append({
                **self._action_form_definition(action_id, definition),
                "confirmation": definition.get("confirmation", ""),
                "executable": not blocked_reasons,
                "blocked_reasons": blocked_reasons,
            })
        return {"context": context, "actions": actions}

    def prepare_action(
        self,
        action_id: str,
        initial_inputs: dict[str, Any] | None = None,
        context_id: str = "",
    ) -> dict[str, Any]:
        """Validate a UI handoff without requiring the action's missing inputs."""
        with self._lock:
            model = self.workspace.load_model()
            definition = model.get("actions", {}).get(action_id)
            if not isinstance(definition, dict):
                raise ChangeValidationError([f"action: 未知业务操作 {action_id}"])
            supplied_inputs, context = self._resolve_action_context(
                definition,
                initial_inputs or {},
                context_id,
                allow_missing=True,
            )
            prepared_inputs = self._validate_partial_inputs(
                definition.get("inputs", {}),
                supplied_inputs,
                model,
            )
            self._require_preconditions(
                definition,
                prepared_inputs,
                context,
                allow_unresolved=True,
            )
            return {
                "action": self._action_form_definition(action_id, definition),
                "context": context,
                "context_id": context.get("id", "") if context else "",
                "initial_inputs": prepared_inputs,
            }

    def preview_action(
        self,
        action_id: str,
        inputs: dict[str, Any] | None = None,
        context_id: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            model = self.workspace.load_model()
            definition = model.get("actions", {}).get(action_id)
            if not isinstance(definition, dict):
                raise ChangeValidationError([f"action: 未知业务操作 {action_id}"])
            supplied_inputs, context = self._resolve_action_context(
                definition,
                inputs or {},
                context_id,
                allow_missing=False,
            )
            resolved_inputs = self._validate_inputs(
                definition.get("inputs", {}),
                supplied_inputs,
                model,
            )
            self._require_preconditions(definition, resolved_inputs, context)
            operations = self._compile_action_effects(
                action_id,
                definition.get("effects", []),
                resolved_inputs,
                context,
            )
            preview = self.workspace.preview_changes(
                operations,
                read_object_ids=self._action_read_object_ids(
                    definition, resolved_inputs, context,
                ),
            )
            result = {
                **preview,
                "action": self._action_summary(action_id, definition),
                "context": context,
                "operations": operations,
                "summary": definition.get("confirmation") or definition.get("name"),
            }
            if preview["valid"]:
                token = str(uuid4())
                self._previews[token] = {
                    "action_id": action_id,
                    "definition": deepcopy(definition),
                    "inputs": deepcopy(resolved_inputs),
                    "context": deepcopy(context),
                    "operations": deepcopy(operations),
                }
                result["preview_token"] = token
            return result

    def _compile_action_effects(
        self,
        action_id: str,
        effects: list[dict[str, Any]],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Compile an action's declared effects; domains may enrich them."""
        return self._compile_effects(effects, inputs, context)

    @staticmethod
    def _action_read_object_ids(
        definition: dict[str, Any],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> set[str]:
        object_ids = {context["id"]} if context and isinstance(context.get("id"), str) else set()
        for input_id, input_definition in definition.get("inputs", {}).items():
            value = inputs.get(input_id)
            if "object_types" in input_definition and isinstance(value, str):
                object_ids.add(value)
        return object_ids

    def execute_action(
        self,
        preview_token: str,
        reason: str = "",
        actor: str = "agent",
        channel: str = "agent",
    ) -> dict[str, Any]:
        with self._lock:
            preview = self._previews.get(preview_token)
            if preview is None:
                raise ChangeValidationError(["action: 预览已失效，请重新预览业务操作"])
            definition = preview["definition"]
            self._require_preconditions(
                definition,
                preview["inputs"],
                preview["context"],
            )
            audit = {
                "id": f"action:{uuid4()}",
                "action_id": preview["action_id"],
                "actor": str(actor or "unknown"),
                "channel": str(channel or "unknown"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "action_name": definition.get("name"),
                    "reason": str(reason or ""),
                    "context": preview["context"],
                    "inputs": preview["inputs"],
                    "operations": preview["operations"],
                },
            }
            result = self.workspace.apply_changes(preview["operations"], audit=audit)
            self._previews.pop(preview_token, None)
            return {
                **result,
                "action": self._action_summary(preview["action_id"], definition),
                "summary": definition.get("confirmation") or definition.get("name"),
                "audit_id": audit["id"],
            }

    def _validate_context(
        self,
        definition: dict[str, Any],
        context_id: str,
    ) -> dict[str, Any] | None:
        available_on = definition.get("available_on")
        if available_on is None:
            return self._context(context_id) if context_id else None
        if not context_id:
            raise ChangeValidationError(["action.context_id: 此业务操作需要当前对象"])
        context = self._context(context_id)
        if "*" not in available_on and context.get("type") not in available_on:
            raise ChangeValidationError([
                f"action.context_id: {definition.get('name')} 不适用于 {context.get('type')}"
            ])
        return context

    def _resolve_action_context(
        self,
        definition: dict[str, Any],
        supplied_inputs: dict[str, Any],
        context_id: str,
        *,
        allow_missing: bool,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Resolve UI context into an explicit business-object input when declared."""
        if not isinstance(supplied_inputs, dict):
            return supplied_inputs, self._validate_context(definition, context_id)

        context_input = definition.get("context_input")
        if not context_input:
            return deepcopy(supplied_inputs), self._validate_context(definition, context_id)

        resolved = deepcopy(supplied_inputs)
        input_context_id = resolved.get(context_input)
        if context_id and input_context_id and input_context_id != context_id:
            raise ChangeValidationError([
                f"action.inputs.{context_input}: 与当前操作对象不一致"
            ])

        effective_context_id = context_id or input_context_id or ""
        if not effective_context_id:
            if allow_missing:
                return resolved, None
            return resolved, None

        context = self._context(effective_context_id)
        available_on = definition.get("available_on", [])
        if "*" not in available_on and context.get("type") not in available_on:
            raise ChangeValidationError([
                f"action.inputs.{context_input}: {definition.get('name')} 不适用于 {context.get('type')}"
            ])
        resolved[context_input] = context["id"]
        return resolved, context

    def _context(self, context_id: str) -> dict[str, Any]:
        context = self.workspace.repository.get_object(context_id)
        if not context:
            raise ChangeValidationError([f"action.context_id: 未找到对象 {context_id}"])
        return context

    def _require_preconditions(
        self,
        definition: dict[str, Any],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
        *,
        allow_unresolved: bool = False,
    ) -> None:
        errors = self._requirement_errors(
            definition.get("requires", []),
            inputs,
            context,
            allow_unresolved=allow_unresolved,
        )
        if errors:
            raise ChangeValidationError([f"action.requires: {error}" for error in errors])

    def _requirement_errors(
        self,
        requirements: list[dict[str, Any]],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
        *,
        allow_unresolved: bool,
    ) -> list[str]:
        errors: list[str] = []
        for requirement in requirements:
            kind, condition = next(iter(requirement.items()))
            message = condition.get("message")
            if kind == "object_status":
                object_id = self._resolve_requirement_ref(condition["object"], inputs, context)
                if object_id is _MISSING:
                    if allow_unresolved:
                        continue
                    errors.append(message or "前置条件缺少业务对象")
                    continue
                record = self.workspace.repository.get_object(object_id)
                status = (record.get("properties") or {}).get("status") if record else None
                if record is None or status not in condition["in"]:
                    errors.append(message or f"{object_id} 状态必须是 {', '.join(condition['in'])}")
                continue

            from_id = self._resolve_requirement_endpoint(condition, "from", inputs, context)
            to_id = self._resolve_requirement_endpoint(condition, "to", inputs, context)
            if from_id is _MISSING or to_id is _MISSING:
                if allow_unresolved:
                    continue
                errors.append(message or "前置关联条件缺少业务对象")
                continue
            if not self._has_related_object(condition, from_id, to_id):
                errors.append(message or "未找到满足条件的关联业务对象")
        return errors

    def _resolve_requirement_endpoint(
        self,
        condition: dict[str, Any],
        side: str,
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> str | object:
        reference = condition.get(side, _MISSING)
        if reference is _MISSING:
            return None
        return self._resolve_requirement_ref(reference, inputs, context)

    def _resolve_requirement_ref(
        self,
        reference: str,
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> str | object:
        return self._resolve(reference, inputs, context, {})

    def _has_related_object(
        self,
        condition: dict[str, Any],
        from_id: str | object | None,
        to_id: str | object | None,
    ) -> bool:
        filters: dict[str, Any] = {"type": condition["relation"]}
        if from_id is not None:
            filters["from"] = from_id
        if to_id is not None:
            filters["to"] = to_id
        for relation in self.workspace.repository.query_relations(filters=filters):
            relation_properties = relation.get("properties") or {}
            if condition.get("role") is not None and relation_properties.get("role") != condition["role"]:
                continue
            source = self.workspace.repository.get_object(relation.get("from"))
            target = self.workspace.repository.get_object(relation.get("to"))
            if not source or not target:
                continue
            if condition.get("from_type") and source.get("type") != condition["from_type"]:
                continue
            if condition.get("to_type") and target.get("type") != condition["to_type"]:
                continue
            source_properties = source.get("properties") or {}
            if any(source_properties.get(key) != value for key, value in condition.get("properties", {}).items()):
                continue
            return True
        return False

    def _validate_inputs(
        self,
        definitions: dict[str, Any],
        supplied: dict[str, Any],
        model: dict[str, Any],
    ) -> dict[str, Any]:
        result, errors = self._collect_inputs(
            definitions,
            supplied,
            model,
            path="action.inputs",
            include_defaults=True,
            require_required=True,
        )
        if errors:
            raise ChangeValidationError(errors)
        return result

    def _collect_inputs(
        self,
        definitions: dict[str, Any],
        supplied: dict[str, Any],
        model: dict[str, Any],
        *,
        path: str,
        include_defaults: bool,
        require_required: bool,
    ) -> tuple[dict[str, Any], list[str]]:
        if not isinstance(supplied, dict):
            return {}, [f"{path}: 必须是对象"]

        unknown = set(supplied) - set(definitions)
        errors = [f"{path}.{name}: 未定义的输入" for name in sorted(unknown)]
        candidates: list[tuple[str, Any, dict[str, Any]]] = []

        if include_defaults:
            input_ids = definitions.keys()
        else:
            input_ids = (input_id for input_id in supplied if input_id not in unknown)

        for input_id in input_ids:
            definition = definitions[input_id]
            value = supplied.get(input_id, _MISSING)
            if include_defaults and value is _MISSING and "default" in definition:
                value = deepcopy(definition["default"])
            if value is _MISSING or value is None or value == "":
                if require_required and definition.get("required"):
                    errors.append(f"{path}.{input_id}: 必填")
                continue
            candidates.append((input_id, value, definition))

        result, value_errors = self._validate_input_values(candidates, model, path)
        errors.extend(value_errors)
        return result, errors

    def _validate_input_values(
        self,
        candidates: list[tuple[str, Any, dict[str, Any]]],
        model: dict[str, Any],
        path: str,
    ) -> tuple[dict[str, Any], list[str]]:
        result: dict[str, Any] = {}
        errors: list[str] = []
        for input_id, value, definition in candidates:
            error = self._validate_input_value(value, definition, model)
            if error:
                errors.append(f"{path}.{input_id}: {error}")
            else:
                result[input_id] = deepcopy(value)
        return result, errors

    def _validate_partial_inputs(
        self,
        definitions: dict[str, Any],
        supplied: dict[str, Any],
        model: dict[str, Any],
    ) -> dict[str, Any]:
        result, errors = self._collect_inputs(
            definitions,
            supplied,
            model,
            path="action.initial_inputs",
            include_defaults=False,
            require_required=False,
        )
        if errors:
            raise ChangeValidationError(errors)
        return result

    def _validate_input_value(
        self,
        value: Any,
        definition: dict[str, Any],
        model: dict[str, Any],
    ) -> str:
        if "object_types" in definition:
            if not isinstance(value, str):
                return "必须是对象 ID"
            record = self.workspace.repository.get_object(value)
            if not record:
                return f"未找到对象 {value}"
            if record.get("type") not in definition["object_types"]:
                return f"对象类型必须是 {', '.join(definition['object_types'])}"
            return ""
        value_type = definition.get("type")
        if "property" in definition:
            value_type = (
                model.get("property_definitions", {})
                .get(definition["property"], {})
                .get("type")
            )
        if value_type == "string" and not isinstance(value, str):
            return "必须是文本"
        if value_type == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return "必须是数字"
        if value_type == "boolean" and not isinstance(value, bool):
            return "必须是布尔值"
        if value_type == "date":
            try:
                if not isinstance(value, str):
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                return "必须是 ISO 日期"
        if value_type == "datetime":
            try:
                if not isinstance(value, str):
                    raise ValueError
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return "必须是 ISO 日期时间"
        if value_type == "period" and (not isinstance(value, str) or not _PERIOD.fullmatch(value)):
            return "必须是 YYYY-MM"
        if value_type == "money":
            if not isinstance(value, dict) or set(value) != {"amount", "currency"}:
                return "必须包含 amount 和 currency"
            amount = value.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                return "amount 必须是数字"
            if not isinstance(value.get("currency"), str) or not re.fullmatch(r"[A-Z]{3}", value["currency"]):
                return "currency 必须是三位 ISO 币种"
        if value_type == "json":
            try:
                self.workspace._digest(value)
            except (TypeError, ValueError):
                return "必须是 JSON 值"
        return ""

    def _compile_effects(
        self,
        effects: list[dict[str, Any]],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        created: dict[str, str] = {}
        operations = []
        for effect in effects:
            if "create_object" in effect:
                definition = effect["create_object"]
                object_id = f"{definition['type']}:{uuid4()}"
                record = {
                    "id": object_id,
                    "type": definition["type"],
                    "name": self._resolve(definition["name"], inputs, context, created),
                }
                for field in ("properties", "tags"):
                    resolved = self._resolve(definition.get(field, _MISSING), inputs, context, created)
                    if resolved is not _MISSING and resolved not in ({}, []):
                        record[field] = resolved
                operations.append({"action": "create_object", "record": record})
                created[definition["ref"]] = object_id
                continue
            if "update_object" in effect:
                definition = effect["update_object"]
                record_id = self._resolve(definition["id"], inputs, context, created)
                changes = self._resolve(definition.get("changes", {}), inputs, context, created)
                if record_id is _MISSING:
                    continue
                operations.append({
                    "action": "update_object",
                    "id": record_id,
                    "changes": changes,
                })
                continue
            definition = effect["create_relation"]
            relation_id = f"rel:{definition['type']}:{uuid4()}"
            from_id = self._resolve(definition["from"], inputs, context, created)
            to_id = self._resolve(definition["to"], inputs, context, created)
            if from_id is _MISSING or to_id is _MISSING:
                continue
            record = {
                "id": relation_id,
                "type": definition["type"],
                "from": from_id,
                "to": to_id,
            }
            for field in ("properties", "tags"):
                resolved = self._resolve(definition.get(field, _MISSING), inputs, context, created)
                if resolved is not _MISSING and resolved not in ({}, []):
                    record[field] = resolved
            operations.append({"action": "create_relation", "record": record})
        return operations

    def _resolve(
        self,
        value: Any,
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
        created: dict[str, str],
    ) -> Any:
        if value is _MISSING:
            return _MISSING
        if isinstance(value, str) and value.startswith("$"):
            if value == "$context":
                return context["id"] if context else _MISSING
            if value.startswith("$input."):
                input_id = value[7:]
                return deepcopy(inputs[input_id]) if input_id in inputs else _MISSING
            return created.get(value[1:], _MISSING)
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                resolved = self._resolve(item, inputs, context, created)
                if resolved is not _MISSING:
                    result[key] = resolved
            return result
        if isinstance(value, list):
            result = []
            for item in value:
                resolved = self._resolve(item, inputs, context, created)
                if resolved is not _MISSING:
                    result.append(resolved)
            return result
        return deepcopy(value)

    @staticmethod
    def _action_summary(action_id: str, definition: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": action_id,
            "name": definition.get("name"),
            "description": definition.get("description"),
            "icon": definition.get("icon"),
        }

    @staticmethod
    def _action_form_definition(
        action_id: str,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        result = {
            "id": action_id,
            "name": definition.get("name"),
            "description": definition.get("description"),
            "icon": definition.get("icon"),
            "inputs": deepcopy(definition.get("inputs", {})),
        }
        if "available_on" in definition:
            result["available_on"] = deepcopy(definition["available_on"])
        if "context_input" in definition:
            result["context_input"] = definition["context_input"]
        if "requires" in definition:
            result["requires"] = deepcopy(definition["requires"])
        return result
