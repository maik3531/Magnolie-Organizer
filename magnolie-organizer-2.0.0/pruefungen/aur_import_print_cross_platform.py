"""Explicit public two-desktop gate; missing siblings/tools fail, never skip."""
from pathlib import Path
import subprocess
import sys


def test_visible_ldif_and_calendar_selection_routes():
    subprocess.run([sys.executable, str(Path(__file__).with_name('aur07-08-verify.py'))], check=True)
