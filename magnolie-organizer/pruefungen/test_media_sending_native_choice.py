"""Bounded native dialog ticket, not a browser-confirmed or reusable grant."""
from pathlib import Path
import time
from dataclasses import replace
from hashlib import sha256
import pytest

from test_media_source_connection import source, native, receiving, mappings, composition
from magnolie_file_control import FileControlPacket
from magnolie_file_transfer import TransferError


def test_old_pairing_send_consent_is_not_displayed_or_reconfirmed_as_an_already_granted_current_right(source,native):
    with composition(source,native[0]) as h:
        # Valid protected migrated metadata: receiving association is current,
        # but its independently retained sending choice belongs to an old pair.
        prefs=h.preferences;before=prefs.read();revision=before.policy.revision+1
        policy=replace(before.policy,revision=revision,permission_revision=revision,permission_epoch='d'*64,
            sending=replace(before.policy.sending,pairing_epoch='f'*64))
        with prefs._operation():
            with prefs._locked():
                blob=prefs._protect(policy.wire(),'policy')
                head=prefs._protect(dict(revision=revision,policy_sha256=sha256(blob).hexdigest()),'owner')
                with prefs._db:
                    prefs._db.execute('UPDATE policy SET payload=? WHERE id=1',(blob,))
                    prefs._db.execute('UPDATE owner SET payload=? WHERE id=1',(head,))
                prefs._sync()
        current=prefs.read();assert current.associated and current.policy.sending.photos
        assert not h.connection._local().grants.send_files
        assert not h.connection.desktop_snapshot()['sending_consent']['photos']
        choice=h.connection.native_sending_consent('prepare',photos=True,videos=False,version=current.version)
        assert not choice['current_photos'] and not choice['current_videos']
        assert prefs.read()==current and h.target.read_bytes()==b'hello'


def test_native_sending_preflight_and_cancel_are_inert_and_commit_requires_the_exact_one_use_choice(source,native):
    with composition(source,native[0]) as h:
        before=h.preferences.read();frames=h.wire.received
        choice=h.connection.native_sending_consent('prepare',photos=False,videos=False,version=before.version)
        assert h.preferences.read()==before and h.wire.received==frames
        assert h.connection.native_sending_consent('cancel',selection=choice['selection'])==dict(canceled=True)
        with pytest.raises(TransferError):h.connection.native_sending_consent('commit',selection=choice['selection'])
        assert h.preferences.read()==before
        choice=h.connection.native_sending_consent('prepare',photos=False,videos=True,version=before.version)
        result=h.connection.native_sending_consent('commit',selection=choice['selection'])
        packet=FileControlPacket.parse(h.wire.receive()['body'])
        assert packet.grants.send_files and not packet.grants.receive_files
        assert result['photos'] is False and result['videos'] is True
        assert h.connection.desktop_snapshot()['sending_consent']==result
        after=h.preferences.read()
        with pytest.raises(TransferError):h.connection.native_sending_consent('commit',selection=choice['selection'])
        assert h.preferences.read()==after and h.target.read_bytes()==b'hello'


@pytest.mark.parametrize('fault',['version','book','expired','superseded','fields'])
def test_native_choice_rejects_stale_context_or_changed_type_selection_without_overwriting_policy(source,native,fault):
    with composition(source,native[0]) as h:
        choice=h.connection.native_sending_consent('prepare',photos=False,videos=False,version=h.preferences.read().version)
        if fault=='version':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=True)
        if fault=='book':
            book=Path(h.authority.binding.native_directory).parent/'daten.json'
            book.write_bytes(book.read_bytes()+b'\n')
        if fault=='expired':
            ticket=h.connection._media_sending_choice
            h.connection._media_sending_choice=(ticket[0],time.monotonic()-1,*ticket[2:])
        latest=None
        if fault=='superseded':latest=h.connection.native_sending_consent('prepare',photos=True,videos=True,version=h.preferences.read().version)
        before=h.preferences.read()
        with pytest.raises(TransferError):
            h.connection.native_sending_consent('commit',selection=choice['selection'],**(dict(photos=True) if fault=='fields' else {}))
        assert h.preferences.read()==before and h.target.read_bytes()==b'hello' and not h.source._prepared
        if latest is not None:assert h.connection._media_sending_choice[0]==latest['selection']
