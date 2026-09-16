"""Explicit current Windows save/restore host with its real-source negative control."""
from pathlib import Path
import subprocess
import sys


def test_native_windows_save_restore_epoch_boundary():
    subprocess.run([sys.executable, str(Path(__file__).with_name('aur-save-native.py'))], check=True)
