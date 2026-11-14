"""Actual authenticated receive -> deferred native worker -> actual book writer.

All primary files/peers/keys are synthetic. No production registration or sockets.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import threading
from types import MethodType

import pytest

from test_contact_notes_consent import Harness, native
from test_contact_notes_fs_origin import frame
from magnolie_contact_notes_controller import NativeNotesController
from magnolie_contact_notes_return import NativeNotesAckIntents, NativeNotesExportChoice


class Runtime:
    def __init__(self, h, *, per_peer=8):
        self._receive_scope = threading.local()
        self.h, self.receiving = h, False
        def key():
            assert not self.receiving, 'Journal IO under tree receive gate'
            return b'J' * 32
        self.outcomes = NativeNotesAckIntents(Path(h.root).parent / 'outcomes', key)
        self.controller = NativeNotesController(h.store, self.outcomes, self.book_gate, per_peer=per_peer)
        for name in ('_capture', '_capture_primary', '_native_data', '_read'):
            original = getattr(h.store, name)
            def outside_receive(*args, _callback=original):
                assert not self.receiving, 'Book/consent IO under tree receive gate'
                return _callback(*args)
            setattr(h.store, name, outside_receive)
        self.protocol = self.controller.begin_peer((h.sender['kennung'], h.sender['oeffentlich']),
            (h.receiver['kennung'], h.receiver['oeffentlich']))
        h.service.bei_sicherer_nachricht = self.receive

    @property
    def receiving(self):
        return getattr(self._receive_scope, 'active', False)

    @receiving.setter
    def receiving(self, value):
        self._receive_scope.active = value

    @contextmanager
    def book_gate(self):
        assert not self.receiving, 'Worker waited for book gate inside receive'
        with self.h.probe._daten_sperre:
            yield

    def receive(self, *args):
        self.receiving = True
        try:
            return self.controller.receive(*args)
        finally:
            self.receiving = False

    def negotiate(self):
        self.h.send(dict(self.protocol.request(), antwort=True))
        assert self.controller.process_one().kind == 'negotiated'

    def start(self):
        self.negotiate()
        self.h.send(self.h.export)
        action = self.controller.process_one()
        assert action.kind == 'request'
        return action

    @staticmethod
    def result(request, receipt='22222222-2222-4222-8222-222222222222'):
        import hashlib
        from magnolie_contact_notes_return import _frame_bytes
        return {'art': 'kontakt_original_ergebnis', 'fassung': 1,
            **{name: request[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')},
            'request_sha256': hashlib.sha256(_frame_bytes(request)).hexdigest(),
            'receipt_id': receipt, 'native_revision': 2, 'next_basis': 'd' * 64}

    def rejected(self, body):
        channel, envelope, _ = frame(self.h.native, self.h.service, self.h.sender, self.h.receiver, body, b'Z' * 16)
        try:
            assert self.h.service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] == 403
        finally:
            self.h.native.fs_sitzung_loeschen(channel)


@pytest.mark.parametrize('mode', ['complete', 'prepared', 'duplicate', 'conflict', 'stop-before-worker',
    'stop-before-save', 'stop-after-save', 'expired-frame', 'unknown-result', 'early-save-boolean'])
def test_registry_joins_actual_receive_worker_save_and_terminal_history_without_receive_io(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure(); runtime = Runtime(h); c = runtime.controller
        start = runtime.start(); request = start.intent.request(); result = runtime.result(request)
        if mode == 'unknown-result':
            runtime.rejected(dict(result, request_id='33333333-3333-4333-8333-333333333333'))
            assert c.counts()['queued'] == 0 and c.counts()['owners'] == 1
            return
        if mode == 'early-save-boolean':
            with pytest.raises(PermissionError): c.after_saved(request['request_id'], runtime.protocol)
            with pytest.raises(PermissionError): c.after_saved(request['request_id'], {'confirmed': True})
            assert not (tmp_path / 'outcomes').exists()
            return
        h.send(result)
        before = Path(native.daten_datei()).read_bytes()
        assert not (tmp_path / 'outcomes').exists(), 'Receive issued a saved ACK'
        if mode == 'stop-before-worker':
            c.stop()
            with pytest.raises(PermissionError): c.process_one()
            with pytest.raises(PermissionError): start.intent.request()
            assert Path(native.daten_datei()).read_bytes() == before
            return
        if mode == 'expired-frame':
            h.service.anhalten()
            assert c.process_one().kind == 'held'
            assert Path(native.daten_datei()).read_bytes() == before
            return
        save = c.process_one()
        assert save.kind == 'save' and save.request_id == request['request_id']
        if mode in ('duplicate', 'conflict'):
            h.send(result if mode == 'duplicate' else dict(result, receipt_id='33333333-3333-4333-8333-333333333333'))
            assert c.process_one().kind == ('duplicate' if mode == 'duplicate' else 'held')
        if mode == 'stop-before-save': c.stop()
        response = h.save(monkeypatch, invocation=save.intent)
        if mode in ('conflict', 'stop-before-save'):
            assert not response['ok']
            assert Path(native.daten_datei()).read_bytes() == before
            assert not (tmp_path / 'outcomes').exists()
            return
        assert response['ok']
        ack = c.after_saved(request['request_id'], runtime.protocol)
        assert ack.kind == 'ack' and ack.intent.body()['request_id'] == request['request_id']
        journal, = (tmp_path / 'outcomes').glob('*.bin')
        if mode == 'stop-after-save':
            c.stop()
            with pytest.raises(PermissionError): ack.intent.body()
            assert runtime.outcomes.load_held(journal.stem)['request'] == request
            return
        status = dict(result, art='kontakt_original_abschlussstatus',
            phase='prepared' if mode == 'prepared' else 'settled', desktop_sha256=ack.intent.body()['desktop_sha256'])
        before_book, before_journal = Path(native.daten_datei()).read_bytes(), journal.read_bytes()
        h.send(status)
        assert Path(native.daten_datei()).read_bytes() == before_book and journal.read_bytes() == before_journal
        action = c.process_one()
        assert action.kind == ('ack' if mode == 'prepared' else 'settled')
        assert c.counts()['owners'] == (1 if mode == 'prepared' else 0)
        assert Path(native.daten_datei()).read_bytes() == before_book
        if mode == 'prepared':
            assert journal.read_bytes() == before_journal
            assert action.intent.body() == ack.intent.body()
        else:
            assert 'native_terminal_sha256' in runtime.outcomes.load_held(journal.stem)
            with pytest.raises(PermissionError): start.intent.request()
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['export-before-offer', 'bounded-and-isolated', 'restart-history', 'physical-hold', 'book-lock-held'])
def test_registry_waiting_budgets_restart_and_receive_do_not_replace_owned_attempts(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure(); runtime = Runtime(h, per_peer=2); c = runtime.controller
        if mode == 'export-before-offer':
            h.send(h.export)
            h.send(dict(runtime.protocol.request(), antwort=True))
            assert c.process_one().kind == 'waiting'
            assert c.process_one().kind == 'negotiated'
            assert c.process_one().kind == 'request'
            assert h.choices == 1
            return
        if mode == 'bounded-and-isolated':
            h.send(dict(runtime.protocol.request(), antwort=True))
            h.send(dict(runtime.protocol.request(), antwort=True))
            assert c.counts()['queued'] == 1, 'Duplicate echo consumed another slot'
            h.send(dict(h.export, share_id='unaccepted-private-source'))
            runtime.rejected(dict(h.export, share_id='another-unaccepted-source'))
            assert c.counts()['queued'] == 2
            assert c.process_one().kind == 'negotiated'
            assert c.process_one().kind == 'held'
            h.send(h.export)
            assert c.process_one().kind == 'request'
            assert c.counts()['owners'] == 1 and c.counts()['held'] == 1
            return
        start = runtime.start(); request = start.intent.request()
        if mode == 'physical-hold':
            h.send(h.export)
            assert c.process_one().kind == 'held'
            assert start.intent.request() == request and c.counts()['owners'] == 1
            return
        result = runtime.result(request)
        if mode == 'book-lock-held':
            done, errors = threading.Event(), []
            def receive():
                try: h.send(result)
                except BaseException as error: errors.append(error)
                finally: done.set()
            with h.probe._daten_sperre:
                thread = threading.Thread(target=receive, daemon=True); thread.start()
                assert done.wait(5), 'Actual receive waited on held native book lock'
            thread.join(5)
            assert not thread.is_alive() and not errors
            assert c.process_one().kind == 'save'
            return
        h.send(result); save = c.process_one()
        assert h.save(monkeypatch, invocation=save.intent)['ok']
        ack = c.after_saved(request['request_id'], runtime.protocol).intent.body()
        journal, = (tmp_path / 'outcomes').glob('*.bin')
        c.stop(); h.restart()
        runtime = Runtime(h); runtime.negotiate(); c = runtime.controller
        query = c.register_history(journal.stem, runtime.protocol)
        assert query.kind == 'query' and 'ziel' not in query.intent.request()
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        h.send(result)
        assert c.process_one().intent.body() == ack
        ready, = c.ready_acks()
        assert ready.intent.body() == ack
        h.send(dict(result, art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256=ack['desktop_sha256']))
        assert c.process_one().kind == 'settled' and c.counts()['owners'] == 0
        assert h.probe._kontakt_quellen_buchaufnahme() is None and h.choices == 1
    finally:
        h.service.anhalten()


def test_controller_module_is_declared_in_existing_source_manifests():
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
                 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        assert 'magnolie_contact_notes_controller.py' in (root / name).read_text()


def test_held_source_does_not_block_another_privately_selected_source_in_the_same_book(native, monkeypatch, tmp_path):
    h = Harness(native, tmp_path)
    try:
        proposed = copy.deepcopy(h.probe._aktuelle_daten)
        second = copy.deepcopy(proposed['kontakte'][0]); second.update(id='other-native-id', uid='other-canonical-uid')
        proposed['kontakte'].append(second)
        assert h.save(monkeypatch, proposed)['ok']
        h.configure()
        export2 = dict(h.export, share_id='other-private-share', setup_id='55555555-5555-4555-8555-555555555555')
        body, origin, transport = h.observed(export2)
        choice2 = NativeNotesExportChoice(body, origin, transport, h.probe._kontakt_quellen_buchaufnahme(),
            h.probe._kontakt_quellen_buchaufnahme, lambda _: 'other-native-id')
        with h.probe._daten_sperre: h.store.configure([h.choice, choice2])
        runtime = Runtime(h); runtime.negotiate(); c = runtime.controller
        first = c.register_pending(h.choice.pending(), runtime.protocol)
        second = c.register_pending(choice2.pending(), runtime.protocol)
        first_result = runtime.result(first.intent.request())
        h.send(first_result); first_save = c.process_one()
        h.send(dict(first_result, receipt_id='33333333-3333-4333-8333-333333333333'))
        assert c.process_one().kind == 'held'
        h.send(runtime.result(second.intent.request()))
        second_save = c.process_one()
        assert second_save.kind == 'save' and h.save(monkeypatch, invocation=second_save.intent)['ok']
        ack = c.finish_save(second_save)
        assert ack.intent.body()['share_id'] == 'other-private-share'
        with pytest.raises(PermissionError): first_save.intent.write(first_save.intent.text, lambda _: pytest.fail('Held source wrote'))
        assert c.counts()['owners'] == 2 and c.counts()['held'] == 1
        assert len(c.ready_acks()) == 1
        assert 'notesOriginalBasis' not in h.probe._aktuelle_daten['kontakte'][0]
        assert h.probe._aktuelle_daten['kontakte'][1]['notesOriginalBasis']['share_id'] == 'other-private-share'
    finally:
        h.service.anhalten()


def test_actual_window_native_factory_receive_worker_queue_and_real_save_callback_are_joined(native, monkeypatch, tmp_path):
    h = Harness(native, tmp_path)
    try:
        h.configure(); runtime = Runtime(h)
        probe = h.probe
        probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, probe)
        controller = native.Fenster._notes_original_native_controller(probe, runtime.outcomes)
        # Explicit native-only injection; startup/default config does not do this.
        probe._notes_original_controller = controller
        runtime.controller = controller
        runtime.protocol = controller.begin_peer((h.sender['kennung'], h.sender['oeffentlich']),
            (h.receiver['kennung'], h.receiver['oeffentlich']))
        native_receive = MethodType(native.Fenster._baum_notes_native_empfangen, probe)
        def receive(*args):
            runtime.receiving = True
            try: return native_receive(*args)
            finally: runtime.receiving = False
        h.service.bei_sicherer_nachricht = receive
        h.send(dict(runtime.protocol.request(), antwort=True))
        assert native.Fenster._notes_original_native_arbeit(probe).kind == 'negotiated'
        h.send(h.export)
        pending = native.Fenster._notes_original_native_arbeit(probe)
        original_request = pending.intent.request()
        h.send(runtime.result(original_request))
        save = native.Fenster._notes_original_native_arbeit(probe)
        assert save.kind == 'save' and probe._speicher_auftraege.qsize() == 1
        monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
        probe._speicher_auftraege.put(None)
        thread = threading.Thread(target=native.Fenster._speicher_lauf, args=(probe,), daemon=True)
        thread.start(); thread.join(15)
        assert not thread.is_alive()
        assert save.intent.result['confirmed'] and probe._notes_original_work_error is None
        ack, = controller.ready_acks()
        assert ack.intent.body()['request_id'] == save.request_id
        from magnolie_contact_notes_controller import NativeNotesWork
        with pytest.raises(PermissionError): controller.finish_save(NativeNotesWork('save', save.intent, 'other-request-id'))
        controller.stop()
        runtime.rejected(runtime.result(original_request))
    finally:
        h.service.anhalten()


def test_actual_window_default_tree_callback_never_creates_or_infers_a_controller(native, monkeypatch, tmp_path):
    h = Harness(native, tmp_path)
    try:
        probe = h.probe
        probe._baum_notes_native_empfangen = MethodType(native.Fenster._baum_notes_native_empfangen, probe)
        probe._baum_zustand = lambda: h.receiver
        probe._baum_sichern = lambda *_: None
        probe._baum_empfangen = lambda *_: pytest.fail('Native draft entered generic renderer inbox')
        probe._baum_stand_melden = lambda *_: None
        probe._baum_alte_statuspost_entfernen = lambda: None
        probe._baum_sperre = threading.RLock()
        captured = []
        def no_socket_start(service): captured.append(service); return False
        monkeypatch.setattr(native.BaumDienst, 'starten', no_socket_start)
        assert native.Fenster._baum_dienst_pflegen_serialisiert(probe) is False
        h.service.anhalten(); h.service, = captured
        assert not hasattr(probe, '_notes_original_controller')
        assert native.Fenster._notes_original_native_arbeit(probe) is None
        body = {'art': 'kontakt_original_aushandlung', 'fassung': 1, 'challenge': '11111111-1111-4111-8111-111111111111',
            'antwort': True, 'profil': 'notes-original-return-draft1'}
        channel, envelope, _ = frame(native, h.service, h.sender, h.receiver, body)
        try: assert h.service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] == 403
        finally: native.fs_sitzung_loeschen(channel)
        assert not Path(h.root).exists() and not (tmp_path / 'outcomes').exists()
    finally:
        h.service.anhalten()


def test_receive_can_stage_while_native_book_worker_is_waiting_for_tree_context(native, tmp_path):
    h = Harness(native, tmp_path)
    release = threading.Event()
    threads = []
    try:
        h.configure(); runtime = Runtime(h); c = runtime.controller
        work = runtime.start(); result = runtime.result(work.intent.request())
        h.send(result)
        entered = threading.Event()
        original = work.intent._mapping
        def mapping():
            entered.set()
            assert release.wait(5), 'Receive could not finish while worker held native book gate'
            original()
        work.intent._mapping = mapping
        outputs, errors = [], []
        def worker():
            try: outputs.append(c.process_one())
            except BaseException as error: errors.append(error)
        thread = threading.Thread(target=worker, daemon=True); threads.append(thread); thread.start()
        assert entered.wait(5)
        def receive():
            try: h.send(result)
            except BaseException as error: errors.append(error)
            finally: release.set()
        thread = threading.Thread(target=receive, daemon=True); threads.append(thread); thread.start()
        for thread in threads: thread.join(10)
        assert not any(thread.is_alive() for thread in threads) and not errors
        assert len(outputs) == 1 and outputs[0].kind == 'save'
        assert c.process_one().kind == 'duplicate'
    finally:
        release.set()
        for thread in threads: thread.join(5)
        h.service.anhalten()


def test_registry_native_types_and_peer_limits_create_no_default_consent_or_journal(native, tmp_path):
    h = Harness(native, tmp_path)
    try:
        outcomes = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: pytest.fail('Constructor read a journal key'))
        with pytest.raises(TypeError): NativeNotesController({}, outcomes, lambda: h.probe._daten_sperre)
        with pytest.raises(TypeError): NativeNotesController(h.store, outcomes, lambda: h.probe._daten_sperre, max_peers=True)
        c = NativeNotesController(h.store, outcomes, lambda: h.probe._daten_sperre, max_peers=1)
        c.begin_peer(('one', 'pinned-key'), ('own', 'own-key'))
        with pytest.raises(PermissionError): c.begin_peer(('two', 'another-key'), ('own', 'own-key'))
        assert c.receive({}, {'native': True}, {'native': True}, 'copied') is False
        assert c.counts() == {'peers': 1, 'owners': 0, 'queued': 0, 'held': 0}
        assert not Path(h.root).exists() and not (tmp_path / 'outcomes').exists()
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('store', ['consent', 'outcome'])
def test_private_cipher_failure_holds_work_without_rewriting_unknown_records_or_blocking_the_worker(native, monkeypatch, tmp_path, store):
    h = Harness(native, tmp_path)
    try:
        h.configure(); runtime = Runtime(h); c = runtime.controller
        if store == 'consent':
            runtime.negotiate(); h.send(h.export)
            path = Path(h.root, 'choices.aes')
        else:
            request = runtime.start().intent.request()
            result = runtime.result(request); h.send(result)
            save = c.process_one()
            assert h.save(monkeypatch, invocation=save.intent)['ok']
            ack = c.finish_save(save).intent.body()
            path, = (tmp_path / 'outcomes').glob('*.bin')
            h.send(dict(result, art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256=ack['desktop_sha256']))
        original = path.read_bytes()
        corrupt = original[:-1] + bytes([original[-1] ^ 1])
        path.write_bytes(corrupt)  # Own synthetic ciphertext only.
        before = Path(native.daten_datei()).read_bytes()
        assert c.process_one().kind == 'held'
        assert c.process_one() is None and c.ready_acks() == ()
        assert path.read_bytes() == corrupt and Path(native.daten_datei()).read_bytes() == before
        if store == 'consent':
            path.write_bytes(original)  # Explicit repair in isolated fixture, not automatic adoption.
            h.send(h.export)
            assert c.process_one().kind == 'request' and h.choices == 1
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['exact-noop', 'missing-defaults-noop', 'semantic-collision-change'])
def test_noop_export_creates_no_request_hold_but_semantic_hash_collision_is_not_exact_authority(native, monkeypatch, tmp_path, mode):
    from magnolie_contact_notes_return import notes_content_hash
    h = Harness(native, tmp_path)
    try:
        saved = copy.deepcopy(h.probe._aktuelle_daten)
        saved['kontakte'][0].update(vorname='Ada', nachname='Test', anzeigename='Ada Test', vcardRoundtrip=[])
        assert h.save(monkeypatch, saved)['ok']
        h.configure()
        exact_change = mode == 'semantic-collision-change'
        patch = h.choice.pending().request()['ziel']
        before = dict(h.before, **patch)
        if exact_change: before['anzeigename'] = ''
        if mode == 'missing-defaults-noop':
            for name in patch:
                if before.get(name) in ('', []): before.pop(name, None)
        assert notes_content_hash(before) == notes_content_hash(dict(before, **patch))
        export = dict(h.export, before_basis='c' * 64, native_revision=2, kontakt=before,
            content_sha256=notes_content_hash(before))
        runtime = Runtime(h); runtime.negotiate()
        book = Path(native.daten_datei()).read_bytes()
        h.send(export)
        if not exact_change:
            queued = next(iter(runtime.controller._frames.values()))
            with h.probe._daten_sperre:
                unchanged_choice = h.store.restore(json.loads(queued.text), queued.origin, queued.transport)
                with pytest.raises(ValueError): runtime.controller._requests.seal(unchanged_choice.pending())
                with pytest.raises(ValueError): runtime.controller.register_pending(unchanged_choice.pending(), runtime.protocol)
        action = runtime.controller.process_one()
        assert action.kind == ('request' if exact_change else 'unchanged')
        assert runtime.controller.counts()['owners'] == int(exact_change)
        assert Path(runtime.controller._requests.root).exists() is exact_change
        assert Path(native.daten_datei()).read_bytes() == book
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['verified', 'physical-only', 'missing-outcome-status'])
def test_controller_restarts_unconfirmed_owner_by_readonly_query_then_real_save_not_provider_replay(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure(); old = Runtime(h); work = old.start(); request = work.intent.request()
        proof = work.intent._request_intention
        if mode == 'physical-only':
            Path(old.controller._requests.root, 'r-' + proof.key + '.bin').unlink()
        old.controller.stop(); h.restart()
        runtime = Runtime(h); runtime.negotiate(); c = runtime.controller
        query = c.register_unconfirmed(proof.key, runtime.protocol, physical=proof.physical)
        assert query.kind == 'query' and 'ziel' not in query.intent.request()
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        result = runtime.result(request)
        if mode == 'missing-outcome-status':
            result.update(art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256='e' * 64)
        h.send(result)
        action = c.process_one()
        if mode == 'missing-outcome-status':
            assert action.kind == 'held' and c.ready_acks() == ()
            assert h.probe._kontakt_quellen_buchaufnahme() is None and not (tmp_path / 'outcomes').exists()
            return
        assert action.kind == 'needs-real-save' and c.counts()['queued'] == 1
        assert h.probe._kontakt_quellen_buchaufnahme() is None and c._requests._fresh == {}
        assert h.save(monkeypatch)['ok']
        save = c.process_one()
        assert save.kind == 'save' and save.request_id == request['request_id']
        assert h.save(monkeypatch, invocation=save.intent)['ok']
        ack = c.finish_save(save)
        assert ack.intent.body()['request_id'] == request['request_id']
        assert c._requests._fresh == {} and h.probe._kontakt_quellen_buchaufnahme().sequence == 2
        with pytest.raises(PermissionError): c._owners[(runtime.protocol.require_current(), request['request_id'])].pending._for_negotiated_protocol(runtime.protocol)
        status = dict(result, art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256=ack.intent.body()['desktop_sha256'])
        h.send(status)
        assert c.process_one().kind == 'settled' and c.counts()['owners'] == 0
        assert c._requests.load_held(proof.key)['state'] == 'request_settled'
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['complete', 'stop-before-bootstrap', 'changed-model', 'fake-complete'])
def test_actual_window_automatically_queues_a_real_known_primary_bootstrap_before_resumed_metadata(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure(); old = Runtime(h); request_work = old.start(); request = request_work.intent.request()
        proof = request_work.intent._request_intention
        old.controller.stop(); h.restart()
        runtime = Runtime(h); probe = h.probe
        probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, probe)
        c = native.Fenster._notes_original_native_controller(probe, runtime.outcomes)
        probe._notes_original_controller = c; runtime.controller = c
        runtime.protocol = c.begin_peer((h.sender['kennung'], h.sender['oeffentlich']), (h.receiver['kennung'], h.receiver['oeffentlich']))
        h.service.bei_sicherer_nachricht = runtime.receive
        runtime.negotiate(); c.register_unconfirmed(proof.key, runtime.protocol, physical=proof.physical)
        h.send(runtime.result(request))
        bootstrap = native.Fenster._notes_original_native_arbeit(probe)
        assert bootstrap.kind == 'needs-real-save' and probe._speicher_auftraege.qsize() == 1
        assert probe._kontakt_quellen_buchaufnahme() is None and c.ready_acks() == ()
        if mode == 'fake-complete':
            bootstrap.intent.complete({'ok': True, 'committed': True, 'repairPending': False, 'standSha256': bootstrap.intent._hash})
            assert bootstrap.intent.result == {'confirmed': False}
            with pytest.raises(PermissionError): c.finish_bootstrap(bootstrap)
            assert probe._kontakt_quellen_buchaufnahme() is None and not (tmp_path / 'outcomes').exists()
            return
        before = Path(native.daten_datei()).read_bytes()
        if mode == 'stop-before-bootstrap': c.stop()
        if mode == 'changed-model': probe._aktuelle_daten['kontakte'][0]['notiz'] = 'Unsaved newer user edit'
        monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
        def writer():
            probe._speicher_auftraege.put(None)
            thread = threading.Thread(target=native.Fenster._speicher_lauf, args=(probe,), daemon=True)
            thread.start(); thread.join(15)
            assert not thread.is_alive()
        writer()
        if mode != 'complete':
            assert bootstrap.intent.result == {'confirmed': False}
            assert Path(native.daten_datei()).read_bytes() == before
            assert probe._kontakt_quellen_buchaufnahme() is None and not (tmp_path / 'outcomes').exists()
            return
        assert bootstrap.intent.result == {'confirmed': True}
        assert probe._kontakt_quellen_buchaufnahme().sequence == 1
        assert c.ready_acks() == () and not (tmp_path / 'outcomes').exists()
        metadata = native.Fenster._notes_original_native_arbeit(probe)
        assert metadata.kind == 'save' and probe._speicher_auftraege.qsize() == 1
        writer()
        ack, = c.ready_acks()
        assert ack.intent.body()['request_id'] == request['request_id']
        assert probe._kontakt_quellen_buchaufnahme().sequence == 2 and c._requests._fresh == {}
        assert probe._notes_original_work_error is None
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['request', 'unchanged', 'wrong-setup', 'revoked', 'bad-export-hash', 'unknown-primary', 'stop-before-write'])
def test_regular_fresh_export_after_restart_bootstraps_only_its_existing_private_native_selection(native, monkeypatch, tmp_path, mode):
    from magnolie_contact_notes_return import notes_content_hash
    h = Harness(native, tmp_path)
    try:
        h.configure()
        export = copy.deepcopy(h.export)
        if mode == 'unchanged':
            export['kontakt'] = dict(h.before, **h.choice.pending().request()['ziel'])
            export['content_sha256'] = notes_content_hash(export['kontakt'])
        if mode == 'wrong-setup': export['setup_id'] = '55555555-5555-4555-8555-555555555555'
        if mode == 'bad-export-hash': export['content_sha256'] = '0' * 64
        h.restart()
        if mode == 'revoked': h.store.revoke()
        if mode == 'unknown-primary':
            changed = copy.deepcopy(h.probe._aktuelle_daten); changed['kontakte'][0]['notiz'] = 'Unknown replaced primary'
            native.speichere_text(h.probe._vielleicht_verschluesseln(json.dumps(changed)))
        runtime = Runtime(h); runtime.negotiate(); c = runtime.controller
        h.probe._notes_original_controller = c
        before = Path(native.daten_datei()).read_bytes()
        h.send(export)
        work = native.Fenster._notes_original_native_arbeit(h.probe)
        if mode in ('wrong-setup', 'revoked', 'bad-export-hash', 'unknown-primary'):
            assert work.kind == 'held' and h.probe._speicher_auftraege.empty()
            assert h.probe._kontakt_quellen_buchaufnahme() is None
            assert Path(native.daten_datei()).read_bytes() == before
            assert c._export_bootstraps == {}
            return
        assert work.kind == 'needs-real-save' and not work.request_id
        assert c.counts()['owners'] == 0 and not Path(c._requests.root).exists()
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        assert native.Fenster._notes_original_native_arbeit(h.probe).kind == 'waiting'
        assert h.probe._speicher_auftraege.qsize() == 1, 'Deferred export queued the same bootstrap twice'
        if mode == 'stop-before-write': c.stop()
        monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
        h.probe._speicher_auftraege.put(None)
        thread = threading.Thread(target=native.Fenster._speicher_lauf, args=(h.probe,), daemon=True)
        thread.start(); thread.join(15)
        assert not thread.is_alive()
        if mode == 'stop-before-write':
            assert work.intent.result == {'confirmed': False}
            assert Path(native.daten_datei()).read_bytes() == before and h.probe._kontakt_quellen_buchaufnahme() is None
            return
        assert work.intent.result == {'confirmed': True}
        assert h.probe._kontakt_quellen_buchaufnahme().sequence == 1 and c.ready_acks() == ()
        planned = native.Fenster._notes_original_native_arbeit(h.probe)
        assert planned.kind == ('unchanged' if mode == 'unchanged' else 'request')
        assert c.counts()['owners'] == (0 if mode == 'unchanged' else 1)
        assert c._export_bootstraps == {} and h.choices == 1
        assert not (tmp_path / 'outcomes').exists()
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('failure', [False, True])
def test_multiple_approved_exports_share_one_actual_book_bootstrap_not_full_book_copies_per_source(native, monkeypatch, tmp_path, failure):
    h = Harness(native, tmp_path)
    try:
        data = copy.deepcopy(h.probe._aktuelle_daten)
        second = copy.deepcopy(data['kontakte'][0]); second.update(id='second-id', uid='second-uid')
        data['kontakte'].append(second)
        assert h.save(monkeypatch, data)['ok']
        h.configure()
        export2 = dict(h.export, share_id='second-private-share', setup_id='55555555-5555-4555-8555-555555555555')
        body, origin, transport = h.observed(export2)
        choice2 = NativeNotesExportChoice(body, origin, transport, h.probe._kontakt_quellen_buchaufnahme(),
            h.probe._kontakt_quellen_buchaufnahme, lambda _: 'second-id')
        h.store.configure([h.choice, choice2])
        h.restart(); runtime = Runtime(h); runtime.negotiate(); c = runtime.controller
        h.probe._notes_original_controller = c
        h.send(h.export); h.send(export2)
        bootstrap = native.Fenster._notes_original_native_arbeit(h.probe)
        assert bootstrap.kind == 'needs-real-save'
        assert native.Fenster._notes_original_native_arbeit(h.probe).kind == 'waiting'
        assert h.probe._speicher_auftraege.qsize() == 1 and len(c._export_bootstraps) == 1
        monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
        if failure:
            def reject():
                raise PermissionError('synthetic_one_source_bootstrap_failure')
            monkeypatch.setattr(bootstrap.intent, '_require_before', reject)
        h.probe._speicher_auftraege.put(None)
        thread = threading.Thread(target=native.Fenster._speicher_lauf, args=(h.probe,), daemon=True)
        thread.start(); thread.join(15)
        assert not thread.is_alive()
        if failure:
            assert bootstrap.intent.result == {'confirmed': False}
            assert c._export_bootstraps == {} and c.counts()['queued'] == 1
            assert h.probe._kontakt_quellen_buchaufnahme() is None
            other = native.Fenster._notes_original_native_arbeit(h.probe)
            assert other.kind == 'needs-real-save'
            h.probe._speicher_auftraege.put(None)
            thread = threading.Thread(target=native.Fenster._speicher_lauf, args=(h.probe,), daemon=True)
            thread.start(); thread.join(15)
            assert not thread.is_alive() and other.intent.result == {'confirmed': True}
        assert h.probe._kontakt_quellen_buchaufnahme().sequence == 1
        assert native.Fenster._notes_original_native_arbeit(h.probe).kind == 'request'
        if not failure:
            assert native.Fenster._notes_original_native_arbeit(h.probe).kind == 'request'
        assert c.counts()['owners'] == (1 if failure else 2) and c._export_bootstraps == {}
    finally:
        h.service.anhalten()
