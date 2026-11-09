"""Actual Linux descriptors/statx; no phone, SEND composition or deletion proof."""
from dataclasses import replace
from pathlib import Path
import os
import struct
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_media_source_collection as collection
from magnolie_file_transfer import TransferError, CHUNK_BYTES


def test_actual_statx_repeated_inventory_and_bounded_read(tmp_path):
    album = tmp_path / 'album';album.mkdir();p = album / 'one.jpg';p.write_bytes(b'actual original')
    with collection.NativeCollectionRoot(tmp_path, lambda:True) as root:
        assert root.mount_id > 0 and len(root.birthtime) == 2
        first = root.inventory();second = root.inventory()
        assert first == second and not first.needs_review and len(first.members) == 1
        member = first.members[0]
        assert not member.grants_read_authority and not member.proves_deletion
        with root.open_member(member) as reader:
            assert reader.read_exact(0, 15) == b'actual original'
            for offset,count in [(-1,1),(0,0),(0,CHUNK_BYTES+1),(15,1),(True,1),(0,True)]:
                with pytest.raises(TransferError):reader.read_exact(offset,count)
            assert reader.read_exact(0,1) == b'a'
        before = member.birthtime;p.write_bytes(b'new actual data')
        after = root.inventory().members[0]
        assert after.key == member.key and after.birthtime == before


def test_private_paths_links_special_files_and_bounds(tmp_path):
    for name in ['Backup','.magnolie-staging']:
        d = tmp_path / name;d.mkdir();(d / 'private.jpg').write_bytes(b'private')
        with pytest.raises(TransferError):collection.NativeCollectionRoot(d, lambda:True)
    (tmp_path / 'good.jpg').write_bytes(b'good')
    os.symlink('good.jpg', tmp_path / 'link.jpg');os.mkfifo(tmp_path / 'fifo')
    (tmp_path / 'empty.jpg').touch()
    with collection.NativeCollectionRoot(tmp_path, lambda:True) as root:
        inventory = root.inventory()
        assert [m.name for m in inventory.members] == ['good.jpg'] and inventory.needs_review
        with pytest.raises(TransferError):root.inventory(maximum_entries=1)
        with pytest.raises(TransferError):root.inventory(maximum_depth=False)
        os.link(tmp_path / 'good.jpg', tmp_path / 'hard.jpg')
        with pytest.raises(TransferError):root.inventory()


def test_depth_cancel_and_native_owner_revival_are_not_permissions(tmp_path):
    (tmp_path / 'album').mkdir();(tmp_path / 'album' / 'one.jpg').write_bytes(b'one')
    live = [True]
    with collection.NativeCollectionRoot(tmp_path, lambda:live[0]) as root:
        with pytest.raises(TransferError):root.inventory(maximum_depth=0)
        with pytest.raises(TransferError):root.inventory(cancelled=lambda:True)
        member = root.inventory().members[0]
        with root.open_member(member) as reader:
            live[0] = False
            with pytest.raises(TransferError):reader.read_exact(0,1)
            live[0] = True
            with pytest.raises(TransferError):reader.read_exact(0,1)
            with pytest.raises(TransferError):root.inventory()


@pytest.mark.parametrize('change', ['rename','replace','ancestor','content','hardlink'])
def test_native_changes_retire_held_reader_without_revival(tmp_path, change):
    album = tmp_path / 'album';album.mkdir();p = album / 'one.jpg';p.write_bytes(b'original')
    with collection.NativeCollectionRoot(tmp_path, lambda:True) as root:
        member = root.inventory().members[0]
        with root.open_member(member) as reader:
            if change == 'rename':p.rename(album / 'moved.jpg')
            elif change == 'replace':p.rename(album / 'old.jpg');p.write_bytes(b'original')
            elif change == 'ancestor':album.rename(tmp_path / 'moved');album.mkdir()
            elif change == 'content':p.write_bytes(b'changed!')
            else:os.link(p, album / 'link.jpg')
            with pytest.raises((TransferError,OSError)):reader.read_exact(0,1)
            if change == 'rename':(album / 'moved.jpg').rename(p)
            elif change == 'replace':p.unlink();(album / 'old.jpg').rename(p)
            elif change == 'ancestor':album.rmdir();(tmp_path / 'moved').rename(album)
            elif change == 'content':p.write_bytes(b'original')
            else:(album / 'link.jpg').unlink()
            with pytest.raises(TransferError):reader.read_exact(0,1)


def test_root_binding_rejects_cross_root_replay_even_same_actual_file(tmp_path):
    a = tmp_path / 'a';b = tmp_path / 'b';a.mkdir(mode=0o700);b.mkdir(mode=0o700);(a / 'one.jpg').write_bytes(b'one')
    with collection.NativeCollectionRoot(a, lambda:True) as first, collection.NativeCollectionRoot(b, lambda:True) as second:
        member = first.inventory().members[0];(a / 'one.jpg').rename(b / 'one.jpg')
        actual = second.inventory().members[0]
        assert actual.key == member.key and actual.birthtime == member.birthtime
        with pytest.raises(TransferError):second.open_member(member)
        with second.open_member(actual) as reader:assert reader.read_exact(0,3) == b'one'
        for invalid in [replace(actual, birthtime=(0,0)),replace(actual, root_mount_id=0),replace(actual, root_birthtime=(0,0))]:
            with pytest.raises(TransferError):second.open_member(invalid)


def test_missing_or_changed_witness_never_falls_back_to_ctime(tmp_path, monkeypatch):
    (tmp_path / 'one.jpg').write_bytes(b'one')
    actual = collection._native_witness
    with collection.NativeCollectionRoot(tmp_path, lambda:True) as root:
        member = root.inventory().members[0]
        with root.open_member(member) as reader:
            def changed(fd):
                birth,mount = actual(fd)
                return (birth[0]+1,birth[1]),mount
            monkeypatch.setattr(collection,'_native_witness',changed)
            with pytest.raises(TransferError):reader.read_exact(0,1)
            monkeypatch.setattr(collection,'_native_witness',actual)
            with pytest.raises(TransferError):reader.read_exact(0,1)
    def missing(fd):raise TransferError('synthetic absent native witness')
    monkeypatch.setattr(collection,'_native_witness',missing)
    with pytest.raises(TransferError):collection.NativeCollectionRoot(tmp_path, lambda:True)


def test_actual_read_close_drains_and_zeroes_owned_buffer(tmp_path, monkeypatch):
    (tmp_path / 'one.jpg').write_bytes(b'original')
    with collection.NativeCollectionRoot(tmp_path, lambda:True) as root:
        reader = root.open_member(root.inventory().members[0])
        entered = threading.Event();release = threading.Event();done = threading.Event();closing = threading.Event()
        actual = os.preadv;buffers = [];errors = []
        def blocked(fd, views, offset):
            n = actual(fd,views,offset);buffers.append(views[0].obj);entered.set()
            assert release.wait(5)
            return n
        monkeypatch.setattr(os,'preadv',blocked)
        def read():
            try:reader.read_exact(0,8)
            except BaseException as error:errors.append(error)
        def close():closing.set();reader.close();done.set()
        worker = threading.Thread(target=read);closer = threading.Thread(target=close)
        worker.start()
        try:
            assert entered.wait(5);closer.start();assert closing.wait(5)
            assert reader._closed.wait(5) and not done.is_set()
        finally:
            release.set();worker.join(5)
            if closer.ident is not None:closer.join(5)
            reader.close()
        assert not worker.is_alive() and not closer.is_alive() and done.is_set()
        assert len(errors) == 1 and isinstance(errors[0],TransferError)
        assert buffers == [bytearray(8)] and reader._owned == ()


def test_root_close_invalidates_but_does_not_claim_member_drain(tmp_path):
    (tmp_path / 'one.jpg').write_bytes(b'one')
    root = collection.NativeCollectionRoot(tmp_path, lambda:True)
    reader = root.open_member(root.inventory().members[0]);root.close()
    try:
        assert reader._owned
        with pytest.raises(TransferError):reader.read_exact(0,1)
    finally:reader.close()


@pytest.mark.parametrize('mask,mount,nanos', [(0,1,0),(0x800,1,0),(0x1800,0,0),(0x1800,1,1_000_000_000)])
def test_incomplete_kernel_witness_is_hold_not_a_synthetic_generation(tmp_path, monkeypatch, mask, mount, nanos):
    def incomplete(fd, path, flags, requested, data):
        struct.pack_into('=I',data,0,mask);struct.pack_into('=qI',data,80,0,nanos);struct.pack_into('=Q',data,144,mount)
        return 0
    monkeypatch.setattr(collection,'_statx_query',lambda:incomplete)
    with pytest.raises(TransferError):collection.NativeCollectionRoot(tmp_path,lambda:True)


def test_root_path_replacement_cannot_adopt_a_held_original(tmp_path):
    selected = tmp_path / 'selected';selected.mkdir(mode=0o700);(selected / 'one.jpg').write_bytes(b'one')
    with collection.NativeCollectionRoot(selected,lambda:True) as root:
        with root.open_member(root.inventory().members[0]) as reader:
            selected.rename(tmp_path / 'old');selected.mkdir(mode=0o700)
            with pytest.raises(TransferError):reader.read_exact(0,1)
            selected.rmdir();(tmp_path / 'old').rename(selected)
            with pytest.raises(TransferError):root.inventory()
