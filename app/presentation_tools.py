"""Bind OMS presentation tools to the OAG frontend surface."""

from __future__ import annotations

import json
from typing import Any

from oag.tools.registry import ToolDef, ToolPolicy

from oms.store import ChangeValidationError


def register_presentation_tools(harness, ontology, workspace, actions) -> None:
    """Register frontend-only tools using the current OMS Action catalog."""
    definition = ontology.presentation_tools.get("ui_open_action_form")
    if definition is None:
        return

    model_actions = workspace.snapshot()["model"].get("actions", {})
    action_ids = list(model_actions)
    catalog = "；".join(
        f"{action_id}={item.get('name', action_id)}"
        for action_id, item in model_actions.items()
        if isinstance(item, dict)
    )
    description = definition.description.strip()
    if catalog:
        description += f"\n\n当前可用 action_id：{catalog}"

    harness.tools.register(ToolDef(
        name="ui_open_action_form",
        description=description,
        usage_prompt=definition.usage_prompt,
        parameters={
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "enum": action_ids,
                    "description": "model.yaml 中的业务操作 ID",
                },
                "context_id": {
                    "type": "string",
                    "description": "可选的当前业务对象 ID；只在操作依赖当前对象时提供",
                },
                "initial_inputs": {
                    "type": "object",
                    "description": "可选预填值；只包含用户已经明确给出的 Action 输入",
                },
            },
            "required": ["action_id"],
        },
        handler=lambda args: _open_action_form(actions, args),
        category=definition.category,
        max_result_chars=2000,
        policy=ToolPolicy(
            read_only=True,
            requires_confirmation=definition.requires_confirmation,
            concurrency_safe=definition.concurrency_safe,
            worker_allowed=definition.worker_allowed,
            idempotent=definition.idempotent,
            destructive=definition.destructive,
            timeout_seconds=definition.timeout_seconds,
        ),
    ))


def _open_action_form(actions, args: dict[str, Any]) -> str:
    try:
        prepared = actions.prepare_action_form(
            action_id=str(args.get("action_id", "")),
            context_id=str(args.get("context_id", "")),
            initial_inputs=args.get("initial_inputs") or {},
        )
    except ChangeValidationError as exc:
        return json.dumps({
            "error": "无法打开业务操作表单",
            "errors": exc.errors,
        }, ensure_ascii=False)
    return json.dumps({
        "message": f"已向用户打开{prepared['action']['name']}表单，等待用户填写并确认。",
        "presentation": {
            "kind": "action_form",
            **prepared,
        },
    }, ensure_ascii=False)
