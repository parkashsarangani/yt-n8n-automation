#!/usr/bin/env python3
"""Stable entry point for final compose/B-roll runtime hardening."""
from __future__ import annotations
import sys
from pathlib import Path
from compose_retrieval_telemetry import patch_file as patch_compose_retrieval_telemetry
from retrieval_observability import patch_file as patch_retrieval_observability
from retrieval_recall_phase2 import patch_file as patch_retrieval_recall_phase2
from runtime_hardening_impl import upgrade as _upgrade
from video_multiframe_phase3 import patch_file as patch_video_multiframe_phase3

def upgrade(path:Path)->None:
    _upgrade(path)
    patch_retrieval_observability(path)
    patch_retrieval_recall_phase2(path)
    patch_video_multiframe_phase3(path)
    compose_path=path.with_name('compose.js')
    if compose_path.exists():patch_compose_retrieval_telemetry(compose_path)
def main():
    if len(sys.argv)!=2:raise SystemExit('usage: upgrade-compose-runtime-hardening.py BROLL_RESOLVER_JS')
    path=Path(sys.argv[1]);upgrade(path);print(f'runtime-hardened + observable + phase2 recall + phase3 multiframe resolver written to {path}')
if __name__=='__main__':main()
