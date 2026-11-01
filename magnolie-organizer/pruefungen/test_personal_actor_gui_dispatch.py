"""Execute the actual native script-message dispatch branch, without GTK/VM."""
import ast
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('action,on_owner', [('notes_actor_produce', True), ('notes_actor_dispatch_proposals', True),
    ('notes_actor_reply', True), ('notes_actor_begin_completion', True), ('notes_actor_advance_completion', True), ('notes_actor_late_review', True),
    ('notes_actor_source', False), ('notes_actor_scope', False), ('notes_actor_status', False), ('read', False)])
def test_private_writer_actions_reach_the_native_gui_owner_not_the_generic_worker(action, on_owner):
    source = Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer'
    branch = next(node for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.If) and
        isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == 'befehl' and
        len(node.test.comparators) == 1 and isinstance(node.test.comparators[0], ast.Constant) and node.test.comparators[0].value == 'telefon_mcp' and
        any(isinstance(child, ast.Attribute) and child.attr == '_telefon_mcp' for statement in node.body for child in ast.walk(statement)))
    # Preserve the production branch exactly, stripping only unrelated siblings.
    route = ast.FunctionDef(name='route', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='self'), ast.arg(arg='nachricht')], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=[ast.Assign(targets=[ast.Name(id='befehl', ctx=ast.Store())], value=ast.Constant(value='telefon_mcp')),
              ast.If(test=branch.test, body=branch.body, orelse=[])], decorator_list=[])
    threads = []
    def thread(*args, **kwargs):
        result = threading.Thread(*args, **kwargs); threads.append(result); return result
    namespace = {'threading': SimpleNamespace(Thread=thread)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[])), str(source), 'exec'), namespace)
    caller = threading.get_ident(); observed = []; event = threading.Event()
    def received(message):
        observed.append((threading.get_ident(), message)); event.set()
    request = {'request': {'action': action}, 'requestId': 'synthetic-private-actor'}
    namespace['route'](SimpleNamespace(_telefon_mcp=received), request)
    assert event.wait(3)
    for item in threads:
        item.join(1); assert not item.is_alive()
    assert len(observed) == 1 and observed[0][1] is request
    assert (observed[0][0] == caller) is on_owner
