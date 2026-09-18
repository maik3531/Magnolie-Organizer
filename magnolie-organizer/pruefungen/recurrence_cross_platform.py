"""Explicit four-engine developer suite; requires restored .NET, Node and dateutil.

Run with pytest on this file. Normal public source/package tests replay fixed
goldens and do not require another product's tree or compile C# as a side effect.
"""

from recurrence_dateutil_oracle import rrule  # Fail if the explicitly requested oracle is unavailable.
from test_recurrence_integration import FIXTURES, check_cross_language
from test_recurrence_timezones import (
    cross_language_timezone_differential_and_own_linux_export,
    cross_language_448_windows_oracles,
)


def test_real_cross_language_consumers():
    check_cross_language(FIXTURES)


def test_real_timezone_differential_and_own_linux_export():
    cross_language_timezone_differential_and_own_linux_export()


def test_frozen_448_windows_oracles_through_all_four_engines():
    cross_language_448_windows_oracles()
