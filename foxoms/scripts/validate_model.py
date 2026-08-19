#!/usr/bin/env python3
"""Validate the FoxOMS UOM domain."""

from __future__ import annotations

from pathlib import Path

from uom.validation import main


if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parents[1]))
