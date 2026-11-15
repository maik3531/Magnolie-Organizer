"""#640 actual acquisition/FS1 -> owned worker/UI dispatch, no real GUI or socket."""
import copy
import json
from pathlib import Path
import queue
import threading
from types import MethodType

import pytest

from test_contact_notes_consent import Harness, native
from magnolie_contact_notes_setup_run import NativeNotesSetupRun


@pytest.mark.parametrize('mode', ['configured', 'second-source', 'display-alias', 'source-cancel', 'contact-cancel',
    'bad-index', 'replay-ui', 'cancel-queued', 'revoke-queued', 'save-queued', 'cancel-contact', 'cancel-wait',
    'offline', 'dispatch-rejected', 'inline-dispatch', 'foreground-run', 'notice-error', 'bad-range', 'chooser-error',
    'post-error', 'cancel-before-run'])
def test_owned_native_worker_and_one_use_ui_callbacks_never_become_permission(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    acquisition = run = worker = None
    sessions = []
    events = queue.Queue()
    arrived = threading.Event()
    calls, notices, source_dialogs, contact_dialogs = [], [], [], []
    try:
        probe = h.probe
        probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, probe)
        probe._baum_sperre, probe._baumdienst, probe._baum = h.service._sperre, h.service, h.receiver
        peer = native.baum_partner(h.receiver, h.sender['kennung']); peer.update(vertraut=True, kontaktSync=True, protokoll='baum-fs1')
        h.receiver.setdefault('syncEpoch', 'synthetic-run-epoch')
        monkeypatch.setattr(native, 'kontakt_quellen_wlan_verfuegbar', lambda: mode != 'offline')
        def sender(url, body):
            assert threading.current_thread() is not threading.main_thread()
            assert not probe._daten_sperre._is_owned() and not probe._baum_sperre._is_owned()
            calls.append(url)
            if url.endswith('/sitzung'):
                answer, session = native.fs_antwort_bauen(h.sender,
                    {'kennung': h.receiver['kennung'], 'oeffentlich': h.receiver['oeffentlich']}, body)
                sessions.append(session)
                return answer
            session = sessions[-1]
            clear, _ = native.umschlag_oeffnen_fs(session, h.sender['kennung'], h.receiver['kennung'], body)
            assert clear['art'] == 'kontakt_original_aushandlung'
            h.send(dict(clear, antwort=True))
            if mode != 'cancel-wait':
                h.send(h.export)
                if mode == 'second-source':
                    h.send(dict(h.export, share_id='second-real-share', setup_id='55555555-5555-4555-8555-555555555555'))
            arrived.set()
            return native.fs_ack_bauen(session, body)
        acquisition = native.Fenster._notes_original_native_setup_acquire(probe, lambda _: h.sender['kennung'], sender)
        def post(callback):
            if mode == 'post-error': raise RuntimeError('synthetic unavailable main context')
            if mode == 'dispatch-rejected': return False
            if mode == 'inline-dispatch': callback(); return True
            events.put(callback)
            return True
        def source(views):
            assert threading.current_thread() is threading.main_thread()
            assert not probe._daten_sperre._is_owned() and not probe._baum_sperre._is_owned()
            source_dialogs.append(views)
            if mode == 'chooser-error': raise RuntimeError('synthetic native source chooser failure')
            if mode == 'display-alias': views[0].export['share_id'] = 'not-a-native-share'
            return None if mode == 'source-cancel' else True if mode == 'bad-index' else len(views) if mode == 'bad-range' else len(views) - 1 if mode == 'second-source' else 0
        def contact(view):
            assert threading.current_thread() is threading.main_thread()
            assert not probe._daten_sperre._is_owned() and not probe._baum_sperre._is_owned()
            contact_dialogs.append(view)
            if mode == 'cancel-contact': run.cancel()
            return None if mode == 'contact-cancel' else view.contacts[0]['id']
        def finished(phase):
            assert threading.current_thread() is threading.main_thread()
            notices.append(phase)
            if mode == 'notice-error': raise RuntimeError('synthetic closed status widget')
        before = Path(native.daten_datei()).read_bytes()
        run = NativeNotesSetupRun(acquisition, post, source, finished, choose_contact=contact)
        assert run.phase == 'created' and not calls and not h.store.has_desired_consent()
        if mode == 'cancel-before-run': run.cancel()
        if mode == 'foreground-run': run.run()
        else:
            worker = threading.Thread(target=run.run)
            worker.start()
            if mode == 'cancel-wait':
                assert arrived.wait(5)
                run.cancel()
            worker.join(10)
            assert not worker.is_alive(), 'Explicit setup worker did not join after cancellation/bounded work'
        if mode == 'cancel-queued': run.cancel()
        if mode == 'revoke-queued': h.store.revoke()
        if mode == 'save-queued':
            edit = copy.deepcopy(probe._aktuelle_daten); edit['during-ui-queue'] = 'preserve'
            assert h.save(monkeypatch, edit)['ok']
            before = Path(native.daten_datei()).read_bytes()
        # Native main-thread queue, not a fake provider/SaveACK. A callback may be
        # replayed by a stale UI dispatch but must not prompt/publish twice.
        first = None
        while not events.empty():
            callback = events.get_nowait()
            if first is None: first = callback
            assert callback() is False
            if mode == 'replay-ui': assert callback() is False
        assert run.done.is_set() and h.service._notes_setup_collector is None
        assert run._acquisition is None and run._candidates == (), 'Finished/late UI dispatch retained acquisition/candidate snapshots'
        granted = mode in ('configured', 'second-source', 'display-alias', 'replay-ui', 'notice-error')
        expected = 'configured' if granted else 'cancelled' if mode in ('source-cancel', 'contact-cancel', 'cancel-queued', 'cancel-contact', 'cancel-wait', 'cancel-before-run') else 'waiting-network' if mode == 'offline' else 'held'
        assert run.phase == expected and h.store.has_desired_consent() == granted
        if granted:
            active = h.store._active_record()[1]['choices']
            assert len(active) == 1 and active[0]['share_id'] == ('second-real-share' if mode == 'second-source' else h.export['share_id'])
            assert len(source_dialogs) == len(contact_dialogs) == 1
        else:
            assert not Path(h.root, '.key').exists()
        assert Path(native.daten_datei()).read_bytes() == before
        if mode in ('dispatch-rejected', 'inline-dispatch', 'post-error'): assert notices == []
        else: assert notices == [expected]
        if mode in ('cancel-queued', 'revoke-queued', 'save-queued', 'cancel-wait', 'offline', 'dispatch-rejected', 'inline-dispatch', 'foreground-run', 'post-error', 'cancel-before-run'):
            assert not source_dialogs and not contact_dialogs
        run.run()  # Worker replay is a no-op, never another source attempt.
        assert run.phase == expected
    finally:
        if run is not None: run.cancel()
        if acquisition is not None: acquisition.stop()
        if worker is not None: worker.join(5)
        for session in sessions: native.fs_sitzung_loeschen(session)
        h.service.anhalten()


def test_setup_run_is_shipped_without_registering_an_action_or_startup_factory():
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
            'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        assert 'magnolie_contact_notes_setup_run.py' in (root / name).read_text()
    json.loads((root / 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json').read_text())
    assert 'magnolie_contact_notes_setup_run' not in (root / 'bin/magnolie-organizer').read_text()


def test_serialized_or_fake_acquisition_cannot_construct_a_native_setup_run():
    for value in ({'phase': 'configured', 'permission': True}, True, object()):
        with pytest.raises(TypeError): NativeNotesSetupRun(value, lambda _: True, lambda _: 0, lambda _: None)
