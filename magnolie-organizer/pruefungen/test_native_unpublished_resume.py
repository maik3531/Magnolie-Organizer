"""Native closed-owner proof is consumed once; absence never grants publication."""
from pathlib import Path
import os
import sys

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_file_offer import create_offer
from magnolie_catalog_membership import CatalogMembership
from magnolie_file_publish import NativeFilePublisher
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,accept,chunk,reconnect


def admitted(fixture):
    connection=fixture[3];_,full=accept(fixture)
    request=connection.request_next_chunk();fixture[0]._payload(fixture[1],fixture[2],chunk(request,b'hello'))
    return connection._run.receiver,full


def resume(fixture,job):
    offered=create_offer(job.accepted.manifest)
    fixture[0]._payload(fixture[1],fixture[2],offered)
    fixture[3].resume_pending_offer(fixture[3].issue_receive_action(),offered['message_id'],job.owner)
    return fixture[3]._run.receiver


def detached(fixture,receiver):
    receiver.close();fixture[3]._run=None


def test_clean_native_end_survives_reconnection_and_new_consent_then_publishes_exact_original_target(receiving):
    old,full=admitted(receiving);job=old.job
    detached(receiving,old)
    assert old._unpublished_end and old._closed
    before=old._unpublished_end.copy()
    with reconnect(receiving) as fresh:
        receiver=resume(fresh,job)
        assert receiver._publisher is not None and receiver.progress().phase=='receiving'
        assert receiver.progress().verified_bytes==len(b'hello')
        records=fresh[3]._catalog._registry.attempts(fresh[3]._catalog.jobs())
        assert [record['operation'] for record,_ in records]==['closed','consumed']
        assert records[0][0]['evidence']==before
        fresh[3].publish_received(fresh[3].issue_receive_action())
        assert (fresh[4]/full.files[0].path).read_bytes()==b'hello'
        assert receiver._index.saved_receipts()


@pytest.mark.parametrize('boundary',['before-publication','published'])
def test_attempted_publication_never_earns_clean_end_and_missing_target_does_not_recreate_tombstone(receiving,boundary):
    receiver,full=admitted(receiving);job=receiver.job
    def fail(at):
        if at==boundary:raise OSError('Fixture interrupted publication')
    receiver._publisher._boundary=fail
    with pytest.raises(OSError):receiving[3].publish_received(receiving[3].issue_receive_action())
    target=receiving[4]/full.files[0].path
    if boundary=='published':
        assert target.read_bytes()==b'hello'
        target.unlink() # Explicit user deletion in this private fixture.
    detached(receiving,receiver)
    assert receiver._unpublished_end is None
    with reconnect(receiving) as fresh:
        restored=resume(fresh,job)
        assert restored._publisher is None and restored.progress().phase=='receiving_publication_repair_pending'
        with pytest.raises(TransferError,match='publication_repair_required'):
            fresh[3].publish_received(fresh[3].issue_receive_action())
        assert not target.exists()


def test_abrupt_descriptor_end_is_not_a_positive_native_stop_even_with_empty_cache_and_journal(receiving):
    receiver,full=admitted(receiving);job=receiver.job
    for value in (receiver._publisher,receiver._journal,receiver._stage,receiver._index):value.close()
    detached(receiving,receiver)
    assert receiver._unpublished_end is None
    with reconnect(receiving) as fresh:
        restored=resume(fresh,job)
        assert restored._publisher is None
        with pytest.raises(TransferError,match='publication_repair_required'):
            fresh[3].publish_received(fresh[3].issue_receive_action())
        assert not (fresh[4]/full.files[0].path).exists()


def test_consumed_proof_cannot_be_replayed_after_second_owner_dies_before_publication(receiving):
    receiver,_=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    with reconnect(receiving) as first:
        renewed=resume(first,job)
        assert renewed._publisher is not None
        for value in (renewed._publisher,renewed._journal,renewed._stage,renewed._index):value.close()
        detached(first,renewed)
        with reconnect(first) as second:
            restored=resume(second,job)
            assert restored._publisher is None
            records=second[3]._catalog._registry.attempts(second[3]._catalog.jobs())
            assert [record['operation'] for record,_ in records]==['closed','consumed']
            with pytest.raises(TransferError,match='publication_repair_required'):
                second[3].publish_received(second[3].issue_receive_action())


def test_replaced_original_publication_cache_is_preserved_and_does_not_consume_proof(receiving):
    receiver,full=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    cache=receiving[4]/('.magnolie-publication-'+job.owner);held=cache.with_name(cache.name+'-held-fixture')
    cache.rename(held);cache.mkdir(mode=0o700)
    unknown=cache/'user-owned';unknown.write_bytes(b'preserve unfamiliar cache entry')
    try:
        with reconnect(receiving) as fresh:
            with pytest.raises(TransferError,match='unpublished_end_changed'):resume(fresh,job)
            records=fresh[3]._catalog._registry.attempts(fresh[3]._catalog.jobs())
            assert [record['operation'] for record,_ in records]==['closed']
            assert unknown.read_bytes()==b'preserve unfamiliar cache entry'
            assert held.is_dir() and not (fresh[4]/full.files[0].path).exists()
    finally:
        # Restore only the exact private directories/files created by this test.
        unknown.unlink();cache.rmdir();held.rename(cache)


def test_orderly_native_owner_end_after_revocation_records_no_read_grant_but_allows_fresh_bound_resume(receiving):
    receiver,_=admitted(receiving);job=receiver.job
    receiving[3]._authority.revoke()
    detached(receiving,receiver)
    assert receiver._unpublished_end and receiver._publisher._closed
    with pytest.raises(TransferError):receiver._accepted.verify(receiving[3]._receive_binding)
    with reconnect(receiving) as fresh:
        restored=resume(fresh,job)
        assert restored._publisher is not None
        assert restored._current()==job.accepted.binding


def test_multiple_clean_stops_each_need_a_new_positive_end_and_consume_it_once(receiving):
    receiver,full=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    with reconnect(receiving) as first:
        renewed=resume(first,job)
        assert renewed._publisher is not None
        detached(first,renewed)
        with reconnect(first) as second:
            restored=resume(second,job)
            assert restored._publisher is not None
            events=second[3]._catalog._registry.attempts(second[3]._catalog.jobs())
            assert [event['operation'] for event,_ in events]==['closed','consumed','closed','consumed']
            assert events[1][0]['evidence']['closed_sha256']==events[0][1]
            assert events[3][0]['evidence']['closed_sha256']==events[2][1]
            second[3].publish_received(second[3].issue_receive_action())
            assert (second[4]/full.files[0].path).read_bytes()==b'hello'


def test_failure_after_commit_does_not_expose_a_writer_or_replay_the_consumed_end(receiving,monkeypatch):
    receiver,full=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    fsync=os.fsync;failed=[]
    with reconnect(receiving) as first:
        first[3]._open_catalog(allow_create=False)
        registry=first[3]._catalog._registry
        def lose_readback(fd):
            if (fd==registry.fd and not failed and not registry.db.in_transaction
                    and registry.db.execute('SELECT count(*) FROM publication_attempts').fetchone()==(2,)):
                failed.append(True);raise OSError('Fixture lost consumed-proof postcommit sync')
            return fsync(fd)
        monkeypatch.setattr(os,'fsync',lose_readback)
        with pytest.raises(TransferError):resume(first,job)
        assert failed and (first[3]._run.receiver is None or first[3]._run.receiver._publisher is None)
        monkeypatch.setattr(os,'fsync',fsync)
        with reconnect(first) as second:
            restored=resume(second,job)
            assert restored._publisher is None
            events=second[3]._catalog._registry.attempts(second[3]._catalog.jobs())
            assert [event['operation'] for event,_ in events]==['closed','consumed']
            assert not (second[4]/full.files[0].path).exists()


def test_revocation_while_consuming_end_cannot_create_writable_journal_or_publisher(receiving,monkeypatch):
    receiver,full=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    with reconnect(receiving) as fresh:
        fresh[3]._open_catalog(allow_create=False)
        catalog=fresh[3]._catalog;seal=catalog._seal;revoked=[]
        def revoke(data,domain):
            if '/publication-attempt/' in domain and b'"operation":"consumed"' in data:
                revoked.append(True);fresh[3]._authority.revoke()
            return seal(data,domain)
        monkeypatch.setattr(catalog,'_seal',revoke)
        with pytest.raises(TransferError):resume(fresh,job)
        assert revoked and fresh[3]._run.receiver is None
        records=catalog._registry.attempts(catalog.jobs())
        assert [record['operation'] for record,_ in records]==['closed']
        assert not (fresh[4]/full.files[0].path).exists()


def test_missing_consumed_record_is_detected_by_membership_before_any_republication(receiving):
    receiver,full=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    with reconnect(receiving) as first:
        renewed=resume(first,job)
        for value in (renewed._publisher,renewed._journal,renewed._stage,renewed._index):value.close()
        detached(first,renewed)
        registry=first[3]._catalog._registry
        with registry.db:registry.db.execute('DELETE FROM publication_attempts WHERE owner=? AND revision=2',(job.owner,))
        with pytest.raises(TransferError,match='membership_changed'):first[3]._catalog.jobs()
        with reconnect(first) as second:
            with pytest.raises(TransferError,match='membership_changed'):resume(second,job)
            assert second[3]._run is None and not (second[4]/full.files[0].path).exists()


def test_history_capacity_never_discards_consumed_proof_to_allow_another_attempt(receiving,monkeypatch):
    monkeypatch.setattr(CatalogMembership,'MAX_ATTEMPTS',2)
    receiver,_=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    with reconnect(receiving) as first:
        renewed=resume(first,job)
        assert renewed._publisher is not None
        with pytest.raises(TransferError,match='publication_history_limit'):renewed.close()
        assert renewed._closed and renewed._publisher._closed and renewed._stage._closed
        first[3]._run=None
        records=first[3]._catalog._registry.attempts(first[3]._catalog.jobs())
        assert [record['operation'] for record,_ in records]==['closed','consumed']
        with reconnect(first) as second:
            restored=resume(second,job)
            assert restored._publisher is None
            assert second[3]._catalog._registry.attempts(second[3]._catalog.jobs())==records


def test_serialized_end_or_old_consumed_permit_cannot_open_another_native_writer(receiving):
    receiver,_=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    evidence=receiver._unpublished_end
    with reconnect(receiving) as fresh:
        renewed=resume(fresh,job);catalog=fresh[3]._catalog
        records=catalog._registry.attempts(catalog.jobs())
        with pytest.raises(TransferError):catalog.record_unpublished_end(dict(evidence),evidence)
        with pytest.raises(TransferError):catalog.record_unpublished_end(renewed,evidence)
        with pytest.raises(TransferError):
            renewed._journal._renew_unpublished(renewed,catalog,object(),evidence['journal_key'])
        with pytest.raises(TransferError):
            NativeFilePublisher(job.accepted.destination.path,job.accepted.manifest,job.accepted.binding,
                renewed._current,renewed._publisher._publication_gate,owner=job.owner,targets=dict(job.accepted.targets),
                journal=renewed._journal,accepted=job.accepted,
                _renewal=(renewed,catalog,object(),evidence['publication_key']))
        assert catalog._registry.attempts(catalog.jobs())==records
        assert renewed._publisher._cache_entries()==set()


def test_concurrent_native_membership_cipher_change_is_preserved_before_consuming_end(receiving,monkeypatch):
    receiver,_=admitted(receiving);job=receiver.job;detached(receiving,receiver)
    with reconnect(receiving) as fresh:
        fresh[3]._open_catalog(allow_create=False)
        catalog=fresh[3]._catalog;registry=catalog._registry;seal=catalog._seal;concurrent=[]
        def change(data,domain):
            if '/publication-attempt/' in domain and b'"operation":"consumed"' in data and not concurrent:
                old=registry.db.execute('SELECT payload FROM head WHERE id=1').fetchone()[0]
                new=seal(catalog._unseal(old,catalog._domain+'membership-head'),catalog._domain+'membership-head')
                with registry.db:registry.db.execute('UPDATE head SET payload=? WHERE id=1',(new,))
                concurrent.append(new)
            return seal(data,domain)
        monkeypatch.setattr(catalog,'_seal',change)
        with pytest.raises(TransferError,match='membership_cas_changed'):resume(fresh,job)
        assert concurrent and registry.db.execute('SELECT payload FROM head WHERE id=1').fetchone()[0]==concurrent[0]
        assert registry.db.execute('SELECT count(*) FROM publication_attempts').fetchone()==(1,)
        assert fresh[3]._run.receiver is None


def test_corrupt_native_index_cannot_mint_end_proof_or_prevent_actual_resource_close(receiving):
    receiver,full=admitted(receiving);job=receiver.job
    blob=receiver._index._db.execute('SELECT payload FROM meta WHERE id=1').fetchone()[0]
    corrupt=blob[:-1]+bytes([blob[-1]^1])
    with receiver._index._db:receiver._index._db.execute('UPDATE meta SET payload=? WHERE id=1',(corrupt,))
    detached(receiving,receiver)
    assert receiver._unpublished_end is None
    assert all(value._closed for value in (receiver._publisher,receiver._journal,receiver._stage,receiver._index))
    assert receiving[3]._catalog._registry.attempts(receiving[3]._catalog.jobs())==()
    with reconnect(receiving) as fresh:
        with pytest.raises(InvalidTag):resume(fresh,job)
        assert fresh[3]._run is None
        assert not (fresh[4]/full.files[0].path).exists()
