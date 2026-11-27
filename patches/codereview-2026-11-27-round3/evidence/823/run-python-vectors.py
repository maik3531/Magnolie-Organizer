"""Run the unchanged repository vector tests against an explicit native source.

Usage: python run-python-vectors.py FIXED_TEST_CHECKOUT PRODUCT_SOURCE_CHECKOUT
This permits a red baseline without editing either checkout.
"""
import sys
from pathlib import Path

tests = Path(sys.argv[1]).resolve() / "magnolie-organizer/pruefungen"
source = Path(sys.argv[2]).resolve() / "magnolie-organizer/bin/magnolie-organizer"
sys.path.insert(0, str(tests))
import pytest
import test_restore_identity
from modul_laden import quellmodul_laden

test_restore_identity.native = quellmodul_laden("magnolie_restore_explicit_source", source)
raise SystemExit(pytest.main(["-q", str(tests / "test_restore_identity.py")]))
