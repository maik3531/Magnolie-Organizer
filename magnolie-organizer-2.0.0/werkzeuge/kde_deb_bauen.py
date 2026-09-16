#!/usr/bin/env python3
"""Run the same standalone multi-rootfs recipe that ships in the KDE .dsc."""
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, str(Path(__file__).resolve().parents[1] /
        "native/akonadi-helper/build.py"), *sys.argv[1:]]))
