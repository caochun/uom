"""Load an OAG-native domain with the UOM graph and Action runtime."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterable, Iterator

import yaml

from oag.ontology.bindings import RuntimeBindings
from oag.ontology.domain import DomainProvider
from oag.ontology.loader import load_domain as load_oag_domain
from oag.ontology.repository import OntologyRepository
from oag.ontology.schema import Ontology

from uom.actions import ModelActionService
from uom.change_store import UomChangeStore
from uom.composition import (
    ComposedActionRuntime,
    compose_domain_models,
    load_function_handlers,
)
from uom.provider import UomDomainProvider
from uom.registry import DomainRegistry
from uom.model import load_action_plans, load_domain_model
from uom.workspace import UomWorkspaceService


@dataclass
class UomDomainRuntime:
    ontology: Ontology
    repository: OntologyRepository
    bindings: RuntimeBindings
    workspace: UomWorkspaceService
    change_store: UomChangeStore
    actions: ModelActionService
    _cleanup: Callable[[], None] | None = None
    _closed: bool = False

    def __iter__(self) -> Iterator[object]:
        """Retain tuple unpacking for callers that only need OAG components."""
        yield self.ontology
        yield self.repository
        yield self.bindings

    def close(self) -> None:
        """Close the repository and release temporary composed resources."""
        if self._closed:
            return
        self._closed = True
        self.repository.close()
        if self._cleanup is not None:
            self._cleanup()
            self._cleanup = None


class UomRuntimeManager:
    """Lazily load and cache one or more domain runtimes by registry ID."""

    def __init__(self, registry: DomainRegistry, *, expose_actions: bool = False) -> None:
        self.registry = registry
        self.expose_actions = expose_actions
        self._runtimes: dict[tuple[str, ...], UomDomainRuntime] = {}

    def load(self, domain_ids: Iterable[str]) -> UomDomainRuntime:
        ids = tuple(dict.fromkeys(str(domain_id) for domain_id in domain_ids))
        if not ids:
            raise ValueError("至少需要一个领域 ID")
        if ids in self._runtimes:
            return self._runtimes[ids]
        descriptors = self.registry.resolve(ids)
        if len(descriptors) == 1:
            runtime = load_domain(descriptors[0].path)
        else:
            runtime = load_composed_domain(
                (descriptor.path for descriptor in descriptors),
                expose_actions=self.expose_actions,
            )
        self._runtimes[ids] = runtime
        return runtime

    def load_for_intent(
        self,
        intent: str,
        *,
        fallback_ids: Iterable[str] = (),
        limit: int | None = 1,
    ) -> UomDomainRuntime:
        matches = self.registry.match(intent, limit=limit)
        ids = [descriptor.id for descriptor in matches]
        if not ids:
            ids = [str(domain_id) for domain_id in fallback_ids]
        if not ids:
            raise ValueError("无法根据意图匹配领域，且没有默认领域")
        return self.load(ids)

    @property
    def loaded_domain_sets(self) -> list[tuple[str, ...]]:
        return list(self._runtimes)

    def close(self) -> None:
        for runtime in self._runtimes.values():
            runtime.close()
        self._runtimes.clear()


def load_domain(domain_dir: str | Path) -> UomDomainRuntime:
    domain_dir = Path(domain_dir).resolve()
    provider = _load_extension_provider(domain_dir) or UomDomainProvider(domain_dir)
    return _load_runtime(provider)


def load_composed_domain(
    domain_dirs: Iterable[str | Path],
    *,
    expose_actions: bool = False,
) -> UomDomainRuntime:
    """Load one runtime spanning multiple domains.

    The default is read-only.  ``expose_actions`` routes previews and commits
    to the original domain runtimes rather than writing through the temporary
    combined model.
    """
    roots: list[Path] = []
    seen: set[Path] = set()
    for domain_dir in domain_dirs:
        root = Path(domain_dir).resolve()
        if root not in seen:
            roots.append(root)
            seen.add(root)
    composed = compose_domain_models(roots, include_actions=expose_actions)
    handlers: dict[str, Callable] = {}
    for domain_dir in roots:
        for name, handler in load_function_handlers(domain_dir).items():
            if name in handlers and handlers[name] is not handler:
                raise ValueError(f"组合领域 Function 实现冲突: {name}")
            handlers[name] = handler

    source_runtimes: dict[str, UomDomainRuntime] = {}
    action_owners: dict[str, str] = {}
    action_plans: dict[str, Any] = {"schema": "uom.action_plans.v1", "actions": {}}
    if expose_actions:
        try:
            for domain_dir in roots:
                source_runtime = load_domain(domain_dir)
                source_runtimes[str(domain_dir)] = source_runtime
                _, source_model = load_domain_model(domain_dir)
                source_plans = load_action_plans(domain_dir).get("actions", {})
                for action_id in source_model.actions:
                    action_owners.setdefault(action_id, str(domain_dir))
                    if action_id in source_plans and action_id not in action_plans["actions"]:
                        action_plans["actions"][action_id] = source_plans[action_id]
        except Exception:
            for source_runtime in source_runtimes.values():
                source_runtime.close()
            raise

    payload = composed.model_dump(by_alias=True)
    for definition in payload["repositories"].values():
        definition["mode"] = "read_only"
    temp_dir = TemporaryDirectory(prefix="uom-composed-")
    root = Path(temp_dir.name)
    try:
        (root / "model.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (root / "action_plans.yaml").write_text(
            yaml.safe_dump(
                action_plans,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        action_runtime_factory = None
        if expose_actions:
            action_runtime_factory = lambda _workspace: ComposedActionRuntime(
                source_runtimes, action_owners,
            )
        provider = UomDomainProvider(
            root,
            function_handlers=handlers,
            action_runtime_factory=action_runtime_factory,
        )

        def cleanup() -> None:
            for source_runtime in source_runtimes.values():
                source_runtime.close()
            temp_dir.cleanup()

        return _load_runtime(provider, cleanup=cleanup)
    except Exception:
        for source_runtime in source_runtimes.values():
            source_runtime.close()
        temp_dir.cleanup()
        raise


def _load_runtime(
    provider: DomainProvider,
    *,
    cleanup: Callable[[], None] | None = None,
) -> UomDomainRuntime:
    ontology, repository, bindings = load_oag_domain(provider)
    uom_provider = getattr(provider, "uom", provider)
    workspace = getattr(uom_provider, "workspace", None)
    change_store = getattr(uom_provider, "change_store", None)
    actions = getattr(uom_provider, "actions", None)
    if workspace is None or change_store is None or actions is None:
        repository.close()
        if cleanup is not None:
            cleanup()
        raise RuntimeError("UOM provider did not expose its runtime services")
    return UomDomainRuntime(
        ontology=ontology,
        repository=repository,
        bindings=bindings,
        workspace=workspace,
        change_store=change_store,
        actions=actions,
        _cleanup=cleanup,
    )


def _load_extension_provider(domain_dir: Path):
    source_path = domain_dir / "provider.py"
    if not source_path.is_file():
        return None
    module_name = f"_uom_domain_{domain_dir.name}_provider"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import UOM domain provider: {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    factory = getattr(module, "create_domain", None)
    if not callable(factory):
        raise ValueError(f"UOM domain provider factory not found: {source_path}:create_domain")
    provider = factory(domain_dir)
    if not callable(getattr(provider, "load_ontology", None)):
        raise TypeError("UOM domain provider must define load_ontology")
    if not callable(getattr(provider, "register", None)):
        raise TypeError("UOM domain provider must define register")
    return provider
