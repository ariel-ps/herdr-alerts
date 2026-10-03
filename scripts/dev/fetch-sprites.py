#!/usr/bin/env python3
"""Compatibility entry point; use herdr-alert download --sprites PACK."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parents[2] / 'libexec/fetch-sprites.py'), run_name='__main__')
