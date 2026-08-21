"""Load an OAG-native domain with the UOM graph and Action runtime."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.registry import FunctionRegistry
from oag.ontology.repository import OntologyRepository

from uom.provider import UomDomainProvider


def load_domain(domain_dir: str | Path):
    domain_dir = Path(domain_dir).resolve()
    provider = _load_extension_provider(domain_dir) or UomDomainProvider(domain_dir)
    ontology = provider.load_ontology()
    registry = FunctionRegistry()
    repository = OntologyRepository(ontology, registry)
    provider.register(DomainContext(
        domain_dir=domain_dir,
        ontology=ontology,
        registry=registry,
        repository=repository,
    ))
    missing = [name for name in ontology.functions if not registry.has(name)]
    if missing:
        repository.close()
        raise ValueError(
            "UOM function implementations are missing: " + ", ".join(sorted(missing))
        )
    return ontology, repository, registry


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
