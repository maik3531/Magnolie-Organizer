"""Whole Linux provider handlers: one failed book must not disable a contact."""
import copy
import pytest
from test_startup_read_failure import native


class WireContact:
    def __init__(self, text): self.text = text
    def inline_local_photos(self): pass
    def to_string(self, _format): return self.text


class Book:
    def __init__(self, text):
        self.contacts = [WireContact(text)]
        self.fail = False
        self.readback_fail = False
        self.writes = 0
    def get_contacts_sync(self, _query, _cancel):
        if self.readback_fail and self.writes:
            raise RuntimeError('controlled source readback failure')
        return True, self.contacts


class Probe:
    def antwort(self, callback, payload): self.payload = payload
    def _journal_snapshot(self, _reason): pass


def prepare(native, monkeypatch):
    monkeypatch.setattr(native, 'eds_laden', lambda: True)
    monkeypatch.setattr(native, 'eds_registry', lambda: object())
    monkeypatch.setitem(native._EDS, 'buch_ok', True)
    monkeypatch.setitem(native._EDS, 'EBookContacts', type('Contacts', (), {
        'VCardFormat': type('Format', (), {'VCARD_30': 1})}))
    original = {'uid': 'source-failure-fixture', 'vorname': 'Alex', 'nachname': 'Fixture',
                'notiz': 'Original', 'geaendert': 1000,
                'telefone': [{'wert': '+49305550123', 'typen': ['HOME'], 'label': 'Home'}]}
    text = native.vcard_text(original)
    baseline, = native.vcf_lesen(text)['kontakte']
    local = dict(copy.deepcopy(baseline), id='local', sync=True)
    books = {name: Book(text) for name in ('first', 'second')}
    for name in books:
        native._kontakt_eds_baseline(local, 'eds:' + name, baseline)
    local.update(notiz='Canonical updated note', geaendert=2000)
    monkeypatch.setattr(native, 'eds_buch_client', lambda _registry, name: books[name])
    def write(book, value):
        if book.fail:
            raise RuntimeError('controlled source write failure')
        book.writes += 1
        book.contacts = [WireContact(value)]
    monkeypatch.setattr(native, 'eds_kontakt_aendern', write)
    monkeypatch.setattr(native, 'eds_kontakt_anlegen', lambda *_: pytest.fail('Unexpected creation'))
    monkeypatch.setattr(native, 'eds_kontakt_loeschen', lambda *_: pytest.fail('Unexpected deletion'))
    data = {'termine': [], 'aufgaben': [], 'kontakte': [local], 'jahrestage': [],
            'geloescht': {'termine': [], 'kontakte': []}, 'letzterSync': 100,
            'syncMetadaten': {'eds': {'adressbuecher': {name: {
                'initialisiert': True, 'letzterSync': 100, 'remoteAnzahl': 1,
                'snapshotHash': 'a' * 64} for name in books}}}}
    return books, data


def run(native, data, name):
    probe = Probe()
    native.Fenster._sync_ausfuehren(probe, {'wahl': {'adressbuchUid': name}, 'daten': copy.deepcopy(data)})
    return probe.payload


@pytest.mark.parametrize('failure', ('write', 'readback', 'create', 'label-write', 'label-readback'))
def test_failed_eds_source_remains_pending_without_disabling_other_book(native, monkeypatch, failure):
    books, data = prepare(native, monkeypatch)
    if failure == 'create':
        books['first'].contacts = []
        data['kontakte'][0]['syncQuellen'].pop('eds:first')
        monkeypatch.setattr(native, 'eds_kontakt_anlegen', native.eds_kontakt_aendern)
    if failure.startswith('label-'):
        data['kontakte'][0]['notiz'] = 'Original'
        native._telefone_setzen(data['kontakte'][0], [{'wert': '+49305550123', 'typen': ['CELL'], 'label': 'Mobile'}])
    before = copy.deepcopy(data['kontakte'][0]['syncQuellen'])
    books['first'].fail = failure in ('write', 'create', 'label-write')
    books['first'].readback_fail = failure in ('readback', 'label-readback')
    failed = run(native, data, 'first')
    assert failed['ok'] is False
    contact, = failed['kontakte']
    assert contact['sync'] is True, 'One source failure disabled global contact synchronization'
    assert contact['syncQuellen'] == before, 'Failed/uncertain source write was acknowledged'
    second = run(native, failed, 'second')
    assert second['ok'] and books['second'].writes == 1
    assert second['kontakte'][0]['syncQuellen'].get('eds:first') == before.get('eds:first')
    written, = native.vcf_lesen(books['second'].contacts[0].text)['kontakte']
    assert written['notiz'] == ('Original' if failure.startswith('label-') else 'Canonical updated note')
    books['first'].fail = False; books['first'].readback_fail = False
    recovered = run(native, second, 'first')
    assert recovered['ok'] and recovered['kontakte'][0]['sync'] is True
    writes = sum(book.writes for book in books.values())
    repeated = run(native, recovered, 'first')
    run(native, repeated, 'second')
    assert sum(book.writes for book in books.values()) == writes


@pytest.mark.parametrize('create', (False, True))
def test_failed_dav_source_keeps_original_baseline_and_other_book_writable(native, monkeypatch, create):
    original = {'uid': 'source-failure-fixture', 'vorname': 'Alex', 'nachname': 'Fixture',
                'notiz': 'Original', 'geaendert': 1000}
    baseline, = native.vcf_lesen(native.vcard_text(original))['kontakte']
    local = dict(copy.deepcopy(baseline), id='local', sync=True)
    class Dav:
        def __init__(self):
            self.fail = True
            self.puts = []
            self.resources = {name: [] if create else [{
                'href': 'https://fixture.invalid/' + name + '/person.vcf',
                'etag': '"v1"', 'data': native.vcard_text(baseline)}] for name in ('first', 'second')}
        def collections(self, kind):
            assert kind == 'addressbook'
            return [{'uid': 'nextcloud-addressbook:' + name, 'name': name,
                     'href': 'https://fixture.invalid/' + name + '/'} for name in self.resources]
        def report(self, href, kind):
            assert kind == 'addressbook'
            return copy.deepcopy(self.resources[href.split('/')[-2]])
        def put(self, href, text, etag=None, create=False):
            name = href.split('/')[-2]
            if name == 'first' and self.fail:
                raise RuntimeError('controlled DAV source refusal')
            current = self.resources[name]
            assert (create and not current) or (not create and current[0]['etag'] == etag)
            result = '"write-' + str(len(self.puts) + 1) + '"'
            self.resources[name] = [{'href': href, 'etag': result, 'data': text}]
            self.puts.append((name, text, etag, create))
            return result
        def delete(self, *_): pytest.fail('Unexpected deletion')
    dav = Dav()
    monkeypatch.setattr(native, 'NextcloudDav', lambda _: dav)
    monkeypatch.setattr(native, 'configured_client', lambda _: object())
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: object())
    if not create:
        for name in dav.resources:
            native._dav_syncquelle_setzen(local, 'nextcloud-addressbook:' + name,
                dav.resources[name][0]['href'], '"v1"')
    local.update(notiz='Canonical updated note', geaendert=2000)
    data = {'kontakte': [local], 'syncMetadaten': {'nextcloud': {'adressbuecher': {
        'nextcloud-addressbook:' + name: {'initialisiert': True, 'letzterSync': 1000} for name in dav.resources}}}}
    def run_book(data, name):
        probe = Probe()
        return native.Fenster._nextcloud_sync_ausfuehren(probe, {'daten': copy.deepcopy(data)}, [],
            'nextcloud-addressbook:' + name, antworten=False)
    before = copy.deepcopy(local.get('syncQuellen') or {})
    failed = run_book(data, 'first')
    assert failed['ok'] is False and not dav.puts
    assert failed['kontakte'][0]['sync'] is True, 'DAV failure disabled global contact synchronization'
    assert (failed['kontakte'][0].get('syncQuellen') or {}) == before
    second = run_book(failed, 'second')
    assert second['ok'] and len(dav.puts) == 1 and dav.puts[0][0] == 'second'
    assert second['kontakte'][0]['syncQuellen'].get('nextcloud-addressbook:first') == before.get('nextcloud-addressbook:first')
    dav.fail = False
    recovered = run_book(second, 'first')
    assert recovered['ok'] and len(dav.puts) == 2
    again = run_book(recovered, 'first')
    run_book(again, 'second')
    assert len(dav.puts) == 2
