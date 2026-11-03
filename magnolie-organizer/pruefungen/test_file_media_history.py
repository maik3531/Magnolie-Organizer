"""Historical per-job anchors exist before publication, not reconstructed later."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_media_history import NativeMediaHistory
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_receive import NativeFileReceiveOperation
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import ready_source
from test_file_desktop_media import manifest,collect,send_offer,dispatch


def admit(fixture,count=1):
    connection=fixture[3]
    ready_source(fixture);full=manifest(fixture,count);collect(fixture,full)
    offered,result=send_offer(fixture,full);dispatch(fixture,result)
    connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    return connection._run.receiver


def unpublished(fixture,receiver):
    # Native admission deliberately creates its private publication workspace.
    # That is not a published media member and must not be removed by the test.
    assert {path.name for path in fixture[4].iterdir()}=={'.magnolie-publication-'+receiver.job.owner}
    assert all(not (fixture[4]/path).exists() for _,path in receiver._accepted.targets)


@pytest.mark.parametrize('supply_accepted',[False,True])
def test_native_index_contains_encrypted_history_before_first_chunk_and_recovers_original_anchor(receiving,supply_accepted):
    connection=receiving[3];receiver=admit(receiving,count=9)
    index=receiver._index;history=index.media_history
    checkpoint=connection._mappings.checkpoint(connection.read_preferences().policy.mapping_store)
    assert history.mapping_store==checkpoint
    assert history==NativeMediaHistory.capture(receiver._accepted,connection._source_media_pages,mapping_store=checkpoint)
    assert len(history.entries)==9 and tuple(count for _,count in history.attempts)==(8,1)
    assert not history.grants_write_authority and not history.is_saved_receipt
    assert not index.saved_receipts()
    unpublished(receiving,receiver)
    raw=(index._parent/index._name/'index.sqlite').read_bytes()
    assert history.source_epoch.encode() not in raw and history.entries[0].photo_id.encode() not in raw
    parent=index._parent;job=receiver.job;protection=connection._authority.protection
    receiver.close()
    with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,connection._receive_binding,
            protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted if supply_accepted else None) as reopened:
        assert reopened.media_history==history
        assert reopened.accepted_transfer==job.accepted and not reopened.saved_receipts()
    unpublished(receiving,receiver)


@pytest.mark.parametrize('field',['accepted_sha256','manifest_sha256','version','run_id','source_epoch','media_type',
    'insertion_witness','attempts','entries','extra'])
def test_malformed_history_is_rejected_without_another_reservation_or_target_write(receiving,field):
    connection=receiving[3];receiver=admit(receiving)
    history=receiver._index.media_history;value=deepcopy(history.wire())
    if field in ('accepted_sha256','manifest_sha256'):value[field]='d'*64
    elif field in ('version','source_epoch'):value[field]=True
    elif field=='run_id':value[field]='not-an-original-run'
    elif field=='media_type':value[field]='audio'
    elif field=='insertion_witness':value[field]=1
    elif field=='attempts':value[field][0]['count']=True
    elif field=='entries':value[field][0]['photo_id']='not-an-id'
    else:value[field]=True
    before=connection._catalog.jobs()
    with pytest.raises(TransferError,match='media_history_invalid'):NativeMediaHistory.parse(value,receiver._accepted)
    assert connection._catalog.jobs()==before
    unpublished(receiving,receiver)


def test_foreign_native_history_is_rejected_before_catalog_reservation(receiving):
    connection=receiving[3];receiver=admit(receiving)
    history=replace(receiver._index.media_history,accepted_sha256='e'*64)
    jobs=connection._catalog.jobs();protection=connection._authority.protection
    with pytest.raises(TransferError,match='media_history_invalid'):
        NativeFileReceiveOperation.accept(connection._catalog,receiver._accepted,connection._receive_binding,
            protection.seal,protection.unseal,connection._publication_gate,media_history=history)
    assert connection._catalog.jobs()==jobs
    unpublished(receiving,receiver)


def test_missing_authenticated_anchor_is_not_replaced_with_inferred_empty_history(receiving):
    connection=receiving[3];receiver=admit(receiving)
    index=receiver._index;parent=index._parent;job=receiver.job;protection=connection._authority.protection
    row=index._db.execute('SELECT payload FROM meta').fetchone()[0]
    value=index._open(row,'owner');del value['context']['media_history']
    broken=index._protect(value,'owner')
    with index._db:index._db.execute('UPDATE meta SET payload=?',(broken,))
    receiver.close()
    with pytest.raises(TransferError,match='media_history_invalid'):
        ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,connection._receive_binding,
            protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted)
    unpublished(receiving,receiver)


def test_history_rejects_changed_order_duplicate_ids_and_fabricated_page_counts(receiving):
    connection=receiving[3];receiver=admit(receiving,count=9)
    original=receiver._index.media_history.wire()
    variants=[]
    bad=deepcopy(original);bad['entries'].reverse();variants.append(bad)
    bad=deepcopy(original);bad['entries'][1]['photo_id']=bad['entries'][0]['photo_id'];variants.append(bad)
    bad=deepcopy(original);bad['attempts'][1]['request_id']=bad['attempts'][0]['request_id'];variants.append(bad)
    for count in (0,9,-1,True,'8'):
        bad=deepcopy(original);bad['attempts'][0]['count']=count;variants.append(bad)
    bad=deepcopy(original);bad['attempts'][1]['count']=2;variants.append(bad)
    bad=deepcopy(original);bad['attempts']*=129;variants.append(bad)
    bad=deepcopy(original);bad['media_type']='video';variants.append(bad)
    for bad in variants:
        with pytest.raises(TransferError,match='media_history_invalid'):NativeMediaHistory.parse(bad,receiver._accepted)
    assert receiver._index.media_history.wire()==original
    unpublished(receiving,receiver)


def test_reopen_with_same_manifest_but_different_accepted_targets_cannot_adopt_original_history(receiving):
    connection=receiving[3];receiver=admit(receiving)
    index=receiver._index;parent=index._parent;job=receiver.job;protection=connection._authority.protection
    changed=NativeAcceptedTransfer.capture(job.accepted.manifest,job.accepted.binding,
        {file.id:'another-folder/'+file.path for file in job.accepted.manifest.files},
        job.accepted.destination.path,connection._receive_binding)
    receiver.close()
    with pytest.raises(TransferError,match='acceptance_mismatch'):
        ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,connection._receive_binding,
            protection.seal,protection.unseal,owner=job.owner,accepted=changed)
    with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,connection._receive_binding,
            protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as original:
        assert original.media_history.accepted_sha256==job.accepted.fingerprint
    unpublished(receiving,receiver)
