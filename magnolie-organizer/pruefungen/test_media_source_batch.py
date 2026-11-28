"""Refs #330: actual native all-file roots/statx/book leases, no sender/ready flags."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading
import pytest

from test_media_source_pc import pc, source, mappings, receiving, native, png
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_retention import NativeMediaRetention
from magnolie_file_transfer import CHUNK_BYTES, TransferError


def members(h):
    with NativeCollectionRoot(h.pc_file.parent, lambda: True) as root:
        return root.inventory().members


def select(h, chosen=None):
    return h.source.select_original_batch(h.preferences.issue_action(), h.policy, h.selected, members(h) if chosen is None else chosen)


def two_files(h, *, padded=False):
    h.second_file = h.pc_file.parent / 'z-second.png'
    first = h.raw + (bytes(CHUNK_BYTES + 17) if padded else b'')
    second = png(1) + (bytes(2 * CHUNK_BYTES + 9) if padded else b'')
    h.pc_file.write_bytes(first); h.second_file.write_bytes(second)
    return {h.pc_file.name: first, h.second_file.name: second}


def assert_closed(batch):
    assert batch._root is None and batch._catalog is None
    assert all(not lease._owned for lease in batch._leases.values())


def test_actual_two_file_original_root_one_native_book_lease_and_exact_bounded_chunk_routing(pc):
    h = pc; expected = two_files(h, padded=True)
    action = h.preferences.issue_action()
    batch = h.source.select_original_batch(action, h.policy, h.selected, members(h))
    observation = batch.observation(); body = observation.body
    assert len(body['members']) == 2 and body['total_bytes'] == sum(map(len, expected.values()))
    assert not observation.grants_read_authority and not observation.is_saved_receipt and not observation.permits_retirement
    changed = observation.body; changed['members'].clear(); assert len(batch.observation().body['members']) == 2
    assert not h.source._prepared and not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))
    assert len({os.fstat(lease._owned[-1]).st_ino for lease in batch._leases.values()}) == 2
    with pytest.raises(TransferError): h.source.select_original_batch(action, h.policy, h.selected, members(h))
    with pytest.raises(TransferError, match='prepared_capacity'):
        h.source.freeze(h.preferences.issue_action(), h.policy, h.selected, members(h)[0])
    with batch.original_reader() as reader:
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity(lambda: True, exclusive=True) as competing: assert competing is None
        for file_id, item in body['members'].items():
            actual = bytearray()
            for index in range((item['size'] + CHUNK_BYTES - 1) // CHUNK_BYTES):
                clear = reader.read_chunk(file_id, index)
                try: actual.extend(clear)
                finally: clear[:] = b'\0' * len(clear)
            assert actual == expected[item['path']]
            assert item['local_origin']['file_key'][1] == os.stat(h.pc_file.parent / item['path']).st_ino
        for file_id, index in [('f' * 32, 0), (next(iter(body['members'])), True), (next(iter(body['members'])), -1)]:
            with pytest.raises(TransferError): reader.read_chunk(file_id, index)
    with pytest.raises(TransferError, match='live_lease'): reader.read_chunk(next(iter(body['members'])), 0)
    assert all(lease._owned for lease in batch._leases.values())  # Reader close is not early parent-FD release.
    batch.close(); assert_closed(batch)
    assert h.pc_file.read_bytes() == expected[h.pc_file.name] and h.second_file.read_bytes() == expected[h.second_file.name]


@pytest.mark.parametrize('fault', ['consent', 'intent', 'file', 'book'])
def test_original_batch_revocation_or_changed_file_retires_all_members_without_repair(pc, fault):
    h = pc; expected = two_files(h); batch = select(h); body = batch.observation().body
    if fault == 'consent': h.preferences.configure_sending(h.preferences.issue_action(), h.policy, photos=False, videos=False)
    elif fault == 'intent': h.controller.change('enabled', False)
    elif fault == 'file': h.second_file.write_bytes(png(2))
    else:
        with NativeMediaRetention(h.authority.binding.native_directory) as retention: paused = retention.pause()
    with pytest.raises((TransferError, OSError)):
        with batch.original_reader() as reader: reader.read_chunk(next(iter(body['members'])), 0)
    assert_closed(batch); assert not h.source._prepared
    if fault == 'file': h.second_file.write_bytes(expected[h.second_file.name])
    if fault == 'book':
        from magnolie_telefon import strict_json
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            retention.publish_saved(paused, strict_json((Path(h.authority.binding.native_directory).parent / 'daten.json').read_bytes()))
    with pytest.raises(TransferError):
        with batch.original_reader(): pytest.fail('Metadata restoration revived the original batch')
    assert h.pc_file.read_bytes() == expected[h.pc_file.name]


def test_duplicate_native_member_cannot_create_a_second_origin_or_any_ready_cache(pc):
    h = pc; chosen = members(h)[0]
    with pytest.raises(TransferError, match='original_members'): select(h, (chosen, chosen))
    assert_closed(h.source._original_batch); assert not h.source._prepared
    assert not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))


def test_existing_phone_mapping_is_not_relabelled_as_a_batch_pc_original(pc):
    h = pc; catalog = h.preferences.open_collection_roots()
    try:
        with NativeCollectionRoot(h.target.parent, lambda: True) as root:
            snapshot = catalog.add(catalog.issue_action(), catalog.read(), root, 'images')
            selected = next(record for record in snapshot.roots if record.key == root.key)
            chosen = next(member for member in root.inventory().members if member.key == h.record.file_key)
        with pytest.raises(TransferError, match='existing_mapping_required'):
            h.source.select_original_batch(h.preferences.issue_action(), h.policy, selected, (chosen,))
        assert_closed(h.source._original_batch); assert not h.source._prepared
    finally: catalog.close()


def test_original_batch_cancel_waits_for_actual_filesystem_read_before_closing_any_parent_descriptor(pc, monkeypatch):
    h = pc; expected = two_files(h); batch = select(h); body = batch.observation().body
    entered = threading.Event(); release = threading.Event(); actual = os.preadv
    descriptors = [lease._owned[-1] for lease in batch._leases.values()]
    target = descriptors[0]
    def held(fd, buffers, offset, *args):
        if fd == target:
            entered.set(); assert release.wait(5)
        return actual(fd, buffers, offset, *args)
    monkeypatch.setattr(os, 'preadv', held)
    def read():
        with batch.original_reader() as reader: return reader.read_chunk(next(iter(body['members'])), 0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(read)
        try:
            assert entered.wait(5); batch.close()
            assert not attempt.done() and h.source._gate.locked()
            for fd in descriptors: assert os.fstat(fd).st_size > 0
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                with retention.activity(lambda: True, exclusive=True) as competing: assert competing is None
        finally: release.set()
        with pytest.raises(TransferError): attempt.result(timeout=5)
    assert_closed(batch)
    assert h.pc_file.read_bytes() == expected[h.pc_file.name] and h.second_file.read_bytes() == expected[h.second_file.name]


def test_equal_basenames_under_distinct_actual_parents_keep_full_paths_and_exact_native_file_routing(pc):
    h = pc; expected = {}
    for index, parent in enumerate(('day-a', 'day-b')):
        directory = h.pc_file.parent / parent; directory.mkdir(mode=0o700)
        raw = png(index); (directory / 'photo.png').write_bytes(raw); expected[parent + '/photo.png'] = raw
    chosen = tuple(member for member in members(h) if member.name == 'photo.png')
    assert len(chosen) == 2
    batch = select(h, chosen); body = batch.observation().body
    assert {entry['path'] for entry in body['members'].values()} == set(expected)
    with batch.original_reader() as reader:
        for file_id, entry in body['members'].items():
            actual = bytearray()
            for index in range((entry['size'] + CHUNK_BYTES - 1) // CHUNK_BYTES):
                clear = reader.read_chunk(file_id, index)
                try: actual.extend(clear)
                finally: clear[:] = b'\0' * len(clear)
            assert actual == expected[entry['path']]
    batch.close(); assert_closed(batch)


def test_batch_metadata_or_a_foreign_thread_cannot_adopt_the_actual_native_reader_scope(pc):
    from magnolie_media_source_batch import _NativeCollectionBatchReader
    h = pc; two_files(h); batch = select(h); observation = batch.observation()
    with pytest.raises(TransferError, match='live_lease'): _NativeCollectionBatchReader(observation)
    file_id = next(file_id for file_id, entry in observation.body['members'].items() if entry['path'] == h.pc_file.name)
    with batch.original_reader() as reader:
        with ThreadPoolExecutor(max_workers=1) as pool:
            foreign = pool.submit(reader.read_chunk, file_id, 0)
            with pytest.raises(TransferError, match='live_lease'): foreign.result(timeout=5)
        clear = reader.read_chunk(file_id, 0)
        try: assert clear == h.raw[:CHUNK_BYTES] and len(clear) == min(CHUNK_BYTES, len(h.raw))
        finally: clear[:] = b'\0' * len(clear)
    batch.close(); assert_closed(batch)


def test_changed_ancestor_of_one_member_retires_the_whole_original_before_any_other_file_read(pc):
    h = pc; directory = h.pc_file.parent / 'album'; directory.mkdir(mode=0o700)
    (directory / 'photo.png').write_bytes(png(1))
    batch = select(h); body = batch.observation().body
    untouched = next(file_id for file_id, entry in body['members'].items() if entry['path'] == h.pc_file.name)
    directory.rename(h.pc_file.parent / 'moved-album'); directory.mkdir(mode=0o700)
    with pytest.raises((TransferError, OSError)):
        with batch.original_reader() as reader: reader.read_chunk(untouched, 0)
    assert_closed(batch); assert h.pc_file.read_bytes() == h.raw


def test_partial_original_open_cannot_be_observed_as_an_admitted_whole_batch(pc):
    h = pc; two_files(h); checked = []
    def boundary(phase):
        if phase == 'source_batch_original_open':
            batch = h.source._original_batch
            with pytest.raises(TransferError, match='admitted'): batch.observation()
            checked.append(len(batch._leases))
    h.source._boundary = boundary
    batch = select(h)
    assert sorted(checked) == [1, 2] and len(batch.observation().body['members']) == 2
    batch.close(); assert_closed(batch)
