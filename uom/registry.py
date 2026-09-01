"""Lightweight UOM domain catalog used for discovery and lazy loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import yaml

from uom.model import load_domain_model


@dataclass(frozen=True)
class DomainDescriptor:
    """Metadata that can be shown to a router or UI without opening a runtime."""

    id: str
    path: Path
    name: str
    version: str
    description: str = ""
    object_types: tuple[str, ...] = ()
    relation_types: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()
    priority: int = 0
    action_terms: tuple[str, ...] = ()

    def model_dump(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": str(self.path),
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "object_types": list(self.object_types),
            "relation_types": list(self.relation_types),
            "functions": list(self.functions),
            "actions": list(self.actions),
            "tags": list(self.tags),
            "terms": list(self.terms),
            "priority": self.priority,
            "action_terms": list(self.action_terms),
        }


@dataclass(frozen=True)
class DomainMatch:
    """One explainable domain match for a user intent."""

    descriptor: DomainDescriptor
    score: int
    terms: tuple[str, ...]

    def model_dump(self) -> dict[str, object]:
        return {
            **self.descriptor.model_dump(),
            "match_score": self.score,
            "matched_terms": list(self.terms),
        }


class DomainRegistry:
    """Catalog of independently loadable UOM domain directories."""

    def __init__(self, descriptors: Iterable[DomainDescriptor] = ()) -> None:
        self._descriptors: dict[str, DomainDescriptor] = {}
        for descriptor in descriptors:
            self.register_descriptor(descriptor)

    @classmethod
    def discover(
        cls,
        root: str | Path,
        *,
        include_children: bool = True,
    ) -> "DomainRegistry":
        """Discover a domain or an application's immediate ``domains/*`` children.

        An application root is not required to be a domain itself.  When it has
        no ``model.yaml``, only the concrete domains below ``domains/`` are
        registered under the application namespace.
        """
        root = Path(root).resolve()
        registry = cls()
        if (root / "model.yaml").is_file():
            registry.register(root, domain_id=root.name)
        if include_children:
            children_root = root / "domains"
            if children_root.is_dir():
                for model_path in sorted(children_root.glob("*/model.yaml")):
                    child = model_path.parent
                    registry.register(
                        child,
                        domain_id=f"{root.name}.{child.name}",
                        priority=10,
                    )
        if not registry.list():
            raise ValueError(f"未发现 UOM 领域: {root}")
        return registry

    @classmethod
    def from_paths(
        cls,
        paths: Iterable[str | Path],
        *,
        ids: Iterable[str] | None = None,
    ) -> "DomainRegistry":
        paths = [Path(path).resolve() for path in paths]
        configured_ids = list(ids or ())
        if configured_ids and len(configured_ids) != len(paths):
            raise ValueError("领域 ID 数量必须与领域路径数量一致")
        registry = cls()
        for index, path in enumerate(paths):
            registry.register(
                path,
                domain_id=configured_ids[index] if configured_ids else path.name,
            )
        return registry

    def register(
        self,
        domain_dir: str | Path,
        *,
        domain_id: str | None = None,
        tags: Iterable[str] = (),
        priority: int = 0,
    ) -> DomainDescriptor:
        root = Path(domain_dir).resolve()
        _, model = load_domain_model(root)
        local_model = _load_local_model(root / "model.yaml")
        local_objects = _routing_terms(local_model.get("objects"))
        local_functions = _routing_terms(local_model.get("functions"))
        local_action_terms = _definition_terms(local_model.get("actions"))
        local_actions = local_action_terms
        descriptor = DomainDescriptor(
            id=domain_id or root.name,
            path=root,
            name=model.name,
            version=model.version,
            description=model.description,
            object_types=tuple(model.objects),
            relation_types=tuple(model.relations),
            functions=tuple(model.functions),
            actions=tuple(model.actions),
            tags=tuple(str(tag) for tag in tags),
            priority=int(priority),
            terms=tuple(dict.fromkeys((
                *local_objects,
                *local_functions,
                *local_actions,
            ))),
            action_terms=tuple(local_action_terms),
        )
        self.register_descriptor(descriptor)
        return descriptor

    def register_descriptor(self, descriptor: DomainDescriptor) -> None:
        current = self._descriptors.get(descriptor.id)
        if current is not None and current != descriptor:
            raise ValueError(f"领域 ID 已注册且定义不同: {descriptor.id}")
        self._descriptors[descriptor.id] = descriptor

    def get(self, domain_id: str) -> DomainDescriptor:
        try:
            return self._descriptors[domain_id]
        except KeyError as exc:
            raise ValueError(f"未知领域: {domain_id}") from exc

    def list(self) -> list[DomainDescriptor]:
        return list(self._descriptors.values())

    def resolve(self, domain_ids: Iterable[str]) -> list[DomainDescriptor]:
        return [self.get(str(domain_id)) for domain_id in dict.fromkeys(domain_ids)]

    def match(self, intent: str, *, limit: int | None = None) -> list[DomainDescriptor]:
        """Return domains whose declared vocabulary matches a user intent."""
        matches = self.rank(intent)
        descriptors = [item.descriptor for item in matches]
        return descriptors if limit is None else descriptors[:max(0, int(limit))]

    def rank(self, intent: str) -> list[DomainMatch]:
        """Rank matching domains and retain the terms that caused each match."""
        query = str(intent or "").strip().lower()
        if not query:
            return []
        scored: list[tuple[int, int, DomainMatch]] = []
        for index, descriptor in enumerate(self._descriptors.values()):
            matched_terms: list[str] = []
            score = 0
            for token in (
                descriptor.id,
                descriptor.name,
                *descriptor.tags,
                *descriptor.terms,
            ):
                normalized = token.strip().lower()
                if len(normalized) < 2 or normalized not in query:
                    continue
                if normalized not in {item.lower() for item in matched_terms}:
                    matched_terms.append(token)
                score += min(len(normalized), 12)
                if normalized in {descriptor.id.lower(), descriptor.name.lower()}:
                    score += 100
                if token in descriptor.action_terms:
                    score += 30
            # Priority only breaks a real semantic match. It must never make a
            # child domain match an unrelated message by itself.
            if matched_terms:
                score += descriptor.priority
                scored.append((
                    score,
                    -index,
                    DomainMatch(descriptor, score, tuple(matched_terms)),
                ))
        scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
        return [item[2] for item in scored]

    def as_dicts(self) -> list[dict[str, object]]:
        return [descriptor.model_dump() for descriptor in self._descriptors.values()]


def _load_local_model(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须是 YAML mapping")
    return payload


def _definition_terms(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    result: list[str] = []
    for type_id, definition in value.items():
        result.append(str(type_id))
        if not isinstance(definition, dict):
            continue
        for field in ("name", "aliases"):
            item = definition.get(field)
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, list):
                result.extend(str(alias) for alias in item if alias)
    return list(dict.fromkeys(term for term in result if term))


def _routing_terms(value: object) -> list[str]:
    return _expand_terms(_definition_terms(value))


def _expand_terms(terms: Iterable[str]) -> list[str]:
    result: list[str] = []
    for term in terms:
        result.append(term)
        for segment in re.findall(r"[\u3400-\u9fff]{4,}", term):
            result.extend(segment[index:index + 2] for index in range(len(segment) - 1))
    return list(dict.fromkeys(result))
