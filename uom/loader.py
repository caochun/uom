"""Load an OAG-native domain with the UOM graph and Action runtime."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from oag.ontology.bindings import RuntimeBindings
from oag.ontology.loader import load_domain as load_oag_domain
from oag.ontology.repository import OntologyRepository
from oag.ontology.schema import Ontology

from uom.actions import ModelActionService
from uom.change_store import UomChangeStore
from uom.provider import UomDomainProvider
from uom.workspace import UomWorkspaceService


@dataclass(frozen=True)
class UomDomainRuntime:
    ontology: Ontology
    repository: OntologyRepository
    bindings: RuntimeBindings
    workspace: UomWorkspaceService
    change_store: UomChangeStore
    actions: ModelActionService

    def __iter__(self) -> Iterator[object]:
        """Retain tuple unpacking for callers that only need OAG components."""
        yield self.ontology
        yield self.repository
        yield self.bindings


def load_domain(domain_dir: str | Path):
    domain_dir = Path(domain_dir).resolve()
    provider = _load_extension_provider(domain_dir) or UomDomainProvider(domain_dir)
    ontology, repository, bindings = load_oag_domain(provider)
    uom_provider = getattr(provider, "uom", provider)
    workspace = getattr(uom_provider, "workspace", None)
    change_store = getattr(uom_provider, "change_store", None)
    actions = getattr(uom_provider, "actions", None)
    if workspace is None or change_store is None or actions is None:
        repository.close()
        raise RuntimeError("UOM provider did not expose its runtime services")
    return UomDomainRuntime(
        ontology=ontology,
        repository=repository,
        bindings=bindings,
        workspace=workspace,
        change_store=change_store,
        actions=actions,
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
