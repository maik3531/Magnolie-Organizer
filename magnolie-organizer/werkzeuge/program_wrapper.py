#!/usr/bin/python3
"""Public command; application-private Python code lives outside PATH."""
from pathlib import Path
import runpy
import sys

_runtime = Path(__file__).resolve().parent.parent / 'share/magnolie-organizer/python'
sys.path.insert(0, str(_runtime))
runpy.run_path(str(_runtime / 'magnolie-organizer'), run_name='__main__')
