"""Printer selection contracts without printing or opening a real dialog."""
import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


class Settings:
    def __init__(self, values=None): self.values = dict(values or {})
    def set_printer(self, name): self.values['printer'] = name
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value


def run_dialog_case(monkeypatch, response=1, virtual=True, output=None, printer=True, portal=False):
    source = Path(__file__).resolve().parents[1] / 'bin/magnolie-handbuch'
    function = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'druckdialog_starten')
    class Flags:
        __flags_values__ = {1: SimpleNamespace(value_names=['GTK_PRINT_CAPABILITY_PAGE_SET']),
                           32: SimpleNamespace(value_names=['GTK_PRINT_CAPABILITY_GENERATE_PDF'])}
    settings = Settings({'output-file-format': output} if output else {})
    selected = Mock()
    selected.get_property.side_effect = lambda key: {'name': 'selected-printer', 'is-virtual': virtual}[key]
    props = {'manual-capabilities': Flags(), 'print-settings': settings, 'page-setup': object(),
             'selected-printer': selected if printer else None}
    dialog = Mock()
    dialog.get_property.side_effect = props.__getitem__
    dialog.run.return_value = response
    lib = Mock(); monkeypatch.setattr(ctypes, 'CDLL', Mock(return_value=lib))
    gobject = SimpleNamespace(type_from_name=lambda _: 'print-dialog', new=Mock(return_value=dialog))
    scope = {'os': SimpleNamespace(path=SimpleNamespace(exists=lambda _: portal), environ={}),
             'Gtk': SimpleNamespace(ResponseType=SimpleNamespace(OK=1), PrintSettings=Settings,
                 PRINT_SETTINGS_OUTPUT_FILE_FORMAT='output-file-format'),
             'GObject': gobject, 'FENSTER_TITEL': 'Handbook'}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    operation = Mock(); operation.get_print_settings.return_value = Settings()
    parent = object()
    scope['druckdialog_starten'](operation, parent)
    return operation, dialog, settings, gobject, parent


def test_virtual_printer_keeps_explicit_pdf_format(monkeypatch):
    operation, dialog, settings, _, _ = run_dialog_case(monkeypatch)
    assert settings.get('output-file-format') == 'pdf'
    assert settings.get('printer') == 'selected-printer'
    operation.set_print_settings.assert_called_once_with(settings)
    operation.print_.assert_called_once_with()
    operation.run_dialog.assert_not_called()
    dialog.destroy.assert_called_once_with()


@pytest.mark.parametrize('response,printer', [(0, True), (1, False)])
def test_cancel_or_missing_printer_does_not_print(monkeypatch, response, printer):
    operation, dialog, _, _, _ = run_dialog_case(monkeypatch, response=response, printer=printer)
    operation.print_.assert_not_called()
    dialog.destroy.assert_called_once_with()


def test_physical_printer_is_not_forced_to_file_format(monkeypatch):
    operation, _, settings, _, _ = run_dialog_case(monkeypatch, virtual=False)
    assert settings.get('output-file-format') is None
    assert settings.get('printer') == 'selected-printer'
    operation.print_.assert_called_once_with()


def test_existing_output_format_is_preserved(monkeypatch):
    _, _, settings, _, _ = run_dialog_case(monkeypatch, output='pdf')
    assert settings.get('output-file-format') == 'pdf'


def test_sandbox_delegates_to_existing_print_portal(monkeypatch):
    operation, dialog, _, gobject, parent = run_dialog_case(monkeypatch, portal=True)
    operation.run_dialog.assert_called_once_with(parent)
    operation.print_.assert_not_called()
    gobject.new.assert_not_called()
    dialog.run.assert_not_called()
