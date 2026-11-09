"""Original source catalog pinning through real protected preferences, no UI."""
from dataclasses import replace
from contextlib import closing
from pathlib import Path

import pytest

from test_file_authenticated_desktop import native
from test_photo_preferences import preferences, configure
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_source_roots import ProtectedMediaCollectionRoots
from magnolie_photo_preferences import ProtectedPhotoPreferences, PhotoPreferences
from magnolie_file_transfer import TransferError


def selected_catalog(f):
    _,authority,_,_,target,_=f
    catalog=ProtectedMediaCollectionRoots(authority)
    try:
        with NativeCollectionRoot(target,lambda:True) as root:
            catalog.add(catalog.issue_action(),catalog.read(),root,'images')
        return catalog
    except BaseException:catalog.close();raise


def test_absent_factory_and_binding_do_not_bootstrap_preferences_or_grants(preferences):
    service,_,prefs,_,_,_=preferences
    parent=Path(service.store.root);before=set(parent.iterdir())
    with pytest.raises(TransferError):prefs.open_collection_roots()
    # The fixture's unrelated live PhoneStore may checkpoint/remove WAL/SHM.
    # Passive source lookup must create nothing and must not create prefs.
    assert set(parent.iterdir())<=before and not (parent/prefs._name).exists()
    catalog=selected_catalog(preferences)
    try:
        with pytest.raises(TransferError):prefs.bind_collection_roots(prefs.issue_action(),prefs.read(),catalog)
        assert prefs.read().policy is None and not (parent/prefs._name).exists()
    finally:catalog.close()


@pytest.mark.parametrize('receiving',[False,True])
def test_explicit_pin_preserves_old_policy_and_exact_grant_then_survives_settings(preferences,receiving):
    _,authority,prefs,_,_,_=preferences
    if receiving:before=configure(preferences)
    else:before=prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=True,videos=False)
    assert 'collection_roots' not in before.policy.wire()
    assert PhotoPreferences.parse(before.policy.wire())==before.policy
    grant=prefs.native_local_state(True,source_handlers_ready=True)[0].grants
    catalog=selected_catalog(preferences)
    try:
        saved=prefs.bind_collection_roots(prefs.issue_action(),before,catalog);proof=catalog.witness()
        assert saved.policy==replace(before.policy,revision=before.policy.revision+1,collection_roots=proof,
            permission_revision=before.policy.permission_revision if before.policy.permission_revision is not None else before.policy.revision)
        assert prefs.native_local_state(True,source_handlers_ready=True)[0].grants==grant
        assert prefs.bind_collection_roots(prefs.issue_action(),saved,catalog)==saved
        with closing(prefs.open_collection_roots()) as reopened:assert reopened.witness()==proof
        if receiving:changed=prefs.set_mode(prefs.issue_action(),saved,'automatic')
        else:
            # The existing receive-mode UI guard stays intact on a SEND-only policy.
            with pytest.raises(TransferError):prefs.set_mode(prefs.issue_action(),saved,'automatic')
            changed=saved
        assert changed.policy.collection_roots==proof and changed.policy.sending==saved.policy.sending
        changed=prefs.configure_sending(prefs.issue_action(),changed,photos=False,videos=False)
        assert changed.policy.collection_roots==proof
        changed=prefs.configure(prefs.issue_action(),changed,enabled=receiving,mode='manual')
        assert changed.policy.collection_roots==proof
        prefs.close();fresh=ProtectedPhotoPreferences(authority)
        try:
            assert fresh.read()==changed
            with closing(fresh.open_collection_roots()) as reopened:assert reopened.witness()==proof
        finally:fresh.close()
    finally:catalog.close()


def test_fresh_preferences_require_original_catalog_after_combined_loss_and_refuse_replacement(preferences):
    service,authority,prefs,_,target,_=preferences
    before=prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=True,videos=False)
    catalog=selected_catalog(preferences)
    saved=prefs.bind_collection_roots(prefs.issue_action(),before,catalog)
    catalog.close();prefs.close();parent=Path(service.store.root)
    for name in [catalog._name,catalog._anchor]:
        p=parent/name;p.rename(p.with_name(name+'.retained'))
    fresh=ProtectedPhotoPreferences(authority)
    replacement=ProtectedMediaCollectionRoots(authority)
    try:
        assert fresh.read()==saved
        with pytest.raises(TransferError):fresh.open_collection_roots()
        # Even a separately explicit new selection must not replace the old pin.
        with NativeCollectionRoot(target,lambda:True) as root:
            replacement.add(replacement.issue_action(),replacement.read(),root,'images')
        with pytest.raises(TransferError):fresh.bind_collection_roots(fresh.issue_action(),saved,replacement)
        with pytest.raises(TransferError):fresh.open_collection_roots()
        assert fresh.read()==saved
    finally:replacement.close();fresh.close()


def test_binding_rejects_stale_replayed_and_expired_actions(preferences):
    _,_,prefs,_,_,clock=preferences
    before=prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=True,videos=False)
    catalog=selected_catalog(preferences)
    try:
        action=prefs.issue_action();saved=prefs.bind_collection_roots(action,before,catalog)
        for candidate,expected in [(action,saved),(prefs.issue_action(),before),({'yes':True},saved)]:
            with pytest.raises(TransferError):prefs.bind_collection_roots(candidate,expected,catalog)
        expired=prefs.issue_action();clock[0]+=60001
        with pytest.raises(TransferError):prefs.bind_collection_roots(expired,saved,catalog)
        assert prefs.read()==saved
    finally:catalog.close()
