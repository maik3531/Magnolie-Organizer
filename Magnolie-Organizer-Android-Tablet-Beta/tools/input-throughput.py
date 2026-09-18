#!/usr/bin/env python3
"""Async four-stage UI gate against the unchanged app; no repeated shell arm."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('input_ab', Path(__file__).with_name('input-ab.py'))
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)
ab.INCLUDE_CONTROL = False
ab.TEST = ab.ROOT / 'artifacts/input-throughput-instrumentation.apk'
ab.MANIFEST = ab.ROOT / 'artifacts/input-throughput.json'

if __name__ == '__main__':
    sys.exit(ab.main())
