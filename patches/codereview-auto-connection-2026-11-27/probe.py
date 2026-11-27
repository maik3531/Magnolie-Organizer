#!/usr/bin/env python3
"""Marker-8 wire-contract diagnostic; never authorizes a live send."""
import importlib.util
import sys
import copy
from pathlib import Path

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('personal_contract_probe', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
run = '11111111-1111-4111-8111-111111111111'
marked = {k: {'available': True, 'versions': [1, 8, 9]} for k in ('personal_notes_sync', 'personal_tasks_sync')}
legacy = copy.deepcopy(marked)
legacy['personal_tasks_sync']['versions'] = [1, 9]
counts = dict(notes=0, tasks=0, notebooks=0)
report = dict(format=1, run_id=run, state='complete', transport='bluetooth', sent=counts, received=counts,
              conflicts=0, attachments_omitted=0, oversized_skipped=0, started_ms=1, finished_ms=2, error='none',
              deletions=dict(pending=0, deleted=0, restored=0, conflicts=0, blocked=0, trash=dict(**counts, attachments=0)))
request = dict(format=1, run_id=run, modules=['notes', 'tasks'])
checks = []
def expect(name, condition):
    checks.append(bool(condition)); print(('PASS' if condition else 'FAIL') + ' ' + name)
def accepts(kind, body):
    try:
        return m.validate_body(kind, body) == body
    except ValueError as e:
        print('  validator:', str(e)); return False
negotiated = m.auto_connection_supported(marked, marked)
expect('bilateral marker', negotiated)
expect('one missing marker', not m.auto_connection_supported(marked, legacy))
expect('legacy wifi', m.automatic_trigger('wifi', False) == 'auto_wifi')
expect('legacy bluetooth', m.automatic_trigger('bluetooth', False) is None)
expect('unnegotiated new trigger rejected by authorization helper', not m.sync_trigger_allowed('auto_connection', False))
expect('unknown trigger rejected by helper', not m.sync_trigger_allowed('bogus', True))
for transport in ('wifi', 'bluetooth'):
    trigger = m.automatic_trigger(transport, negotiated)
    expect(transport + ' negotiated trigger', trigger == 'auto_connection' and m.sync_trigger_allowed(trigger, negotiated))
    expect(transport + ' request wire compatibility', accepts('personal_sync.request', dict(request, trigger=trigger)))
    expect(transport + ' report wire compatibility', accepts('personal_sync.report', dict(report, trigger=trigger, transport=transport)))
for trigger in ('manual', 'auto_wifi'):
    expect(trigger + ' request', accepts('personal_sync.request', dict(request, trigger=trigger)))
    expect(trigger + ' report', accepts('personal_sync.report', dict(report, trigger=trigger, transport='wifi')))
expect('unknown request rejected', not accepts('personal_sync.request', dict(request, trigger='bogus')))
expect('unknown report rejected', not accepts('personal_sync.report', dict(report, trigger='bogus')))
print(f'{sum(checks)}/{len(checks)} passed')
sys.exit(0 if all(checks) else 1)
