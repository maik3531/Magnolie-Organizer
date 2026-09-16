"""Explicit DIN/LibreOffice/.NET gate; missing prerequisites are failures."""
from test_letter_layout import cross_platform_pdf_geometry


def test_cross_platform_pdf_geometry():
    cross_platform_pdf_geometry()
