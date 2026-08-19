"""FoxOMS domain provider built on the reusable UOM runtime."""

from __future__ import annotations

from pathlib import Path

from uom.provider import UomDomainProvider


def create_domain(domain_dir: str | Path) -> UomDomainProvider:
    return UomDomainProvider(domain_dir)
