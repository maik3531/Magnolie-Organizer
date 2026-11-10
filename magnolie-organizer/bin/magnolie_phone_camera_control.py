"""Authenticated-parent webcam control schema, NOT consent or a live session.

No native imports, listeners, capture, advertisement, persisted start or network
side effects. A controller must bind the exact original parent, fresh probe,
monotonic lifetime, phase, actual opt-in and receiver readiness independently.
Desktop-only v24 discovery preserves Notes' full 16-version legacy capability set.
"""
import re
import uuid

DISCOVERY_VERSION = 24
REQUEST = 'device_status.request'
REPORT = 'device_status.report'
MAX_WIRE_BYTES = 4096
MAX_TTL_MS = 60_000
REASONS = frozenset(('disabled', 'unsupported', 'foreground_required',
    'permission_denied', 'capture_failed', 'output_failed', 'retired'))
_BASE = frozenset(('version', 'request_id', 'nonce', 'op'))


def validate_body(body, kind):
    def invalid():
        raise ValueError('webcam_control_invalid')
    def hex_value(key, length):
        value = body.get(key)
        return type(value) is str and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None
    if type(body) is not dict or kind not in (REQUEST, REPORT):
        invalid()
    if type(body.get('version')) is not int or body['version'] != DISCOVERY_VERSION:
        invalid()
    try:
        identity = uuid.UUID(body['request_id'])
        if str(identity) != body['request_id'] or identity.version != 4 or identity.variant != uuid.RFC_4122:
            invalid()
    except (KeyError, TypeError, ValueError, AttributeError):
        invalid()
    if not hex_value('nonce', 64):
        invalid()
    op = body.get('op')
    if type(op) is not str:
        invalid()
    variants = {
        'probe': (REQUEST, ()),
        'offer': (REPORT, ('session', 'secret', 'port', 'muted', 'front')),
        'unavailable': (REPORT, ('reason',)),
        'prepared': (REQUEST, ('session',)),
        'send': (REPORT, ('session',)),
        'stop': (kind, ('session',)),
        'error': (kind, ('session', 'reason')),
    }
    if op not in variants:
        invalid()
    direction, fields = variants[op]
    if direction != kind or body.keys() != _BASE | set(fields):
        invalid()
    if 'session' in fields and not hex_value('session', 32):
        invalid()
    if 'reason' in fields and (type(body['reason']) is not str or body['reason'] not in REASONS):
        invalid()
    if op == 'offer' and (not hex_value('secret', 64) or type(body['port']) is not int or
            not 1024 <= body['port'] <= 65535 or
            type(body['muted']) is not bool or type(body['front']) is not bool):
        invalid()
    return body
