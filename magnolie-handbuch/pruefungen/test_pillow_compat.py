"""#381: bounded legacy namespace bridge; no replacement of modern Pillow."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('handbook_pdf_pillow', Path(__file__).resolve().parents[1] / 'bin/magnolie_print_pdf.py')
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)
NAMES = ('FLIP_LEFT_RIGHT', 'FLIP_TOP_BOTTOM', 'ROTATE_90', 'ROTATE_180', 'ROTATE_270', 'TRANSPOSE', 'TRANSVERSE')


def pillow(monkeypatch, version='9.0.1'):
    module = ModuleType('PIL')
    module.__version__ = version
    module.Image = SimpleNamespace(**dict(zip(NAMES, range(7))))
    monkeypatch.setitem(sys.modules, 'PIL', module)
    return module.Image


def test_legacy_bridge_uses_only_existing_public_integer_constants(monkeypatch):
    image = pillow(monkeypatch)
    before = vars(image).copy()
    pdf.prepare_pillow_for_pdf()
    assert {name: int(getattr(image.Transpose, name)) for name in NAMES} == before
    enum = image.Transpose
    pdf.prepare_pillow_for_pdf()
    assert image.Transpose is enum


def test_modern_namespace_is_never_replaced(monkeypatch):
    image = pillow(monkeypatch, '12.0.0')
    image.Transpose = object()
    original = vars(image).copy()
    pdf.prepare_pillow_for_pdf()
    assert vars(image) == original


@pytest.mark.parametrize('version', ['8.4.0', '9.0.0', 'unknown'])
def test_untested_legacy_versions_are_not_silently_accepted(monkeypatch, version):
    image = pillow(monkeypatch, version)
    with pytest.raises(RuntimeError, match='Unsupported legacy'):
        pdf.prepare_pillow_for_pdf()
    assert not hasattr(image, 'Transpose')


def test_changed_constant_does_not_create_a_wrong_orientation(monkeypatch):
    image = pillow(monkeypatch)
    image.ROTATE_90 = 99
    with pytest.raises(RuntimeError, match='Unexpected legacy'):
        pdf.prepare_pillow_for_pdf()
    assert not hasattr(image, 'Transpose')


def test_package_requirements_match_the_explicitly_supported_legacy_version():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'debian/control').read_text().count('python3-pil (>= 9.0.1)') == 2
    assert (root / 'rpm/magnolie-handbuch.spec').read_text().count('python3dist(pillow) >= 9.0.1') == 2
    assert 'pruefungen/test_pillow_compat.py' in (root / 'debian/rules').read_text()
