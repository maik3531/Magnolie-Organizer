"""Explicit OFF-only photo target changes preserve all independent metadata."""
from dataclasses import fields

import pytest

from test_photo_preferences import preferences, configure
from test_file_authenticated_desktop import native
from magnolie_file_transfer import TransferError


def test_native_photo_target_requires_off_explicit_keep_existing_and_exact_snapshot(preferences,tmp_path):
    _,_,prefs,chooser,old,_=preferences
    active=configure(preferences)
    original=old/'keep-user-photo.jpg';original.write_bytes(b'keep original')
    target=tmp_path/'new-photo-target';target.mkdir(mode=0o700)
    selected=chooser.choose_custom(chooser.issue_action(),target)
    with pytest.raises(TransferError,match='authority_changed'):
        prefs.set_photo_destination(prefs.issue_action(),active,selected,historical_choice='keep_existing')
    assert prefs.read()==active
    off=prefs.configure(prefs.issue_action(),active,enabled=False,mode=active.mode)
    for invalid in (None,'move_existing',True):
        with pytest.raises(TransferError,match='historical_destination_choice_required'):
            prefs.set_photo_destination(prefs.issue_action(),off,selected,historical_choice=invalid)
    with pytest.raises(TransferError,match='cas_conflict'):
        prefs.set_photo_destination(prefs.issue_action(),active,selected,historical_choice='keep_existing')
    changed=prefs.set_photo_destination(prefs.issue_action(),off,selected,historical_choice='keep_existing')
    assert not changed.policy.enabled and changed.policy.destination==selected.destination
    assert changed.policy.destination_token==selected.destination_token!=off.policy.destination_token
    for field in fields(off.policy):
        if field.name not in ('revision','destination','destination_token','permission_revision'):
            assert getattr(changed.policy,field.name)==getattr(off.policy,field.name),field.name
    assert changed.policy.permission_revision==(off.policy.permission_revision or off.policy.revision)
    assert original.read_bytes()==b'keep original' and not list(target.iterdir())
    assert not prefs.local_grant(True).grants.receive_files and not prefs.local_grant(True).grants.send_files
    before=prefs._db.execute('SELECT payload FROM policy WHERE id=1').fetchone()[0]
    again=chooser.choose_custom(chooser.issue_action(),target)
    assert prefs.set_photo_destination(prefs.issue_action(),changed,again,historical_choice='keep_existing')==changed
    assert prefs._db.execute('SELECT payload FROM policy WHERE id=1').fetchone()[0]==before
