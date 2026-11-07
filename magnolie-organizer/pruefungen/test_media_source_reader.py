"""Prepared-source/book-bound local cache reads, never network send grants."""
from pathlib import Path
import os
import sys
import threading

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_retention import NativeMediaRetention
from test_media_source_cache import freeze,decode
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native


def test_cached_version_is_read_only_under_live_preparation_and_old_reader_cannot_renew_into_a_new_lease(source):
    h=source;cached=freeze(h);job=cached.manifest.source_id
    from magnolie_telefon import strict_json
    intent=strict_json(decode(h,cached.directory/'intent.enc'))
    assert intent['format']==2 and intent['book_version']==cached._book_version
    h.target.write_bytes(b'a later PC edit must not change the frozen version')
    with h.source.prepared_cache(job) as reader:
        assert reader.manifest==cached.manifest and reader.read_chunk(0)==b'hello'
    with pytest.raises(TransferError):reader.read_chunk(0)
    with h.source.prepared_cache(job) as fresh:
        assert fresh.read_chunk(0)==b'hello'
        with pytest.raises(TransferError):reader.read_chunk(0)
    assert h.target.read_bytes()==b'a later PC edit must not change the frozen version'
    assert not cached.grants_read_authority and not h.preferences.local_grant(True).grants.send_files


def test_frozen_metadata_and_another_native_owner_do_not_reconstruct_source_read_authority(source):
    h=source;cached=freeze(h)
    other=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        with pytest.raises(TransferError,match='prepared_owner_required'):
            with other.prepared_cache(cached.manifest.source_id):pytest.fail('Metadata was promoted to READ')
    finally:other.close()
    with pytest.raises(TransferError,match='prepared_owner_required'):
        with h.source.prepared_cache('f'*32):pytest.fail('Unknown job was adopted')
    with h.source.prepared_cache(cached.manifest.source_id) as reader:assert reader.read_chunk(0)==b'hello'


def test_saved_book_pause_permanently_retires_old_preparation_without_adopting_new_book_or_touching_cache(source):
    h=source;cached=freeze(h);before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:token=retention.pause()
    with pytest.raises(TransferError,match='original_book_required'):
        with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Old book was replaced')
    from magnolie_telefon import strict_json
    directory=Path(h.authority.binding.native_directory)
    with NativeMediaRetention(directory) as retention:retention.publish_saved(token,strict_json((directory.parent/'daten.json').read_bytes()))
    with pytest.raises(TransferError,match='prepared_retired'):
        with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Retired preparation revived')
    assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before


def test_local_source_consent_withdrawal_denies_even_an_authentic_completed_cache(source):
    h=source;cached=freeze(h)
    h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    with pytest.raises(TransferError,match='local_consent_required'):
        with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Stored cache revived source consent')
    assert (cached.directory/'manifest.enc').exists() and h.target.read_bytes()==b'hello'


@pytest.mark.parametrize('change',['cipher','same_bytes_new_inode'])
def test_cache_membership_rejects_mutated_or_replaced_members_without_plaintext_or_cleanup(source,change):
    h=source;cached=freeze(h);path=cached.directory/'chunk-00000000.enc';original=path.read_bytes()
    if change=='cipher':path.write_bytes(original[:-1]+bytes([original[-1]^1]))
    else:
        path.rename(cached.directory.parent/'held-original-cipher-fixture')
        path.write_bytes(original);path.chmod(0o600)
    with pytest.raises((TransferError,InvalidTag)):
        with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Changed cache member was adopted')
    assert path.exists() and h.target.read_bytes()==b'hello'
    with pytest.raises(TransferError,match='prepared_retired'):
        with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Failed preparation was renewed')


def test_cancel_during_actual_cache_read_retains_native_os_lane_until_io_ends_and_returns_no_plaintext(source,monkeypatch):
    h=source;cached=freeze(h);key=(cached.directory/'chunk-00000000.enc').stat()
    key=key.st_dev,key.st_ino
    entered=threading.Event();release=threading.Event();ended=threading.Event();results=[];calls=[0];pread=os.pread
    def blocked(fd,size,offset):
        value=os.fstat(fd)
        if (value.st_dev,value.st_ino)==key and offset==0:
            calls[0]+=1
            if calls[0]==2:entered.set();assert release.wait(8)
        return pread(fd,size,offset)
    monkeypatch.setattr(os,'pread',blocked)
    def work():
        try:
            with h.source.prepared_cache(cached.manifest.source_id) as reader:results.append(reader.read_chunk(0))
        except BaseException as error:results.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start()
    try:
        assert entered.wait(5);h.source.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5)
    assert ended.is_set() and not worker.is_alive() and len(results)==1 and isinstance(results[0],TransferError)
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:
        with retention.activity() as lease:assert lease is not None
