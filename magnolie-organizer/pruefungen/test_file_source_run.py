from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError

NOW = 1_800_000_000_000
ID = '11111111-1111-4111-8111-111111111111'
CATALOG = '22222222-2222-4222-8222-222222222222'
ALBUM = '33333333-3333-4333-8333-333333333333'
RUN = '44444444-4444-4444-8444-444444444444'

def start():
    return sources.create_command('run', expected_version='a'*64, catalog_id=CATALOG, album_id=ALBUM,
                                  desktop_choice=True, message_id=ID, now=NOW)

def result(state='preparing', ended=False):
    message=start(); message['kind']=sources.RUN_RESULT
    message['body']=dict(format=1, request_id=ID, operation='run', version='a'*64, run_id=RUN, state=state, source_io_ended=ended)
    return message

def parse(message):
    return sources.parse_run_result(message, expected_request_id=ID, expected_operation='run', expected_version='a'*64, now=NOW)

def test_start_and_control_have_only_exact_selection_or_native_run_identity():
    assert sources.parse_command(start(), now=NOW).album_id == ALBUM
    for operation in ('run_status','cancel_run'):
        message=sources.create_command(operation, expected_version='a'*64, run_id=RUN, now=NOW)
        assert sources.parse_command(message, now=NOW).run_id == RUN

@pytest.mark.parametrize('key,value', [('desktop_choice',1),('catalog_id','/private'),('album_id','bucket'),
    ('success',True),('quota_retired',True),('read_granted',True),('run_id',RUN)])
def test_start_cannot_supply_authority_paths_success_or_quota_receipts(key,value):
    message=start(); message['body'][key]=value
    with pytest.raises(TransferError): sources.parse_command(message,now=NOW)

@pytest.mark.parametrize('state,ended',[('preparing',False),('cancel_pending',False),('snapshot_ready',True),('canceled_held',True),('failed_held',True)])
def test_run_states_are_source_metadata_not_synchronization_success(state,ended):
    outcome=parse(result(state,ended))
    assert outcome.state == state and not hasattr(outcome,'success') and not hasattr(outcome,'quota_retired')

@pytest.mark.parametrize('key,value',[('state','success'),('state','published'),('state','retired'),('source_io_ended',1),
    ('source_io_ended',True),('run_id','wrong'),('request_id',RUN),('version','b'*64),('success',True),('quota_retired',True)])
def test_invalid_or_uncorrelated_run_results_never_release_a_sync_owner(key,value):
    message=result(); message['body'][key]=value
    with pytest.raises(TransferError): parse(message)

def test_control_result_requires_the_exact_requested_run_and_cancellation_state():
    message=result(); message['body']['operation']='cancel_run'
    with pytest.raises(TransferError):
        sources.parse_run_result(message,expected_request_id=ID,expected_operation='cancel_run',expected_version='a'*64,expected_run_id=RUN,now=NOW)
    message['body']['state']='cancel_pending'
    assert sources.parse_run_result(message,expected_request_id=ID,expected_operation='cancel_run',expected_version='a'*64,expected_run_id=RUN,now=NOW).run_id == RUN
    with pytest.raises(TransferError):
        sources.parse_run_result(message,expected_request_id=ID,expected_operation='cancel_run',expected_version='a'*64,expected_run_id=ALBUM,now=NOW)
