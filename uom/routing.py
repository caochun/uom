"""Session-level selection of independently loadable UOM domains."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, Literal

from uom.registry import DomainMatch, DomainRegistry


@dataclass(frozen=True)
class DomainSelection:
    """The domain set assigned to one conversation session."""

    domain_ids: tuple[str, ...]
    mode: Literal["auto", "manual"] = "auto"
    matched_ids: tuple[str, ...] = ()
    changed: bool = False
    reason: str = ""


class DomainRouter:
    """Keep a conservative, explicit domain context for each session.

    The router only chooses domain IDs. It never loads a Repository or Agent,
    which keeps model selection separate from runtime lifecycle management.
    """

    def __init__(
        self,
        registry: DomainRegistry,
        *,
        default_ids: Iterable[str],
        max_auto_domains: int = 3,
    ) -> None:
        self.registry = registry
        self.default_ids = self._validate(default_ids)
        if not self.default_ids:
            raise ValueError("领域路由至少需要一个默认领域")
        self.max_auto_domains = max(1, int(max_auto_domains))
        self._sessions: dict[str, DomainSelection] = {}
        self._lock = threading.RLock()

    def current(self, session_id: str) -> DomainSelection:
        with self._lock:
            return self._sessions.get(
                str(session_id),
                DomainSelection(self.default_ids, reason="default"),
            )

    def select(
        self,
        session_id: str,
        domain_ids: Iterable[str],
        *,
        manual: bool = True,
        locked: bool = False,
    ) -> DomainSelection:
        """Explicitly select a domain set, usually from a UI control."""
        with self._lock:
            current = self.current(session_id)
            selected = self._validate(domain_ids)
            if not selected:
                raise ValueError("至少需要选择一个领域")
            if locked and selected != current.domain_ids:
                raise RuntimeError("当前会话有待确认的操作，请先完成或取消后再切换领域")
            result = DomainSelection(
                selected,
                mode="manual" if manual else "auto",
                changed=selected != current.domain_ids or manual != (current.mode == "manual"),
                reason="manual" if manual else "auto",
            )
            self._sessions[str(session_id)] = result
            return result

    def use_auto(self, session_id: str, *, locked: bool = False) -> DomainSelection:
        """Release a manual pin while retaining the current domain until the next match."""
        with self._lock:
            current = self.current(session_id)
            if locked and current.mode == "manual":
                raise RuntimeError("当前会话有待确认的操作，请先完成或取消后再切换领域")
            result = DomainSelection(
                current.domain_ids,
                mode="auto",
                changed=current.mode != "auto",
                reason="auto",
            )
            self._sessions[str(session_id)] = result
            return result

    def resolve(
        self,
        session_id: str,
        intent: str,
        *,
        locked: bool = False,
    ) -> DomainSelection:
        """Resolve a message without overriding a manual or locked context."""
        with self._lock:
            current = self.current(session_id)
            if locked:
                return DomainSelection(
                    current.domain_ids,
                    mode=current.mode,
                    changed=False,
                    reason="pending_confirmation",
                )
            if current.mode == "manual":
                return DomainSelection(
                    current.domain_ids,
                    mode="manual",
                    changed=False,
                    reason="manual",
                )

            ranked = self.registry.rank(intent)
            selected = self._automatic_ids(ranked)
            if not selected:
                return DomainSelection(
                    current.domain_ids,
                    mode="auto",
                    changed=False,
                    reason="keep_current",
                )
            result = DomainSelection(
                selected,
                mode="auto",
                matched_ids=tuple(match.descriptor.id for match in ranked),
                changed=selected != current.domain_ids,
                reason="intent",
            )
            self._sessions[str(session_id)] = result
            return result

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(str(session_id), None)

    def _automatic_ids(self, ranked: list[DomainMatch]) -> tuple[str, ...]:
        if not ranked:
            return ()

        # A named business Action is routed to one owning domain. This keeps
        # MVP writes single-domain even though read questions may compose.
        action_matches = [
            match for match in ranked
            if {term.lower() for term in match.terms}
            & {term.lower() for term in match.descriptor.action_terms}
        ]
        if action_matches:
            return (action_matches[0].descriptor.id,)

        candidates = ranked[: self.max_auto_domains + 1]
        filtered: list[DomainMatch] = []
        for candidate in candidates:
            candidate_id = candidate.descriptor.id
            children = [
                other for other in candidates
                if other.descriptor.id.startswith(candidate_id + ".")
            ]
            candidate_terms = {term.lower() for term in candidate.terms}
            child_terms = {
                term.lower()
                for child in children
                for term in child.terms
            }
            if children and candidate_terms and candidate_terms <= child_terms:
                continue
            filtered.append(candidate)
        return tuple(
            match.descriptor.id
            for match in filtered[: self.max_auto_domains]
        )

    def _validate(self, domain_ids: Iterable[str]) -> tuple[str, ...]:
        ids = tuple(dict.fromkeys(str(domain_id).strip() for domain_id in domain_ids if str(domain_id).strip()))
        self.registry.resolve(ids)
        return ids

