import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_digitizer import DigitizerState, DigitizerRelay, SESSION_PACKET, EVENT_PACKET
from test_startup_read_failure import native, Host, full_data


def start(state):
    return state.accept(SESSION_PACKET, dict(action='start', width=1000, height=500, resolutionX=10, resolutionY=10))


def test_delta_events_preserve_position_and_pressure_and_end_on_hover_exit():
    state = DigitizerState()
    assert not start(state)['touching']
    partial = state.accept(EVENT_PACKET, dict(active=True, touching=True))
    assert not partial['touching'], 'Missing coordinates must not draw at the origin'
    down = state.accept(EVENT_PACKET, dict(x=250, y=100, pressure=0.3, tool='Pen'))
    assert down['touching'] and down['x'] == 0.25 and down['y'] == 0.2
    moved = state.accept(EVENT_PACKET, dict(x=500))
    assert moved['x'] == 0.5 and moved['y'] == 0.2 and moved['pressure'] == 0.3
    assert state.accept(EVENT_PACKET, dict(tool='Rubber'))['tool'] == 'Rubber'
    assert not state.accept(EVENT_PACKET, dict(active=False))['touching']
    assert not state.accept(EVENT_PACKET, dict(active=True))['touching']
    assert not state.accept(SESSION_PACKET, dict(action='end'))['active']


@pytest.mark.parametrize('body', [dict(x=True), dict(y=1.5), dict(pressure=float('nan')),
                                 dict(pressure=-1), dict(tool='Mouse'), dict(touching='true'), dict(unknown=1)])
def test_invalid_packet_resets_session(body):
    state = DigitizerState(); start(state)
    with pytest.raises(ValueError):
        state.accept(EVENT_PACKET, body)
    with pytest.raises(ValueError):
        state.accept(EVENT_PACKET, dict(active=True, touching=True, x=1, y=1))


def test_android_finger_draw_button_uses_pressure_deltas_and_preserves_hover():
    state = DigitizerState(); start(state)
    assert not state.accept(EVENT_PACKET, dict(active=True, touching=False, tool='Pen', x=20, y=30, pressure=0))['touching']
    assert not state.accept(EVENT_PACKET, dict(x=30, pressure=0))['touching']
    down = state.accept(EVENT_PACKET, dict(x=40, pressure=1))
    assert down['touching'] and down['pressure'] == 1
    assert state.accept(EVENT_PACKET, dict(x=50))['touching']
    assert not state.accept(EVENT_PACKET, dict(x=60, pressure=0))['touching']
    assert not state.accept(EVENT_PACKET, dict(active=False, touching=False))['active']
    assert not state.accept(EVENT_PACKET, dict(active=True, x=70))['touching']


def test_explicit_release_clears_pressure_even_if_packet_contains_pressure():
    state = DigitizerState(); start(state)
    state.accept(EVENT_PACKET, dict(active=True, touching=True, x=20, y=30, pressure=1))
    released = state.accept(EVENT_PACKET, dict(touching=False, pressure=1))
    assert not released['touching'] and released['pressure'] == 0
    assert not state.accept(EVENT_PACKET, dict(x=40))['touching']
    state.accept(EVENT_PACKET, dict(touching=True, pressure=1))
    exited = state.accept(EVENT_PACKET, dict(active=False))
    assert not exited['touching'] and exited['pressure'] == 0


def test_diagnostics_distinguish_raw_pressure_from_normalized_release_without_positions():
    state = DigitizerState(); start(state)
    state.accept(EVENT_PACKET, dict(active=True, touching=False, x=20, y=30, pressure=1))
    assert state.sample()['pressure'] == 0
    assert state.diagnostics == dict(events=1, explicit_contact=0, positive_pressure=1,
                                     pressure_updates=1, rejected=0)


def test_new_session_clears_previous_pen_state_and_clamps_real_pressure():
    state = DigitizerState(); start(state)
    assert state.accept(EVENT_PACKET, dict(active=True, touching=True, x=10, y=20, pressure=1.2))['pressure'] == 1
    assert not start(state)['touching']
    assert not state.accept(EVENT_PACKET, dict(active=True, touching=True))['touching']


def test_relay_batches_and_revokes_on_foreground_loss():
    import threading
    import uuid
    received, signal, allowed = [], threading.Event(), {'value': True}
    def publish(kind, payload):
        received.append((kind, payload)); signal.set()
    relay = DigitizerRelay(publish)
    owner, token = object(), str(uuid.uuid4())
    relay.arm(owner, 'tablet', token, lambda: allowed['value'])
    with relay.lock:
        relay.push(object(), {'active': True})
        relay.push(owner, {'active': True, 'touching': True})
        relay.push(owner, {'active': True, 'touching': False})
    assert signal.wait(1)
    assert received[-1][1]['token'] == token
    assert len(received[-1][1]['events']) == 2
    signal.clear(); allowed['value'] = False
    assert signal.wait(1)
    assert received[-1][1]['stopped'] is True and relay.owner is None


def test_relay_overflow_stops_instead_of_replaying_partial_strokes():
    import uuid
    received = []
    relay = DigitizerRelay(lambda kind, payload: received.append(payload))
    owner = object()
    relay.arm(owner, 'tablet', str(uuid.uuid4()), lambda: True)
    with relay.lock:
        for _ in range(129):
            relay.push(owner, {'active': True, 'touching': True})
    assert relay.owner is None and not relay.samples
    assert received[-1]['stopped'] is True


def test_native_save_and_recovery_content_preserve_drawing_points(native):
    import copy
    data = full_data()
    drawing = dict(version=1, width=1200, height=800, strokes=[
        dict(tool='pen', color='#102030', width=4, points=[[0.1, 0.2, 0.5]])])
    data['customOrganizer'] = dict(version=3, modules=[dict(id='drawing', type='drawing',
        page='left', title='Synthetic drawing', items=[], drawing=drawing)])
    before = copy.deepcopy(data)
    drawing['strokes'][0]['points'].append([0.5, 0.6, 0.9])
    assert native.journal_inhalt_geaendert(before, data)
    host = Host(native); host._gesperrt = False; host._aktuelle_daten = before
    assert host.save(data)['ok'] is True
    stored = native.lade_daten()[0]
    assert isinstance(stored, dict)
    assert stored['customOrganizer']['modules'][0]['drawing'] == drawing
