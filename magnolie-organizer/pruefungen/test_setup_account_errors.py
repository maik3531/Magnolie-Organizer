"""Account discovery failures must not become a successful empty selection."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer'


def functions(loaded=True, calendars=None, books=None, failure=None, kde=None, load_error=''):
    tree = ast.parse(SOURCE.read_text())
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and
                node.name in ('setup_internetkonten_status', 'setup_internetkonten')]
    def discover(_registry):
        if failure:
            raise failure
        return calendars or [], books or []
    scope = dict(eds_laden=lambda: loaded, eds_registry=lambda: object(), eds_quellen=discover,
                 _EDS={'fehler': load_error}, _=lambda value: value,
                 debug_ausnahme=lambda *_args, **_kwargs: None,
                 akonadi_quellen_status=lambda: kde or {})
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope


def test_library_failure_keeps_its_cause():
    scope = functions(loaded=False, load_error='Synthetic namespace failure')
    assert scope['setup_internetkonten_status']() == {'accounts': [], 'error': 'Synthetic namespace failure'}


def test_registry_failure_is_not_a_successful_empty_list():
    scope = functions(failure=RuntimeError('Synthetic registry failure'))
    assert scope['setup_internetkonten_status']()['error'] == 'Synthetic registry failure'


def test_real_empty_account_list_has_no_error():
    assert functions()['setup_internetkonten_status']() == {'accounts': [], 'error': ''}


def test_other_backend_sources_remain_selectable_when_eds_fails():
    scope = functions(loaded=False, load_error='EDS unavailable', kde={
        'kalender': [{'uid': 'synthetic-calendar', 'name': 'Synthetic calendar'}]})
    result = scope['setup_internetkonten_status']()
    assert result['accounts'] == [{'uid': 'synthetic-calendar', 'name': 'Synthetic calendar', 'kind': 'calendar'}]
    assert result['error'] == 'EDS unavailable'


def test_existing_list_api_preserves_source_choices():
    scope = functions(calendars=[{'uid': 'synthetic', 'name': 'Synthetic'}])
    assert scope['setup_internetkonten']() == [{'uid': 'synthetic', 'name': 'Synthetic', 'kind': 'calendar'}]
