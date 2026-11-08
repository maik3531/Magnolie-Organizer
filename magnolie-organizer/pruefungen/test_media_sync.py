"""Notes-compatible media intent only: no native grant, storage or worker."""
from pathlib import Path
import copy
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
import magnolie_media_sync as media
import magnolie_shared_sync as personal
from test_file_authenticated_desktop import native,bind

A='11111111-1111-4111-8111-111111111111'
B='22222222-2222-4222-8222-222222222222'
C='33333333-3333-4333-8333-333333333333'


@pytest.fixture
def native_media(native):
    service,peer,_=native
    peer['capabilities']['items']['device_status']['versions'].append(23);service.store.save_peers()
    channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    try:yield service,peer,authority,media.NativeMediaSettingsStore(authority)
    finally:authority.close()


def test_media_defaults_are_complete_separate_and_fail_closed_without_changing_personal_defaults():
    before=personal.create(A);body=media.create(A)
    assert media.effective(body)==dict(enabled=False,photos_enabled=True,videos_enabled=False,collection_mode='phone_inventory',
        auto_mode='manual',skip_deletions=False,direction='phone_to_pc')
    assert media.DISCOVERY_VERSION==23 and media.VERSION==1
    assert not media.requested_for(body,'images') and not media.requested_for(body,'video')
    assert personal.create(A)==before and before['format']==9
    with pytest.raises(ValueError):media.validate(before)
    with pytest.raises(ValueError):personal.validate(body)


def test_activation_and_photo_selection_keep_independent_clocks_and_never_mutate_input():
    before=media.create(A);frozen=copy.deepcopy(before)
    enabled=media.change(before,A,B,'enabled',True)
    photos=media.change(enabled,A,B,'photos_enabled',False)
    assert before==frozen
    assert photos['settings']['enabled'][A]==dict(counter=1,value=True)
    assert photos['settings']['photos_enabled'][A]==dict(counter=1,value=False)
    assert enabled['settings']['photos_enabled'][A]['counter']==0
    assert not media.requested_for(photos,'images')
    assert media.requested_for(enabled,'images') and not media.requested_for(enabled,'images',to_phone=True)
    two_way=media.change(enabled,A,B,'direction','two_way')
    assert media.requested_for(two_way,'images',to_phone=True) and not media.requested_for(two_way,'video',to_phone=True)


@pytest.mark.parametrize('scope',['phone_inventory','entire_collection','import_only'])
@pytest.mark.parametrize('direction',['phone_to_pc','two_way','pc_to_phone'])
def test_scope_and_direction_have_separate_clocks_and_import_cannot_export(scope,direction):
    body=media.change(media.create(A),A,B,'enabled',True)
    body=media.change(body,A,B,'collection_mode',scope)
    body=media.change(body,A,B,'direction',direction)
    frozen=copy.deepcopy(body)
    active_direction='phone_to_pc' if scope=='import_only' else direction
    assert media.effective(body)['direction']==active_direction
    assert media.requested_for(body,'images') is (active_direction in ('phone_to_pc','two_way'))
    assert media.requested_for(body,'images',to_phone=True) is (active_direction in ('pc_to_phone','two_way'))
    assert body==frozen
    assert body['settings']['direction'][A]==dict(counter=1,value=direction)
    assert body['settings']['collection_mode'][A]==dict(counter=1,value=scope)
    restored=media.change(body,A,B,'collection_mode','phone_inventory')
    assert media.effective(restored)['direction']==direction
    assert restored['settings']['direction']==body['settings']['direction']


def test_concurrent_manual_off_phone_scope_and_skip_deletions_win_conservatively():
    left=media.create(A);right=media.create(B)
    for field,value in [('enabled',True),('photos_enabled',True),('videos_enabled',True),('auto_mode','wifi'),
            ('direction','two_way'),('collection_mode','entire_collection')]:left=media.change(left,A,B,field,value)
    for field,value in [('enabled',False),('photos_enabled',False),('videos_enabled',False),('auto_mode','manual'),
            ('direction','phone_to_pc'),('collection_mode','phone_inventory'),('skip_deletions',True)]:right=media.change(right,B,A,field,value)
    a=media.merge(left,right,A,B);b=media.merge(right,left,B,A)
    assert media.effective(a)==media.effective(b)==dict(enabled=False,photos_enabled=False,videos_enabled=False,auto_mode='manual',
        direction='phone_to_pc',collection_mode='phone_inventory',skip_deletions=True)
    assert media.merge(a,b,A,B)==a


def test_zero_clock_manual_tie_is_media_specific_and_does_not_reuse_personal_wifi_migration():
    left=media.create(A);right=media.create(B);right['settings']['auto_mode'][B]['value']='wifi'
    assert media.effective(media.merge(left,right,A,B))['auto_mode']=='manual'


def test_partial_peer_registers_preserve_other_fields_and_foreign_actor_or_equivocation_hold():
    body=media.create(A);partial=dict(format=1,settings={'enabled':{B:dict(counter=1,value=True)}})
    merged=media.merge(body,partial,A,B)
    assert merged['settings']['photos_enabled']==body['settings']['photos_enabled']
    assert media.effective(merged)['enabled']
    partial['settings']['enabled'][B]['value']=False
    with pytest.raises(ValueError):media.merge(merged,partial,A,B)
    partial['settings']['enabled']={C:dict(counter=1,value=True)}
    with pytest.raises(ValueError):media.merge(body,partial,A,B)


def test_local_echo_cannot_forge_newer_local_choice_and_explicit_current_choice_merge_preserves_zero_bootstrap():
    body=media.create(A);forged=copy.deepcopy(body);forged['settings']['enabled'][A]=dict(counter=1,value=True)
    with pytest.raises(ValueError):media.merge(body,forged,A,B)
    stale=copy.deepcopy(body);stale['settings']['photos_enabled'][A]['value']=False
    with pytest.raises(ValueError):media.merge(body,stale,A,B)
    selected=media.merge(body,stale,A,B,current_choices=True)
    assert media.effective(selected)['photos_enabled'] and selected['settings']['photos_enabled'][A]['counter']==1


@pytest.mark.parametrize('field,value',[('enabled',1),('auto_mode','connection'),('collection_mode','phone_import'),
    ('direction','bidirectional'),('read_granted',True)])
def test_media_modes_and_flags_reject_legacy_ambiguity_or_authority_fields(field,value):
    with pytest.raises(ValueError):media.change(media.create(A),A,B,field,value)


def test_incomplete_start_or_boolean_format_cannot_request_a_media_run():
    body=media.create(A);partial=dict(format=1,settings={'enabled':body['settings']['enabled']})
    media.validate(partial)
    with pytest.raises(ValueError):media.validate_start(dict(format=1,settings=partial))
    with pytest.raises(ValueError):media.requested_for(partial,'images')
    with pytest.raises(ValueError):media.validate(dict(body,format=True))
    assert media.validate_start(dict(format=1,settings=body))['settings']==body
    assert media.validate_result(dict(format=1,request_id=A,state='held'))['state']=='held'
    with pytest.raises(ValueError):media.validate_result(dict(format=1,request_id=A,state='success'))


def test_native_media_passive_read_is_absent_and_does_not_initialize_or_change_personal_settings(native_media):
    import sqlite3
    service,peer,_,store=native_media
    before=service.store.shared_settings(peer['device_id'],peer['static_public'])
    with sqlite3.connect(service.store.database_path) as db:rows=db.execute('SELECT key,value FROM meta ORDER BY key').fetchall()
    assert store.read() is None
    with sqlite3.connect(service.store.database_path) as db:assert db.execute('SELECT key,value FROM meta ORDER BY key').fetchall()==rows
    assert service.store.shared_settings(peer['device_id'],peer['static_public'])==before


def test_native_media_changes_are_encrypted_peer_scoped_and_do_not_grant_source_or_receiving(native_media):
    from magnolie_photo_preferences import ProtectedPhotoPreferences
    service,peer,authority,store=native_media
    saved=store.change('enabled',True);saved=store.change('direction','two_way')
    assert media.requested_for(saved,'images',to_phone=True)
    reopened=media.NativeMediaSettingsStore(authority);assert reopened.read()==saved
    prefs=ProtectedPhotoPreferences(authority)
    try:
        assert prefs.read().policy is None
        assert not prefs.local_grant(True).grants.send_files and not prefs.local_grant(True).grants.receive_files
    finally:prefs.close()
    incoming=media.create(peer['device_id'])
    incoming=media.change(incoming,peer['device_id'],authority.identity.receiver_id,'videos_enabled',True)
    merged=store.merge(incoming)
    assert media.effective(merged)['enabled'] and media.effective(merged)['videos_enabled']
    import sqlite3
    with sqlite3.connect(service.store.database_path) as db:cipher=db.execute('SELECT value FROM meta WHERE key=?',(store._key,)).fetchone()[0]
    assert b'phone_inventory' not in cipher and b'photos_enabled' not in cipher
    assert service.store.shared_settings(peer['device_id'],peer['static_public']) is None


def test_native_media_corrupt_cipher_is_preserved_and_never_reset_to_defaults(native_media):
    import sqlite3
    service,_,_,store=native_media
    store.change('enabled',True)
    with sqlite3.connect(service.store.database_path) as db:
        cipher=db.execute('SELECT value FROM meta WHERE key=?',(store._key,)).fetchone()[0]
        broken=cipher[:-1]+bytes([cipher[-1]^1]);db.execute('UPDATE meta SET value=? WHERE key=?',(broken,store._key))
    from cryptography.exceptions import InvalidTag
    with pytest.raises((InvalidTag,ValueError)):store.read()
    with pytest.raises((InvalidTag,ValueError)):store.change('enabled',False)
    with sqlite3.connect(service.store.database_path) as db:assert db.execute('SELECT value FROM meta WHERE key=?',(store._key,)).fetchone()[0]==broken


def test_native_media_rejects_foreign_registers_revoked_owner_and_unsupported_peer(native_media):
    service,peer,authority,store=native_media
    with pytest.raises(ValueError):store.merge(media.create(C))
    assert store.read() is None
    peer['capabilities']['items']['device_status']['versions'].remove(23);service.store.save_peers()
    with pytest.raises(PermissionError):store.change('enabled',True)
    peer['capabilities']['items']['device_status']['versions'].append(23);service.store.save_peers()
    authority.revoke()
    with pytest.raises(PermissionError):store.read()


def test_native_media_missing_original_database_never_creates_replacement(native_media):
    import sqlite3
    service,_,_,store=native_media
    path=Path(service.store.database_path);held=path.with_name(path.name+'.fixture-held');path.rename(held)
    try:
        with pytest.raises(sqlite3.OperationalError):store.read()
        assert not path.exists()
    finally:held.rename(path)
