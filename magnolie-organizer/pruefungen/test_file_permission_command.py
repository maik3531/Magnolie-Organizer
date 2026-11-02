from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError

NOW = 1_800_000_000_000
ID = '11111111-1111-4111-8111-111111111111'


def request():
    return sources.create_command('request_read', expected_version='a' * 64, now=NOW, message_id=ID)


def result(state='requested'):
    message = request(); message['kind'] = sources.PERMISSION_RESULT
    message['body'] = dict(format=1, request_id=ID, operation='request_read', version='a' * 64, state=state)
    return message


def test_native_ui_request_has_only_the_exact_source_policy_version():
    command = sources.parse_command(request(), now=NOW)
    assert command.operation == 'request_read' and command.expected_version == 'a' * 64
    assert command.enabled is None and command.kinds == () and command.catalog_id is None


@pytest.mark.parametrize('key,value', [('read_granted', True), ('send_files', True), ('token', 'opaque'),
    ('owner', 'native-owner'), ('notification_allowed', True), ('path', '/private'), ('after', 0), ('enabled', True)])
def test_remote_ui_request_cannot_supply_native_authority_or_claim_os_permission(key, value):
    message = request(); message['body'][key] = value
    with pytest.raises(TransferError): sources.parse_command(message, now=NOW)


@pytest.mark.parametrize('state', ['requested', 'notification_posted', 'foreground_required', 'failed'])
def test_correlated_result_describes_only_a_ui_attempt_not_os_read(state):
    message = result(state); original = deepcopy(message)
    outcome = sources.parse_permission_result(message, expected_request_id=ID, expected_version='a' * 64, now=NOW)
    assert outcome.state == state
    assert not hasattr(outcome, 'read_granted') and not hasattr(outcome, 'token')
    assert message == original


@pytest.mark.parametrize('key,value', [('state', 'granted'), ('state', True), ('operation', 'configure'),
    ('version', 'b' * 64), ('request_id', '22222222-2222-4222-8222-222222222222'), ('read_granted', True)])
def test_unmatched_or_authority_claiming_result_is_rejected(key, value):
    message = result(); message['body'][key] = value
    with pytest.raises(TransferError):
        sources.parse_permission_result(message, expected_request_id=ID, expected_version='a' * 64, now=NOW)
