"""Highway application adapter for session-level UOM domain routing."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from uom.routing import DomainRouter, DomainSelection


DEFAULT_DOMAIN_ID = "highway.passage_charging"


@dataclass
class _AgentBundle:
    domain_ids: tuple[str, ...]
    runtime: Any
    agent: Any


class OagAgentRuntime:
    """Keep the workbench runtime stable while routing Agent sessions by domain."""

    def __init__(self, root: str | Path, domain_dir: str | Path | None = None):
        self.root = Path(root).resolve()
        configured_domain = domain_dir or os.environ.get("UOM_DOMAIN_DIR", "highway")
        configured_path = Path(configured_domain)
        self.domain_dir = (
            configured_path if configured_path.is_absolute()
            else self.root / configured_path
        ).resolve()
        self.registry = None
        self.runtime_manager = None
        self.router: DomainRouter | None = None
        self.runtime = None
        self.workbench_runtime = None
        self.domain_ids: list[str] = []
        self.ontology = None
        self.repository = None
        self.bindings = None
        self.workspace = None
        self.actions = None
        self._agent = None
        self._agents: dict[tuple[str, ...], _AgentBundle] = {}
        self._action_preview_domains: dict[str, tuple[str, ...]] = {}
        self._client = None
        self._model = ""
        self._disable_reasoning = False
        self._error = ""
        self._lock = threading.RLock()
        self._configure_runtime()
        self._configure_llm()

    def _configure_runtime(self) -> None:
        try:
            from uom.loader import UomRuntimeManager
            from uom.registry import DomainRegistry

            registry = DomainRegistry.discover(self.domain_dir)
            configured_paths = _configured_paths(self.root)
            for path in configured_paths:
                if not any(item.path == path for item in registry.list()):
                    registry.register(path, domain_id=_domain_id_for_path(self.domain_dir, path))
            selected_ids = _configured_domain_ids(registry, configured_paths)
            if not selected_ids:
                available_ids = [descriptor.id for descriptor in registry.list()]
                selected_ids = [
                    DEFAULT_DOMAIN_ID
                    if DEFAULT_DOMAIN_ID in available_ids
                    else available_ids[0]
                ]
            runtime_manager = UomRuntimeManager(
                registry,
                expose_actions=False,
            )
            runtime = runtime_manager.load(selected_ids)
            all_domain_ids = [descriptor.id for descriptor in registry.list()]
            workbench_runtime = runtime_manager.load(all_domain_ids)
            self.registry = registry
            self.runtime_manager = runtime_manager
            self.router = DomainRouter(registry, default_ids=selected_ids)
            self.runtime = runtime
            self.workbench_runtime = workbench_runtime
            self.domain_ids = selected_ids
            self._set_workbench_runtime(workbench_runtime)
        except Exception as exc:
            self._error = f"UOM domain 初始化失败: {exc}"

    def _set_workbench_runtime(self, runtime: Any) -> None:
        self.ontology = runtime.ontology
        self.repository = runtime.repository
        self.bindings = runtime.bindings
        self.workspace = runtime.workspace
        self.actions = runtime.actions
        if self.actions is None:
            raise RuntimeError("UOM Action service 未注册")

    def _configure_llm(self) -> None:
        if self.runtime is None:
            return
        model = (
            os.environ.get("OAG_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("LLM_MODEL")
        )
        base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_API_URL")
        api_key = (
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or ("local" if base_url else None)
        )
        if not model:
            self._error = "未配置 OAG_MODEL、OPENAI_MODEL 或 LLM_MODEL"
            return
        if not api_key:
            self._error = "未配置 OPENAI_API_KEY 或 LLM_API_KEY"
            return
        try:
            from openai import OpenAI

            client_args: dict[str, Any] = {"api_key": api_key}
            if base_url:
                client_args["base_url"] = base_url
            self._client = OpenAI(**client_args)
            self._model = model
            self._disable_reasoning = _is_truthy(os.environ.get("LLM_DISABLE_REASONING"))
            self._agent = self._bundle_for(self.domain_ids).agent
        except Exception as exc:  # The workbench remains usable without an LLM.
            self._client = None
            self._error = f"OAG Agent 初始化失败: {exc}"

    def _bundle_for(self, domain_ids: Iterable[str]) -> _AgentBundle:
        ids = tuple(dict.fromkeys(str(domain_id) for domain_id in domain_ids))
        current = self._agents.get(ids)
        if current is not None:
            return current
        if self.runtime_manager is None:
            raise RuntimeError(self._error or "UOM domain 未初始化")
        runtime = self.runtime_manager.load(ids)
        agent = self._build_agent(runtime, ids) if self._client is not None else None
        bundle = _AgentBundle(ids, runtime, agent)
        self._agents[ids] = bundle
        return bundle

    def _build_agent(self, runtime: Any, domain_ids: tuple[str, ...]):
        from oag.agent import Agent
        from oag.harness import Harness
        from oag.runtime import HarnessConfig

        harness = Harness(
            ontology=runtime.ontology,
            repository=runtime.repository,
            bindings=runtime.bindings,
            llm_client=self._client,
            model=self._model,
            config=HarnessConfig(
                enable_write_confirmation=True,
                max_turns=8,
                runtime_context={
                    "surface": "Highway OMS",
                    "domains": ", ".join(domain_ids),
                },
                llm_extra_body=(
                    {"chat_template_kwargs": {"enable_thinking": False}}
                    if self._disable_reasoning
                    else {}
                ),
                append_system_prompt="/no_think" if self._disable_reasoning else "",
            ),
        )
        return Agent(
            harness,
            self._client,
            model=self._model,
            db_dir=str(self.root / ".oag_data"),
        )

    # Workbench reads use the full composed runtime; writes are routed below.
    def bootstrap(self, include_graph: bool = True) -> dict[str, Any]:
        if self.workspace is None:
            raise RuntimeError(self._error or "UOM domain 未初始化")
        result = self.workspace.bootstrap(include_graph=include_graph)
        actions: dict[str, Any] = {}
        for descriptor in self.registry.list() if self.registry is not None else ():
            model = self._bundle_for((descriptor.id,)).runtime.workspace.load_model()
            for action_id, definition in model.get("actions", {}).items():
                item = dict(definition)
                item["domain_ids"] = [descriptor.id]
                actions[action_id] = item
        result["model"]["actions"] = actions
        result["domains"] = self.domain_catalog()
        result["domain_ownership"] = self._domain_ownership()
        return result

    def call_domain(self, name: str, **kwargs: Any) -> Any:
        if self.bindings is None:
            raise RuntimeError(self._error or "UOM domain 未初始化")
        return self.bindings.call(name, **kwargs)

    def preview_changes(
        self,
        operations: list[dict[str, Any]],
        domain_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        ids = self._change_domains(operations, domain_ids)
        result = self._bundle_for(ids).runtime.workspace.preview_changes(operations)
        result["domain_ids"] = list(ids)
        return result

    def apply_changes(
        self,
        *,
        operations: list[dict[str, Any]],
        domain_ids: Iterable[str] = (),
        **kwargs: Any,
    ) -> Any:
        ids = self._change_domains(operations, domain_ids)
        return self._bundle_for(ids).runtime.workspace.apply_changes(
            operations=operations,
            **kwargs,
        )

    # Domain-aware Action operations are used when an Agent from a child
    # domain opens a UI form. Preview tokens remember their source runtime.
    def list_actions(
        self,
        context_id: str = "",
        domain_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        explicit_ids = tuple(dict.fromkeys(str(item) for item in domain_ids if str(item)))
        if explicit_ids:
            result = self._actions_for(explicit_ids).list_actions(context_id=context_id)
            for action in result.get("actions", []):
                action["domain_ids"] = list(explicit_ids)
            return result

        actions: list[dict[str, Any]] = []
        context = None
        for descriptor in self.registry.list() if self.registry is not None else ():
            result = self._bundle_for((descriptor.id,)).runtime.actions.list_actions(
                context_id=context_id,
            )
            if context is None and result.get("context") is not None:
                context = result["context"]
            for action in result.get("actions", []):
                item = dict(action)
                item["domain_ids"] = [descriptor.id]
                actions.append(item)
        return {"context": context, "actions": actions}

    def preview_action(
        self,
        *,
        action_id: str,
        inputs: dict[str, Any],
        context_id: str = "",
        domain_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        ids = self._action_domains(action_id, domain_ids)
        result = self._bundle_for(ids).runtime.actions.preview_action(
            action_id=action_id,
            inputs=inputs,
            context_id=context_id,
        )
        token = result.get("preview_token")
        if token:
            self._action_preview_domains[str(token)] = ids
        return result

    def execute_action(
        self,
        *,
        preview_token: str,
        reason: str = "",
        actor: str = "web_user",
        channel: str = "ui",
        domain_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        ids = self._action_preview_domains.get(preview_token)
        if ids is None:
            ids = self._normalize_domain_ids(domain_ids)
        result = self._bundle_for(ids).runtime.actions.execute_action(
            preview_token=preview_token,
            reason=reason,
            actor=actor,
            channel=channel,
        )
        self._action_preview_domains.pop(preview_token, None)
        return result

    def _actions_for(self, domain_ids: Iterable[str]):
        ids = self._normalize_domain_ids(domain_ids)
        return self._bundle_for(ids).runtime.actions

    def _normalize_domain_ids(self, domain_ids: Iterable[str]) -> tuple[str, ...]:
        ids = tuple(dict.fromkeys(str(item) for item in domain_ids if str(item)))
        return ids or tuple(self.domain_ids)

    def _action_domains(
        self,
        action_id: str,
        domain_ids: Iterable[str],
    ) -> tuple[str, ...]:
        explicit = tuple(dict.fromkeys(str(item) for item in domain_ids if str(item)))
        if explicit:
            if len(explicit) != 1:
                raise ValueError("业务操作必须属于一个领域")
            descriptor = self.registry.resolve(explicit)[0] if self.registry is not None else None
            if descriptor is None or action_id not in descriptor.actions:
                raise ValueError(f"业务操作 {action_id} 不属于领域 {explicit[0]}")
            return explicit
        owners = [
            descriptor.id
            for descriptor in self.registry.list() if self.registry is not None
            if action_id in descriptor.actions
        ]
        if len(owners) != 1:
            raise ValueError(
                f"业务操作 {action_id} 无法确定唯一所属领域，请明确选择领域"
            )
        return (owners[0],)

    def _change_domains(
        self,
        operations: list[dict[str, Any]],
        domain_ids: Iterable[str],
    ) -> tuple[str, ...]:
        explicit = tuple(dict.fromkeys(str(item) for item in domain_ids if str(item)))
        if explicit:
            if len(explicit) != 1:
                raise ValueError("当前 MVP 的数据或模型变更必须属于一个领域")
            if self.registry is not None:
                self.registry.resolve(explicit)
            inferred = self._infer_change_owners(operations)
            if inferred and explicit[0] not in inferred:
                raise ValueError(
                    f"变更中的业务类型不属于领域 {explicit[0]}，可选领域: "
                    + ", ".join(inferred)
                )
            return explicit
        owners = self._infer_change_owners(operations)
        if len(owners) != 1:
            raise ValueError("无法确定变更所属领域，请在编辑表单中明确选择领域")
        return tuple(owners)

    def _infer_change_owners(self, operations: list[dict[str, Any]]) -> list[str]:
        from uom.model import load_yaml_mapping

        referenced_types: set[tuple[str, str]] = set()
        for operation in operations or []:
            action = str(operation.get("action", ""))
            record = operation.get("record") or {}
            if action == "create_object" and isinstance(record, dict):
                referenced_types.add(("objects", str(record.get("type", ""))))
            elif action == "create_relation" and isinstance(record, dict):
                referenced_types.add(("relations", str(record.get("type", ""))))
            elif action.startswith("upsert_"):
                return []
            elif action in {
                "update_object", "delete_object", "update_relation", "delete_relation",
            }:
                kind = "object" if action.endswith("object") else "relation"
                record_id = str(operation.get("id", ""))
                page = self.workspace.query_records(
                    kind,
                    filters={"id": record_id},
                    limit=1,
                )
                matches = page.get("records", [])
                if matches:
                    referenced_types.add((f"{kind}s", str(matches[0].get("type", ""))))
        candidates: set[str] | None = None
        for section, type_id in referenced_types:
            owners = {
                descriptor.id
                for descriptor in self.registry.list() if self.registry is not None
                if type_id in (load_yaml_mapping(descriptor.path / "model.yaml").get(section) or {})
            }
            candidates = owners if candidates is None else candidates & owners
        return sorted(candidates or ())

    def _domain_ownership(self) -> dict[str, dict[str, list[str]]]:
        from uom.model import load_yaml_mapping

        ownership = {"objects": {}, "relations": {}, "actions": {}}
        for descriptor in self.registry.list() if self.registry is not None else ():
            model = load_yaml_mapping(descriptor.path / "model.yaml")
            for section in ownership:
                for type_id in (model.get(section) or {}):
                    ownership[section].setdefault(type_id, []).append(descriptor.id)
        return ownership

    # Domain catalog and session routing.
    def domain_catalog(self) -> list[dict[str, object]]:
        if self.registry is None:
            return []
        return [_public_descriptor(item.model_dump()) for item in self.registry.list()]

    def match_domains(self, intent: str, *, limit: int | None = None) -> list[dict[str, object]]:
        if self.registry is None:
            return []
        matches = self.registry.rank(intent)
        if limit is not None:
            matches = matches[:max(0, int(limit))]
        return [_public_descriptor(match.model_dump()) for match in matches]

    def domain_context(self, session_id: str) -> dict[str, Any]:
        if self.router is None:
            return {
                "selected": list(self.domain_ids),
                "mode": "auto",
                "locked": False,
                "domains": self.domain_catalog(),
            }
        selection = self.router.current(session_id)
        return self._selection_payload(
            selection,
            locked=self._pending_bundle(session_id) is not None,
        )

    def select_domains(
        self,
        session_id: str,
        domain_ids: Iterable[str] = (),
        *,
        automatic: bool = False,
    ) -> dict[str, Any]:
        if self.router is None:
            raise RuntimeError(self._error or "UOM domain 未初始化")
        with self._lock:
            locked = self._pending_bundle(session_id) is not None
            selection = (
                self.router.use_auto(session_id, locked=locked)
                if automatic
                else self.router.select(
                    session_id,
                    domain_ids,
                    manual=True,
                    locked=locked,
                )
            )
            self._bundle_for(selection.domain_ids)
            return self._selection_payload(selection, locked=locked)

    def status(self, session_id: str = "default") -> dict[str, Any]:
        context = self.domain_context(session_id)
        return {
            "available": self._client is not None,
            "runtime": "oag-agent",
            "message": "已连接" if self._client is not None else self._error,
            "domains": context["selected"],
            "domain_context": context,
        }

    def chat(self, message: str, session_id: str) -> Iterator[dict[str, Any]]:
        if self.router is None:
            yield {"type": "error", "message": self._error}
            return
        with self._lock:
            pending = self._pending_bundle(session_id)
            if pending is not None:
                selection = self.router.resolve(session_id, message, locked=True)
                bundle = pending
            else:
                selection = self.router.resolve(session_id, message)
                bundle = self._bundle_for(selection.domain_ids)
            yield {
                "type": "domain_context",
                **self._selection_payload(selection, locked=pending is not None),
            }
            if bundle.agent is None:
                yield {"type": "error", "message": self._error or "模型服务未配置"}
                return
            for event in bundle.agent.chat_stream_sse(message, session_id=session_id):
                event.setdefault("domain_ids", list(bundle.domain_ids))
                yield event

    def confirm(
        self,
        session_id: str,
        approved: bool,
        answer: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        from oag.runtime.events import event_to_dict

        with self._lock:
            bundle = self._pending_bundle(session_id)
            if bundle is None and self.router is not None:
                bundle = self._bundle_for(self.router.current(session_id).domain_ids)
            if bundle is None or bundle.agent is None:
                yield {"type": "error", "message": self._error or "没有待确认的 Agent 操作"}
                return
            for event in bundle.agent.confirm_tool(
                session_id,
                approved=approved,
                answer=answer,
            ):
                payload = event_to_dict(event)
                payload.setdefault("domain_ids", list(bundle.domain_ids))
                yield payload
            if self.router is not None:
                locked = self._pending_bundle(session_id) is not None
                yield {
                    "type": "domain_context",
                    **self._selection_payload(
                        self.router.current(session_id),
                        locked=locked,
                    ),
                }

    def _pending_bundle(self, session_id: str) -> _AgentBundle | None:
        for bundle in self._agents.values():
            if bundle.agent is not None and bundle.agent.has_pending(session_id):
                return bundle
        return None

    def _selection_payload(
        self,
        selection: DomainSelection,
        *,
        locked: bool,
    ) -> dict[str, Any]:
        selected = set(selection.domain_ids)
        catalog = self.domain_catalog()
        return {
            "selected": list(selection.domain_ids),
            "selected_domains": [item for item in catalog if item["id"] in selected],
            "mode": selection.mode,
            "changed": selection.changed,
            "reason": selection.reason,
            "locked": locked,
            "domains": catalog,
        }

    def close(self) -> None:
        if self.runtime_manager is not None:
            self.runtime_manager.close()
        elif self.repository is not None:
            self.repository.close()
        self._agents.clear()


def _public_descriptor(value: dict[str, object]) -> dict[str, object]:
    public_fields = (
        "id",
        "name",
        "version",
        "description",
        "match_score",
        "matched_terms",
    )
    return {field: value[field] for field in public_fields if field in value}


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _configured_paths(root: Path) -> list[Path]:
    return [
        (Path(value) if Path(value).is_absolute() else root / value).resolve()
        for value in _csv(os.environ.get("UOM_DOMAIN_DIRS"))
    ]


def _configured_domain_ids(registry, configured_paths: list[Path] | None = None) -> list[str]:
    ids = _csv(os.environ.get("UOM_DOMAIN_IDS"))
    if ids:
        registry.resolve(ids)
        return ids
    paths = list(configured_paths or [])
    if not paths:
        return []
    by_path = {descriptor.path: descriptor.id for descriptor in registry.list()}
    missing = [path for path in paths if path not in by_path]
    if missing:
        raise ValueError("UOM_DOMAIN_DIRS 中的路径未注册: " + ", ".join(map(str, missing)))
    return [by_path[path] for path in paths]


def _domain_id_for_path(primary: Path, path: Path) -> str:
    if path == primary:
        return primary.name
    try:
        relative = path.relative_to(primary)
    except ValueError:
        return path.name
    if len(relative.parts) >= 2 and relative.parts[0] == "domains":
        return f"{primary.name}.{relative.parts[1]}"
    return path.name
