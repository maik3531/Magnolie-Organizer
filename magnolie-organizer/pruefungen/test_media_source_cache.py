"""Actual guarded encrypted source-cache bytes; no sender or restart adoption."""
from pathlib import Path
from hashlib import sha256
import os
import sys

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_telefon import canonical,strict_json
from magnolie_media_source import NativeMappedMediaSource
from magnolie_photo_destination import media_path_is_excluded
from magnolie_file_transfer import TransferError,CHUNK_BYTES
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native


def freeze(h,owner=None):
    return (owner or h.source).freeze(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256)


def stage(h):return next(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))


def decode(h,path):
    root=path.parent.stat();value=path.stat();peer=h.authority.current_peer()
    scope=sha256(canonical(dict(local_id=h.authority.identity.receiver_id,local_key=h.authority.identity.receiver_identity_sha256,
        peer_id=peer.peer_id,peer_key=peer.identity_sha256))).hexdigest()
    domain='native-media-source-cache-v1/'+scope+'/'+str(root.st_dev)+':'+str(root.st_ino)+'/'+path.name+'/'+str(value.st_dev)+':'+str(value.st_ino)
    return h.authority.protection.unseal(path.read_bytes(),domain)


def test_private_source_cache_paths_are_recursively_excluded_without_classifying_ordinary_media():
    root='/Pictures/.magnolie-source-'+'a'*32+'.part'
    assert media_path_is_excluded(root) and media_path_is_excluded(root+'/nested/original.jpg')
    assert not media_path_is_excluded('/Pictures/ordinary-source/original.jpg')


def test_native_source_cache_preserves_multichunk_original_bytes_and_native_lineage_without_plaintext_or_hardlinks(source):
    h=source;raw=(b'original JPEG/MP4 bytes, no lossy transform\x00'*4000)+b'end'
    h.target.write_bytes(raw);before=h.target.stat();cached=freeze(h)
    intent=strict_json(decode(h,cached.directory/'intent.enc'));proof=strict_json(decode(h,cached.directory/'manifest.enc'))
    assert intent['state']=='planned' and proof['state']=='sealed'
    assert intent['original_reference']==h.record.phone_original_reference()
    assert proof['manifest']==cached.manifest.wire() and cached.manifest.total_bytes==len(raw)
    assert cached.manifest.files[0].sha256==sha256(raw).hexdigest()
    assert cached.original_references=={cached.manifest.files[0].id:h.record.phone_original_reference()}
    restored=b''.join(decode(h,cached.directory/('chunk-%08x.enc'%index)) for index in range(cached.manifest.files[0].chunks))
    assert restored==raw and h.target.read_bytes()==raw
    assert h.target.stat().st_ino==before.st_ino and h.target.stat().st_mtime_ns==before.st_mtime_ns
    for path in cached.directory.iterdir():
        assert path.stat().st_nlink==1 and not path.stat().st_mode&0o077
        assert path.stat().st_ino!=before.st_ino and raw[:32] not in path.read_bytes()
    assert media_path_is_excluded(cached.directory) and media_path_is_excluded(cached.directory/'nested'/'original.jpg')
    assert not cached.grants_read_authority and not cached.is_saved_receipt and not cached.proves_deletion
    assert not h.preferences.local_grant(True).grants.send_files


def test_existing_source_cache_never_overwrites_adopts_or_duplicates_even_a_verified_job(source):
    h=source;cached=freeze(h);before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    with pytest.raises(TransferError,match='cache_existing_hold'):freeze(h)
    assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before and h.target.read_bytes()==b'hello'


def test_interrupted_source_cache_keeps_durable_intent_and_original_bytes_without_sealed_manifest_or_retry_adoption(source):
    h=source
    def stop(phase):
        if phase=='source_cache_chunk_durable':owner.close()
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=stop)
    try:
        with pytest.raises(TransferError):freeze(h,owner)
    finally:owner.close()
    root=stage(h);assert (root/'intent.enc').exists() and (root/'copying.enc').exists()
    assert (root/'chunk-00000000.enc').exists() and not (root/'manifest.enc').exists()
    before={p.name:p.read_bytes() for p in root.iterdir()}
    with pytest.raises(TransferError,match='cache_existing_hold'):freeze(h)
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before and h.target.read_bytes()==b'hello'


@pytest.mark.parametrize('change',['cipher','unknown_entry'])
def test_source_cache_readback_rejects_changed_cipher_or_foreign_child_without_cleanup_or_false_completion(source,change):
    h=source
    def mutate(phase):
        if phase!='source_cache_chunk_durable':return
        root=stage(h)
        if change=='cipher':
            path=root/'chunk-00000000.enc';blob=path.read_bytes();path.write_bytes(blob[:-1]+bytes([blob[-1]^1]))
        else:(root/'foreign-user-file').write_bytes(b'preserve this unrelated fixture data')
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=mutate)
    try:
        with pytest.raises((TransferError,InvalidTag)):freeze(h,owner)
    finally:owner.close()
    root=stage(h);assert not (root/'manifest.enc').exists() and h.target.read_bytes()==b'hello'
    if change=='unknown_entry':assert (root/'foreign-user-file').read_bytes()==b'preserve this unrelated fixture data'
