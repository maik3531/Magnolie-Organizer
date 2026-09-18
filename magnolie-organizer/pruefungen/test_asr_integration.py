"""Public ASR source/store integration gates, synthetic data only.

The native cross-language hosts require the explicitly configured bounded test
environment; ordinary source-only runs report unavailable prerequisites as skips.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent


def require_cross_environment():
    if not os.environ.get('MAGNOLIE_DOTNET'):
        if os.environ.get('MAGNOLIE_VOLLPRUEFUNG') == '1':
            pytest.fail('Full ASR gate requires the current .NET test toolchain')
        pytest.skip('Explicit current-source .NET test environment not configured')


def test_sms_restore_review_and_exact_approved_transport():
    require_cross_environment()
    subprocess.run([sys.executable, '-B', str(HERE / 'asr_sms_restore.py')], stdin=subprocess.DEVNULL, check=True, timeout=180)


def test_windows_restore_precommit_postcommit_and_repair():
    require_cross_environment()
    subprocess.run([sys.executable, '-B', str(HERE / 'restore-native/phases.py')], stdin=subprocess.DEVNULL, check=True, timeout=240)
