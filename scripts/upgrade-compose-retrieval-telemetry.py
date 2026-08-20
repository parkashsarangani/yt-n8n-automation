#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from compose_retrieval_telemetry import patch_file

def main():
    if len(sys.argv)!=2:raise SystemExit("usage: upgrade-compose-retrieval-telemetry.py COMPOSE_JS")
    path=Path(sys.argv[1]);patch_file(path);print(f"retrieval telemetry endpoints written to {path}")
if __name__=="__main__":main()
