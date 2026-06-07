from __future__ import annotations

from oag.ontology.registry import FunctionRegistry
from oag.ontology.repository import ObjectRepository
from oag.ontology.schema import Ontology

from .runtime import register as register_runtime


def register(registry: FunctionRegistry, store: ObjectRepository, ontology: Ontology):
    register_runtime(registry, store, ontology)
