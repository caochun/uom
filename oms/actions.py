"""Model-driven business actions compiled to validated OMS ChangeSets."""

from __future__ import annotations

import re
import threading
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from oms.store import ChangeValidationError, OmsWorkspaceService


_MISSING = object()
_PERIOD = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")


class OmsActionService:
    """Resolve the small action DSL in model.yaml into ordinary ChangeSets."""

    def __init__(self, workspace: OmsWorkspaceService):
        self.workspace = workspace
        self._previews: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def get_available_actions(self, context_id: str = "") -> dict[str, Any]:
        model = self.workspace.snapshot()["model"]
        context = self._context(context_id) if context_id else None
        actions = []
        for action_id, definition in model.get("actions", {}).items():
            available_on = definition.get("available_on")
            if available_on is not None:
                if context is None:
                    continue
                if "*" not in available_on and context.get("type") not in available_on:
                    continue
            actions.append({"id": action_id, **deepcopy(definition)})
        return {"context": context, "actions": actions}

    def prepare_action_form(
        self,
        action_id: str,
        initial_inputs: dict[str, Any] | None = None,
        context_id: str = "",
    ) -> dict[str, Any]:
        """Validate a UI handoff without requiring the action's missing inputs."""
        with self._lock:
            model = self.workspace.snapshot()["model"]
            definition = model.get("actions", {}).get(action_id)
            if not isinstance(definition, dict):
                raise ChangeValidationError([f"action: 未知业务操作 {action_id}"])
            context = self._validate_context(definition, context_id)
            prepared_inputs = self._validate_partial_inputs(
                definition.get("inputs", {}),
                initial_inputs or {},
                model,
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
            model = self.workspace.snapshot()["model"]
            definition = model.get("actions", {}).get(action_id)
            if not isinstance(definition, dict):
                raise ChangeValidationError([f"action: 未知业务操作 {action_id}"])
            context = self._validate_context(definition, context_id)
            resolved_inputs = self._validate_inputs(
                definition.get("inputs", {}),
                inputs or {},
                model,
            )
            operations = self._compile_effects(
                definition.get("effects", []),
                resolved_inputs,
                context,
            )
            preview = self.workspace.preview_changes(operations)
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

    def apply_action(
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

    def _context(self, context_id: str) -> dict[str, Any]:
        context = self.workspace.repository.query_by_id("Object", context_id)
        if not context:
            raise ChangeValidationError([f"action.context_id: 未找到对象 {context_id}"])
        return context

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
            record = self.workspace.repository.query_by_id("Object", value)
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
            definition = effect["create_relation"]
            relation_id = f"rel:{definition['type']}:{uuid4()}"
            record = {
                "id": relation_id,
                "type": definition["type"],
                "from": self._resolve(definition["from"], inputs, context, created),
                "to": self._resolve(definition["to"], inputs, context, created),
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
        return result
