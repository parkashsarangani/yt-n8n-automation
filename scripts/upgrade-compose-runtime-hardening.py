#!/usr/bin/env python3
"""Stable entry point for final compose/B-roll runtime hardening."""
from __future__ import annotations

import sys
from pathlib import Path

from retrieval_observability import patch_file as patch_retrieval_observability
from runtime_hardening_impl import upgrade as _upgrade


def upgrade(path: Path) -> None:
    _upgrade(path)
    patch_retrieval_observability(path)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: upgrade-compose-runtime-hardening.py BROLL_RESOLVER_JS")
    path = Path(sys.argv[1])
    upgrade(path)
    print(f"runtime-hardened + observable b-roll resolver written to {path}")


if __name__ == "__main__":
    main()
