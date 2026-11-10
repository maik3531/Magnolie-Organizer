import copy
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_phone_camera_control as control


def packet(op='probe'):
    value = {'version': 24, 'request_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
             'nonce': 'b' * 64, 'op': op}
    if op in ('offer', 'prepared', 'send', 'stop', 'error'):
        value['session'] = 'c' * 32
    if op == 'offer':
        value.update(secret='d' * 64, port=24401, muted=False, front=False)
    if op in ('unavailable', 'error'):
        value['reason'] = 'disabled'
    return value


@pytest.mark.parametrize('op,kind', [
    ('probe', control.REQUEST), ('offer', control.REPORT), ('unavailable', control.REPORT),
    ('prepared', control.REQUEST), ('send', control.REPORT), ('stop', control.REQUEST),
    ('stop', control.REPORT), ('error', control.REQUEST), ('error', control.REPORT)])
def test_exact_control_variants_are_not_capture_or_send_authority(op, kind):
    value = packet(op)
    assert control.validate_body(value, kind) == value
    assert 'capture_authority' not in value and 'send_authority' not in value


@pytest.mark.parametrize('op,kind', [('probe', control.REPORT), ('offer', control.REQUEST),
    ('unavailable', control.REQUEST), ('prepared', control.REPORT), ('send', control.REQUEST)])
def test_control_roles_cannot_be_reversed(op, kind):
    with pytest.raises(ValueError, match='webcam_control_invalid'):
        control.validate_body(packet(op), kind)


@pytest.mark.parametrize('field,value', [
    ('version', True), ('version', '24'), ('version', 21), ('version', 22), ('version', 23),
    ('request_id', 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'),
    ('request_id', 'aaaaaaaa-aaaa-1aaa-8aaa-aaaaaaaaaaaa'),
    ('nonce', 'b' * 63), ('nonce', 'B' * 64), ('nonce', None),
    ('session', 'c' * 31), ('session', 'C' * 32), ('secret', 'd' * 63),
    ('port', 1023), ('port', 65536), ('port', True), ('port', '24401'),
    ('muted', 'false'), ('muted', 0), ('front', None), ('op', ['offer'])])
def test_strict_offer_types_bounds_and_non_file_version(field, value):
    body = packet('offer'); body[field] = value
    with pytest.raises(ValueError, match='webcam_control_invalid'):
        control.validate_body(body, control.REPORT)


def test_offer_is_small_control_only_and_cannot_hide_url_frames_or_permissions():
    original = packet('offer')
    for key in original:
        body = copy.deepcopy(original); del body[key]
        with pytest.raises(ValueError): control.validate_body(body, control.REPORT)
    for key, value in [('url', 'https://example.invalid'), ('video', 'frames'),
                       ('audio', 'samples'), ('permission', True), ('ready', True)]:
        with pytest.raises(ValueError): control.validate_body(dict(original, **{key: value}), control.REPORT)
    assert original['muted'] is False


@pytest.mark.parametrize('value', [None, [], 1, 'probe'])
def test_no_nonobject_control(value):
    with pytest.raises(ValueError): control.validate_body(value, control.REQUEST)


def test_unknown_failure_reason_or_op_is_not_a_generic_command():
    for body in [dict(packet('error'), reason='grant_all'), dict(packet(), op='start_without_consent')]:
        with pytest.raises(ValueError): control.validate_body(body, control.REQUEST)
