"""Read-only last-confirmed personal-sync metadata, not readiness or a grant."""
from copy import deepcopy
import uuid
from unittest import mock

import pytest

from test_personal_sync import _personal_service
import magnolie_telefon as phone


def report(run,trigger='manual',state='complete'):
    return dict(format=1,run_id=run,state=state,trigger=trigger,transport='wifi',sent=dict(notes=0,tasks=0,notebooks=0),
        received=dict(notes=0,tasks=0,notebooks=0),conflicts=0,attachments_omitted=0,oversized_skipped=0,started_ms=1,finished_ms=1,
        error='none' if state=='complete' else 'invalid',deletions=dict(pending=0,deleted=0,restored=0,conflicts=0,blocked=0,
            trash=dict(notes=0,tasks=0,notebooks=0,attachments=0)))


def success_service(tmp_path):
    events=[];service,peer_id=_personal_service(tmp_path,lambda event,payload:events.append((event,payload)))
    channel=mock.Mock();service.connections[peer_id]=channel;service.connection_transports[peer_id]='wifi'
    return service,service.store.peer(peer_id),channel,events


def queued_report(service,peer,trigger='manual',state='complete'):
    run=str(uuid.uuid4())
    service.store.remember_personal_run(peer['device_id'],dict(format=1,run_id=run,trigger=trigger,modules=['notes']))
    return service.store.queue(peer['device_id'],'personal_sync.report',report(run,trigger,state),60_000,
        'wifi_only' if trigger=='auto_wifi' else 'any')


def test_legacy_absence_stays_unknown_and_confirmed_summary_preserves_grants_and_survives_reopen(tmp_path):
    service,peer,_,_=success_service(tmp_path);store=service.store;before=deepcopy(peer)
    assert store.personal_success(peer['device_id']) is None and 'last_success' not in peer['personal_sync']
    run=str(uuid.uuid4())
    assert store.remember_personal_success(peer['device_id'],peer['static_public'],run,'manual',1000)
    saved=store.personal_success(peer['device_id']);assert saved==dict(format=1,trigger='manual',finished_ms=1000)
    assert 'run_id' not in saved and 'peer_fingerprint' not in saved
    after=deepcopy(peer);after['personal_sync'].pop('last_success');assert after==before
    reopened=phone.PhoneStore(store.root,'Test')
    assert reopened.personal_success(peer['device_id'])==saved
    assert not store.remember_personal_success(peer['device_id'],peer['static_public'],run,'manual',2000)
    assert not store.remember_personal_success(peer['device_id'],peer['static_public'],str(uuid.uuid4()),'manual',999)
    assert store.personal_success(peer['device_id'])==saved


@pytest.mark.parametrize('trigger',['manual','auto_wifi'])
def test_only_accepted_complete_outgoing_report_ack_records_actual_trigger_not_configured_automatic_mode(tmp_path,trigger):
    service,peer,channel,_=success_service(tmp_path)
    peer['personal_sync']['auto_wifi']=True;service.store.save_peers()
    message=queued_report(service,peer,trigger)
    assert service.store.personal_success(peer['device_id']) is None
    before=phone.now_ms()
    service._payload(peer,channel,dict(type='ack',message_id=message['message_id'],status='accepted',error='none'))
    success=service.store.personal_success(peer['device_id'])
    assert success['trigger']==trigger and success['finished_ms']>=before
    assert success['finished_ms']!=message['body']['finished_ms'] # Not a remote/queued timestamp guess.
    service._payload(peer,channel,dict(type='ack',message_id=message['message_id'],status='duplicate',error='none'))
    assert service.store.personal_success(peer['device_id'])==success


@pytest.mark.parametrize('kind',['rejected','failed_report','stale_channel','raw_remote_report'])
def test_failed_queued_stale_or_remote_claims_cannot_replace_last_confirmed_success(tmp_path,kind):
    service,peer,channel,_=success_service(tmp_path)
    service.store.remember_personal_success(peer['device_id'],peer['static_public'],str(uuid.uuid4()),'manual',1000)
    before=service.store.personal_success(peer['device_id'])
    message=queued_report(service,peer,state='failed' if kind=='failed_report' else 'complete')
    if kind=='stale_channel':service.connections[peer['device_id']]=mock.Mock()
    if kind=='raw_remote_report':
        now=phone.now_ms();incoming=dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='personal_sync.report',
            created_ms=now,expires_ms=now+60_000,body=message['body'])
        service._payload(peer,channel,incoming)
    else:service._payload(peer,channel,dict(type='ack',message_id=message['message_id'],
        status='rejected' if kind=='rejected' else 'accepted',error='invalid_schema' if kind=='rejected' else 'none'))
    assert service.store.personal_success(peer['device_id'])==before


def test_success_is_bound_to_current_phone_key_and_is_not_reassigned_after_key_change(tmp_path):
    service,peer,_,_=success_service(tmp_path);store=service.store
    assert not store.remember_personal_success(peer['device_id'],phone.b64(b'x'*32),str(uuid.uuid4()),'manual',1000)
    store.remember_personal_success(peer['device_id'],peer['static_public'],str(uuid.uuid4()),'manual',1000)
    peer['static_public']=phone.b64(b'x'*32)
    assert store.personal_success(peer['device_id']) is None


def test_auto_connection_metadata_is_supported_without_widening_legacy_transport_policy(tmp_path):
    service,peer,_,_=success_service(tmp_path)
    assert service.store.remember_personal_success(peer['device_id'],peer['static_public'],str(uuid.uuid4()),'auto_connection',1000)
    assert service.store.personal_success(peer['device_id']) == dict(format=1,trigger='auto_connection',finished_ms=1000)


def test_mode_changes_preserve_confirmed_success_without_using_configured_trigger(tmp_path):
    service,peer,_,_=success_service(tmp_path)
    service.store.remember_personal_success(peer['device_id'],peer['static_public'],str(uuid.uuid4()),'manual',1000)
    before=service.store.personal_success(peer['device_id'])
    service.set_personal_sync(peer['device_id'],True,True)
    assert service.store.personal_success(peer['device_id']) == before


@pytest.mark.parametrize('field,value',[('format',True),('finished_ms',True),('finished_ms',-1),('trigger','automatic'),
    ('peer_fingerprint','not-a-key'),('run_id','not-a-run')])
def test_malformed_success_metadata_is_unknown_without_revoking_or_repairing_peer_grants(tmp_path,field,value):
    service,peer,_,_=success_service(tmp_path);store=service.store
    store.remember_personal_success(peer['device_id'],peer['static_public'],str(uuid.uuid4()),'manual',1000)
    peer['personal_sync']['last_success'][field]=value;before=deepcopy(peer)
    assert store.personal_success(peer['device_id']) is None
    phone.PhoneStore._validate_peer(peer)
    assert peer==before
