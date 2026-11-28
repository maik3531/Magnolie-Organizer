"""Refs #330: actual original-root encrypted batch cache/job/reader, no SEND."""
from hashlib import sha256
from contextlib import nullcontext
from pathlib import Path
import os
import pytest

from test_media_source_batch import pc, source, mappings, receiving, native, two_files, select, assert_closed
from magnolie_file_transfer import CHUNK_BYTES, TransferError
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_batch_cache import _NativeBatchCacheReader, _NativeBatchCacheWriter


def test_actual_batch_cache_has_one_complete_native_job_and_exact_encrypted_file_routing(pc, monkeypatch):
    h = pc; expected = two_files(h); batch = select(h)
    cache = batch.freeze_cache(); jobs = _NativeSourceJobs(h.authority)
    record = jobs.require_version(batch._id, cache._job_version)
    assert record.body['format'] == 4 and record.state == 'cache_ready'
    assert len(cache.manifest.files) == 2 and cache.manifest.source_id == batch._id
    assert record.body['members'] == batch.observation().body['members']
    # Protected DATA still needs exact whole-root validation. Re-sealing an
    # incomplete/aliased map must not manufacture native cache authority.
    import copy
    from magnolie_telefon import canonical
    for fault in ('subset', 'alias', 'path', 'format'):
        changed = copy.deepcopy(record.body)
        if fault == 'subset':
            changed['manifest']['files'].pop()
            changed['manifest']['total_bytes'] = sum(f['size'] for f in changed['manifest']['files'])
        elif fault == 'alias':
            entries = list(changed['members'].values())
            entries[1]['local_origin']['file_key'] = entries[0]['local_origin']['file_key']
        elif fault == 'path': next(iter(changed['members'].values()))['path'] = 'wrong.png'
        else: changed['format'] = 3
        cipher = h.authority.protection.seal(canonical(changed), jobs._key(batch._id))
        with pytest.raises(TransferError): jobs._decode(batch._id, cipher, jobs._database_key)
    assert not cache.grants_read_authority and not cache.is_saved_receipt and not cache.permits_retirement
    assert not h.source._prepared  # Old single-file senders cannot take this cache.
    with jobs._database() as (db, key):
        assert db.execute('SELECT COUNT(*) FROM meta WHERE key LIKE ?', (jobs._prefix + '%',)).fetchone()[0] == 1
    for file in cache.manifest.files:
        assert file.sha256 == sha256(expected[file.path]).hexdigest()
        for index in range(file.chunks):
            cipher = (cache.directory / _NativeBatchCacheWriter.chunk_name(file.id, index)).read_bytes()
            assert len(cipher) == min(CHUNK_BYTES, file.size - index * CHUNK_BYTES) + 28
            assert cipher != expected[file.path][index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
    with pytest.raises(TransferError): _NativeBatchCacheReader(batch.observation(), None)
    proof = (cache.directory / 'manifest.enc').stat()
    reads = []
    pread = os.pread
    def count_manifest(fd, size, offset):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (proof.st_dev, proof.st_ino):
            reads.append((size, offset))
        return pread(fd, size, offset)
    monkeypatch.setattr(os, 'pread', count_manifest)
    with batch.cached_reader() as reader:
        assert reads == [(proof.st_size + 1, 0)]
        monkeypatch.setattr(os, 'pread', pread)
        for file in cache.manifest.files:
            actual = bytearray()
            for index in range(file.chunks):
                data = reader.read_chunk(file.id, index)
                try: actual.extend(data)
                finally: data[:] = b'\0' * len(data)
            assert actual == expected[file.path]
        with pytest.raises(TransferError): reader.read_chunk(cache.manifest.files[0].id, True)
    with pytest.raises(TransferError): reader.read_chunk(cache.manifest.files[0].id, 0)
    with pytest.raises(TransferError, match='already_prepared'): batch.freeze_cache()
    # New single-file admission must see EVERY batch origin, not just file0.
    for entry in record.body['members'].values():
        with pytest.raises(TransferError, match='existing_source_held'): jobs.require_new_pc_origin(entry['local_origin'])
    batch.close(); assert_closed(batch)
    assert all((h.pc_file.parent / path).read_bytes() == raw for path, raw in expected.items())


def test_batch_manifest_replacement_during_authentication_does_not_admit_reader(pc, monkeypatch):
    h = pc; expected = two_files(h); batch = select(h); cache = batch.freeze_cache()
    proof = cache.directory / 'manifest.enc'
    raw = proof.read_bytes(); swapped = []
    unseal = h.authority.protection.unseal
    def replace_after_unseal(cipher, domain):
        plain = unseal(cipher, domain)
        if '/manifest.enc/' in domain:
            # Give the pathname the same ciphertext on a different inode.
            replacement = cache.directory / 'replacement.enc'
            replacement.write_bytes(raw); replacement.chmod(0o600)
            replacement.replace(proof); swapped.append(True)
        return plain
    monkeypatch.setattr(h.authority.protection, 'unseal', replace_after_unseal)
    with pytest.raises(TransferError, match='media_source_cache_original_member_required'):
        with batch.cached_reader():
            pytest.fail('a replaced manifest admitted an original-cache reader')
    assert swapped == [True] and proof.read_bytes() == raw
    batch.close(); assert_closed(batch)
    assert all((h.pc_file.parent / name).read_bytes() == data for name, data in expected.items())


@pytest.mark.parametrize('withdraw', [None, 'common_record_changed', 'ready_record_changed', 'original_revoked'])
def test_local_batch_verification_brackets_the_sweep_without_repeating_metadata_per_chunk(pc, monkeypatch, withdraw):
    from collections import Counter

    h = pc; two_files(h); batch = select(h); cache = batch.freeze_cache()
    observations = Counter()
    def boundary(phase):
        if phase != 'source_batch_cache_read': return
        observations[phase] += 1
        if observations[phase] != 1: return
        if withdraw == 'common_record_changed':
            original = cache.directory / 'intent.enc'
            raw = original.read_bytes()
            original.write_bytes(raw[:-1] + bytes((raw[-1] ^ 1,)))
        elif withdraw == 'ready_record_changed':
            jobs = _NativeSourceJobs(h.authority)
            with jobs._database() as (db, _):
                name = jobs._key(batch._id)
                cipher, = db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()
                db.execute('UPDATE meta SET value=? WHERE key=?',(cipher[:-1]+bytes((cipher[-1]^1,)),name))
        elif withdraw == 'original_revoked': batch._closed.set()
    denied = {'ready_record_changed': 'media_source_catalog_membership_changed',
        'original_revoked': 'media_source_batch_retired'}
    with pytest.raises(TransferError, match=denied[withdraw]) if withdraw in denied else nullcontext():
        with batch.cached_reader() as reader:
            def no_second_decode(*args):
                pytest.fail('The opened reader already decoded its exact ready record')
            monkeypatch.setattr(reader._jobs, '_decode', no_second_decode)
            read = reader._read
            def counted(name, witness):
                if name in ('manifest.enc', 'intent.enc', 'copying.enc'): observations[name] += 1
                return read(name, witness)
            monkeypatch.setattr(reader, '_read', counted)
            h.source._boundary = boundary
            if withdraw == 'common_record_changed':
                with pytest.raises(TransferError, match='media_source_cache_original_member_required'): reader.verify()
            elif withdraw in denied: reader.verify()
            else:
                reader.verify()
                assert {name: observations[name] for name in ('manifest.enc', 'intent.enc', 'copying.enc')} == dict.fromkeys(
                    ('manifest.enc', 'intent.enc', 'copying.enc'), 2)
    assert observations['source_batch_cache_read'] == (1 if withdraw in ('ready_record_changed','original_revoked') else
        sum(file.chunks for file in cache.manifest.files))
    batch.close(); assert_closed(batch)


@pytest.mark.parametrize('fault', ['original', 'cancel', 'cache'])
def test_partial_copy_or_changed_earlier_encrypted_member_never_marks_whole_batch_ready(pc, fault):
    h = pc; two_files(h); batch = select(h); calls = []
    def boundary(phase):
        if phase != 'source_cache_chunk_durable': return
        calls.append(phase)
        if fault == 'original' and len(calls) == 1: h.second_file.write_bytes(b'changed original')
        elif fault == 'cancel' and len(calls) == 1: batch.close()
        elif fault == 'cache' and len(calls) == 2:
            stage = next(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))
            first_id = next(iter(batch._entries))
            member = stage / _NativeBatchCacheWriter.chunk_name(first_id, 0)
            raw = bytearray(member.read_bytes()); raw[-1] ^= 1; member.write_bytes(raw)
    h.source._boundary = boundary
    with pytest.raises(TransferError): batch.freeze_cache()
    assert batch._cache is None and not h.source._prepared
    jobs = _NativeSourceJobs(h.authority); planned = jobs.lookup(batch._id)
    assert planned is not None and planned.state == 'cache_planned'
    assert_closed(batch)
    with pytest.raises(TransferError):
        with batch.cached_reader(): pytest.fail('Partial cache reopened')


@pytest.mark.parametrize('fault', ['substitute', 'foreign-thread', 'revoke'])
def test_native_batch_cache_read_denies_changed_member_foreign_thread_or_revoked_original_scope(pc, fault):
    from concurrent.futures import ThreadPoolExecutor
    h = pc; two_files(h); batch = select(h); cache = batch.freeze_cache()
    file = cache.manifest.files[-1]
    with pytest.raises(TransferError) if fault == 'revoke' else nullcontext():
        with batch.cached_reader() as reader:
            if fault == 'foreign-thread':
                with ThreadPoolExecutor(max_workers=1) as pool:
                    foreign = pool.submit(reader.read_chunk, file.id, 0)
                    with pytest.raises(TransferError): foreign.result(timeout=5)
                data = reader.read_chunk(file.id, 0); data[:] = b'\0' * len(data)
            elif fault == 'substitute':
                name = cache.directory / _NativeBatchCacheWriter.chunk_name(file.id, 0)
                raw = name.read_bytes(); name.rename(name.with_suffix('.old')); name.write_bytes(raw); name.chmod(0o600)
                with pytest.raises(TransferError): reader.read_chunk(file.id, 0)
                name.unlink(); name.with_suffix('.old').rename(name)
            else:
                batch._closed.set()
                with pytest.raises(TransferError): reader.read_chunk(file.id, 0)
    batch.close(); assert_closed(batch)


@pytest.mark.parametrize('cancel', ['batch', 'reader'])
def test_cache_cancel_keeps_native_parent_and_book_lease_until_actual_cipher_read_finishes(pc, monkeypatch, cancel):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from magnolie_media_retention import NativeMediaRetention
    h = pc; two_files(h); batch = select(h); cache = batch.freeze_cache()
    file = cache.manifest.files[0]; entered = threading.Event(); release = threading.Event(); actual = os.pread
    shared = {}
    def blocked(fd, size, offset):
        if (threading.get_ident() == shared.get('thread') and shared.get('armed')
                and os.path.basename(os.readlink('/proc/self/fd/%d' % fd)) == _NativeBatchCacheWriter.chunk_name(file.id, 0)):
            shared['cipher_fd'] = fd; entered.set(); assert release.wait(5)
        return actual(fd, size, offset)
    monkeypatch.setattr(os, 'pread', blocked)
    def read():
        with batch.cached_reader() as reader:
            shared.update(reader=reader, root=reader._root, parent=reader._parent, thread=threading.get_ident(), armed=True)
            return reader.read_chunk(file.id, 0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(read)
        try:
            assert entered.wait(15)
            if cancel == 'batch': batch.close()
            else: shared['reader'].close()
            assert not attempt.done() and h.source._gate.locked()
            for key in ('root', 'parent', 'cipher_fd'): os.fstat(shared[key])
            assert all(lease._owned for lease in batch._leases.values())
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                with retention.activity(lambda: True, exclusive=True) as competing: assert competing is None
        finally: release.set()
        with pytest.raises(TransferError): attempt.result(timeout=15)
    assert_closed(batch)
