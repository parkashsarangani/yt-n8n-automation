#!/usr/bin/env python3
"""Stable entry point for quality alignment plus retrieval telemetry."""
from __future__ import annotations

import quality_alignment_impl as _impl
from workflow_retrieval_telemetry import apply as apply_retrieval_telemetry, assert_applied as assert_retrieval_telemetry

# Preserve the historical import surface used by upgrade-anthropic-parser.py.
from quality_alignment_impl import *  # noqa: F401,F403,E402


def upgrade(workflow: dict) -> dict:
    upgraded = _impl.upgrade(workflow)
    return apply_retrieval_telemetry(upgraded)


def assert_alignment(workflow: dict) -> None:
    _impl.assert_alignment(workflow)
    assert_retrieval_telemetry(workflow)
