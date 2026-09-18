"""Explicit Windows POT source gate; normal Linux source builds have no sibling."""
from test_pot_source_coverage import WINDOWS, cross_windows_deferred_literals
from test_pot_source_coverage import test_current_desktop_sources_and_handoffs_are_in_generated_pots as check_sources


def test_windows_deferred_literals():
    cross_windows_deferred_literals()


def test_windows_sources(tmp_path):
    check_sources(tmp_path, roots=(WINDOWS,))
