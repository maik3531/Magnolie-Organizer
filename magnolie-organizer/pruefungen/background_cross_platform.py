"""Explicit Windows source gate; a missing sibling is an error, never a skip."""
from test_automatic_cloud_backup import cross_windows_dpapi_save_routing_and_readback_sources


def test_windows_dpapi_save_routing_and_readback_sources():
    cross_windows_dpapi_save_routing_and_readback_sources()
