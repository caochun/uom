"""Compose several UOM domain models into one read-oriented vocabulary.

Composition belongs to UOM.  OAG receives only the resulting ontology and
does not need to know which source domains contributed a type or function.
"""

from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from uom.model import load_domain_model
from uom.schema import DomainModel


class ComposedActionRuntime:
    """Route a combined Action catalog to its owning domain runtime."""

    def __init__(self, runtimes: dict[str, Any], owners: dict[str, str]) -> None:
        self._runtimes = runtimes
        self._owners = owners
        self._previews: dict[str, tuple[str, str]] = {}

    def _runtime_for(self, action_id: str):
        domain_id = self._owners.get(action_id)
        if domain_id is None:
            raise ValueError(f"组合领域 Action 未找到所属领域: {action_id}")
        runtime = self._runtimes.get(domain_id)
        if runtime is None:
            raise ValueError(f"组合领域 Action 运行时未加载: {domain_id}")
        return domain_id, runtime.actions

    def list_actions(self, context_id: str = "") -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        context = None
        for action_id, domain_id in self._owners.items():
            runtime = self._runtimes[domain_id]
            result = runtime.actions.list_actions(context_id=context_id)
            if context is None:
                context = result.get("context")
            actions.extend(
                item for item in result.get("actions", [])
                if item.get("action_id") == action_id
                or item.get("id") == action_id
            )
        return {"context": context, "actions": actions}

    def prepare_action(
        self,
        action_id: str,
        context_id: str = "",
        initial_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _, actions = self._runtime_for(action_id)
        return actions.prepare_action(
            action_id=action_id,
            context_id=context_id,
            initial_inputs=initial_inputs or {},
        )

    def preview_action(
        self,
        action_id: str,
        inputs: dict[str, Any] | None = None,
        context_id: str = "",
    ) -> dict[str, Any]:
        domain_id, actions = self._runtime_for(action_id)
        result = actions.preview_action(
            action_id=action_id,
            inputs=inputs or {},
            context_id=context_id,
        )
        token = result.get("preview_token")
        if token:
            composed_token = f"composed:{uuid4()}"
            self._previews[composed_token] = (domain_id, str(token))
            result = deepcopy(result)
            result["preview_token"] = composed_token
        return result

    def execute_action(
        self,
        preview_token: str,
        reason: str = "",
        actor: str = "",
        channel: str = "",
    ) -> dict[str, Any]:
        source = self._previews.get(preview_token)
        if source is None:
            raise ValueError("组合领域 Action 预览已失效，请重新预览")
        domain_id, source_token = source
        result = self._runtimes[domain_id].actions.execute_action(
            preview_token=source_token,
            reason=reason,
            actor=actor,
            channel=channel,
        )
        self._previews.pop(preview_token, None)
        return result


def compose_domain_models(
    domain_dirs: Iterable[str | Path],
    *,
    include_actions: bool = True,
) -> DomainModel:
    """Merge validated domain models into one validated UOM model.

    Domains may repeat shared vocabulary imported from a contract.  Repeated
    definitions are merged rather than duplicated.  Structural conflicts are
    rejected so a combined Agent never receives ambiguous semantics.
    """

    roots = _unique_roots(domain_dirs)
    if not roots:
        raise ValueError("至少需要一个领域目录")

    models = [load_domain_model(root)[1] for root in roots]
    result: dict[str, Any] = {
        "schema": "uom.domain.v1",
        "name": "、".join(model.name for model in models),
        "version": "+".join(model.version for model in models),
        "description": "；".join(
            dict.fromkeys(model.description for model in models if model.description)
        ),
        "imports": [],
        "repositories": {},
        "default_repository": "",
        "properties": {},
        "objects": {},
        "relations": {},
        "functions": {},
        "actions": {},
        "agent": {
            "instructions": [],
            "excluded_tools": [],
        },
    }

    for root, model in zip(roots, models):
        payload = model.model_dump(by_alias=True)
        repository_map = _merge_repositories(
            result["repositories"], payload["repositories"], root,
        )
        default_repository = payload["default_repository"]
        mapped_default = repository_map[default_repository]
        if not result["default_repository"]:
            result["default_repository"] = mapped_default

        _merge_properties(result["properties"], payload["properties"], root)
        _merge_types(
            result["objects"], payload["objects"], root, kind="object",
            repository_map=repository_map,
            source_default=repository_map[default_repository],
        )
        _merge_types(
            result["relations"], payload["relations"], root, kind="relation",
            repository_map=repository_map,
            source_default=repository_map[default_repository],
        )
        _merge_capabilities(result["functions"], payload["functions"], root, "function")
        if include_actions:
            _merge_capabilities(result["actions"], payload["actions"], root, "action")

        agent = payload.get("agent") or {}
        result["agent"]["instructions"] = _unique_strings(
            [*result["agent"]["instructions"], *(agent.get("instructions") or [])]
        )
        result["agent"]["excluded_tools"] = _unique_strings(
            [*result["agent"]["excluded_tools"], *(agent.get("excluded_tools") or [])]
        )

    # A composed model is a materialized vocabulary, so source-level contract
    # imports must not be resolved relative to a temporary directory later.
    return DomainModel.model_validate(result)


def _unique_roots(domain_dirs: Iterable[str | Path]) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for value in domain_dirs:
        root = Path(value).resolve()
        if root in seen:
            continue
        if not (root / "model.yaml").is_file():
            raise FileNotFoundError(f"UOM domain model not found: {root / 'model.yaml'}")
        roots.append(root)
        seen.add(root)
    return roots


def _merge_repositories(
    target: dict[str, Any],
    incoming: dict[str, Any],
    domain_dir: Path,
) -> dict[str, str]:
    repository_map: dict[str, str] = {}
    for name, raw_definition in incoming.items():
        definition = deepcopy(raw_definition)
        definition["config"] = _normalize_repository_config(
            definition.get("type", ""), definition.get("config") or {}, domain_dir,
        )
        candidate = str(name)
        existing = target.get(candidate)
        if existing is not None and not _same_repository(existing, definition):
            base = f"{domain_dir.name}_{name}"
            candidate = base
            suffix = 2
            while candidate in target and not _same_repository(target[candidate], definition):
                candidate = f"{base}_{suffix}"
                suffix += 1
        if candidate not in target:
            target[candidate] = definition
        repository_map[str(name)] = candidate
    return repository_map


def _normalize_repository_config(
    repository_type: str,
    config: dict[str, Any],
    domain_dir: Path,
) -> dict[str, Any]:
    result = deepcopy(config)
    if repository_type == "sqlite_graph":
        key = next((item for item in ("database", "db_path", "path") if item in result), None)
        if key is not None and result[key] is not None:
            path = Path(str(result[key]))
            result["database"] = str(path.resolve() if path.is_absolute() else (domain_dir / path).resolve())
            if key != "database":
                result.pop(key, None)
    return result


def _same_repository(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("type") == right.get("type")
        and left.get("mode", "read_only") == right.get("mode", "read_only")
        and (left.get("config") or {}) == (right.get("config") or {})
    )


def _merge_properties(target: dict[str, Any], incoming: dict[str, Any], domain_dir: Path) -> None:
    for name, definition in incoming.items():
        current = target.get(name)
        if current is None:
            target[name] = deepcopy(definition)
            continue
        if current.get("type", "string") != definition.get("type", "string"):
            raise ValueError(
                f"组合领域属性 {name} 类型冲突: {domain_dir} 使用 {definition.get('type')}，"
                f"已存在 {current.get('type')}"
            )
        current_default = current.get("default")
        incoming_default = definition.get("default")
        if (
            current_default is not None
            and incoming_default is not None
            and current_default != incoming_default
        ):
            raise ValueError(
                f"组合领域属性 {name} 默认值冲突: {domain_dir} 使用 {incoming_default}，"
                f"已存在 {current_default}"
            )
        if current_default is None and incoming_default is not None:
            current["default"] = deepcopy(incoming_default)
        if current.get("name") and definition.get("name") and current["name"] != definition["name"]:
            current["aliases"] = _unique_strings(
                [*(current.get("aliases") or []), definition["name"]]
            )
        current["aliases"] = _unique_strings(
            [*(current.get("aliases") or []), *(definition.get("aliases") or [])]
        )
        if not current.get("description") and definition.get("description"):
            current["description"] = definition["description"]


def _merge_types(
    target: dict[str, Any],
    incoming: dict[str, Any],
    domain_dir: Path,
    *,
    kind: str,
    repository_map: dict[str, str],
    source_default: str,
) -> None:
    for type_id, raw_definition in incoming.items():
        definition = deepcopy(raw_definition)
        if definition.get("repository"):
            definition["repository"] = repository_map[str(definition["repository"])]
        else:
            definition["repository"] = source_default
        current = target.get(type_id)
        if current is None:
            target[type_id] = definition
            continue
        _ensure_type_identity(current, definition, type_id, kind, domain_dir)
        current["properties"] = _merge_property_uses(
            current.get("properties") or {}, definition.get("properties") or {},
        )
        current["aliases"] = _unique_strings(
            [*(current.get("aliases") or []), *(definition.get("aliases") or [])]
        )
        if not current.get("description") and definition.get("description"):
            current["description"] = definition["description"]
        if kind == "relation":
            current["from"] = _merge_endpoints(current.get("from") or [], definition.get("from") or [])
            current["to"] = _merge_endpoints(current.get("to") or [], definition.get("to") or [])
            current["acyclic"] = bool(current.get("acyclic") or definition.get("acyclic"))


def _ensure_type_identity(
    current: dict[str, Any],
    incoming: dict[str, Any],
    type_id: str,
    kind: str,
    domain_dir: Path,
) -> None:
    if current.get("name") and incoming.get("name") and current["name"] != incoming["name"]:
        current["aliases"] = _unique_strings(
            [*(current.get("aliases") or []), incoming["name"]]
        )
    for field in ("repository", "selector", "mapping"):
        left = current.get(field) or ({} if field in {"selector", "mapping"} else "")
        right = incoming.get(field) or ({} if field in {"selector", "mapping"} else "")
        if left != right:
            raise ValueError(
                f"组合领域{kind}类型 {type_id} 的 {field} 冲突: {domain_dir} 定义为 {right}，"
                f"已存在 {left}"
            )


def _merge_property_uses(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(left)
    for property_id, usage in right.items():
        if property_id not in result:
            result[property_id] = deepcopy(usage)
            continue
        current_required = bool((result[property_id] or {}).get("required"))
        incoming_required = bool((usage or {}).get("required"))
        result[property_id] = {"required": current_required or incoming_required}
    return result


def _merge_endpoints(left: list[str], right: list[str]) -> list[str]:
    # Empty endpoint lists mean open-ended in UOM.  One open declaration keeps
    # the composed relation open, while closed declarations are unioned.
    if not left or not right:
        return []
    return _unique_strings([*left, *right])


def _merge_capabilities(
    target: dict[str, Any],
    incoming: dict[str, Any],
    domain_dir: Path,
    kind: str,
) -> None:
    for name, definition in incoming.items():
        if name not in target:
            target[name] = deepcopy(definition)
            continue
        if kind == "action":
            if not _compatible_action(target[name], definition):
                raise ValueError(f"组合领域{kind} {name} 定义冲突: {domain_dir}")
            continue
        if target[name] != definition:
            raise ValueError(f"组合领域{kind} {name} 定义冲突: {domain_dir}")


def _compatible_action(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Allow domains to use different labels for the same action contract."""
    def structural(value: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(value)
        result.pop("name", None)
        result.pop("description", None)
        result.pop("usage_prompt", None)
        result.pop("icon", None)
        result.pop("confirmation", None)
        for definition in (result.get("inputs") or {}).values():
            if isinstance(definition, dict):
                definition.pop("name", None)
                definition.pop("description", None)
        return result

    return structural(left) == structural(right)


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value)
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def load_function_handlers(domain_dir: str | Path) -> dict[str, Any]:
    """Load Function handlers declared by an optional domain provider."""
    root = Path(domain_dir).resolve()
    source_path = root / "provider.py"
    if not source_path.is_file():
        return {}
    module_name = f"_uom_composed_{root.name}_{abs(hash(root))}_provider"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import UOM domain provider: {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    factory = getattr(module, "create_domain", None)
    if not callable(factory):
        raise ValueError(f"UOM domain provider factory not found: {source_path}:create_domain")
    provider = factory(root)
    candidate = getattr(provider, "function_handlers", None)
    if candidate is None:
        candidate = getattr(getattr(provider, "uom", None), "function_handlers", None)
    if candidate is None:
        return {}
    if not isinstance(candidate, dict):
        raise TypeError(f"UOM provider function_handlers must be a mapping: {source_path}")
    return dict(candidate)
