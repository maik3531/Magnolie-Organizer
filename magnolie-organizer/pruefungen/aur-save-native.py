"""AUR save-epoch regression through the complete current ASR restore-phase host.

The older minimal template could not represent postcommit repair. The public
host retains its intentional guard-removal negative control and full-data,
serial, restart and failure/retry checks, using the actual stores and methods.
"""
from pathlib import Path
import subprocess
import sys

subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('restore-native') / 'phases.py')],
               stdin=subprocess.DEVNULL, check=True, timeout=240)
