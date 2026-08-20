#!/usr/bin/env python3
"""Compatibility shim for the renamed quality-alignment transform.

The canonical module is ``upgrade_quality_alignment.py``. This file exists so
older CI/deploy snapshots that still reference the former hyphenated path fail
safe instead of aborting before the real transform chain can run.
"""

from upgrade_quality_alignment import *  # noqa: F401,F403
