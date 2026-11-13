"""Bound original provider identities must survive a different canonical UID."""
import copy
import pytest
from test_startup_read_failure import native
from test_contact_source_failure_isolation import prepare, run, WireContact


def test_eds_existing_source_id_selects_original_record_not_create(native, monkeypatch):
    books, data = prepare(native, monkeypatch)
    data['kontakte'][0]['uid'] = 'canonical-person-uid'
    original_id = data['kontakte'][0]['syncQuellen']['eds:first']['id']
    second_card, = native.vcf_lesen(books['second'].contacts[0].text)['kontakte']
    second_card['uid'] = 'second-provider-original-uid'
    books['second'].contacts = [WireContact(native.vcard_text(second_card))]
    second_card, = native.vcf_lesen(books['second'].contacts[0].text)['kontakte']
    native._kontakt_eds_baseline(data['kontakte'][0], 'eds:second', second_card)
    data['kontakte'][0]['syncQuellen']['eds:second']['lokalInhaltSha256'] = native._sync_inhalt_hash(second_card, native.KONTAKT_FELDER)
    data['kontakte'][0]['syncQuellen']['eds:second']['abweichungBehalten'] = False
    writes, creates = [], []
    def update(book, text):
        assert native.vcf_lesen(text)['kontakte'][0]['uid'] == native.vcf_lesen(book.contacts[0].text)['kontakte'][0]['uid']
        writes.append(text)
        book.contacts = [WireContact(text)]
    def create(book, text):
        creates.append(text)
        book.contacts.append(WireContact(text))
    monkeypatch.setattr(native, 'eds_kontakt_aendern', update)
    monkeypatch.setattr(native, 'eds_kontakt_anlegen', create)
    result = run(native, data, 'first')
    assert not creates and len(writes) == 1, 'Known source UID was ignored and the same person created again'
    assert native.vcf_lesen(writes[0])['kontakte'][0]['uid'] == original_id
    contact, = result['kontakte']
    assert contact['uid'] == 'canonical-person-uid'
    assert contact['syncQuellen']['eds:first']['id'] == original_id
    second = run(native, result, 'second')
    assert len(writes) == 2 and second['kontakte'][0]['uid'] == 'canonical-person-uid', (second.get('bericht'), second.get('fehler'), second['kontakte'][0].get('kontaktProviderKonflikte'))
    assert second['kontakte'][0]['syncQuellen']['eds:second']['id'] == 'second-provider-original-uid'
    repeat = run(native, second, 'first')
    run(native, repeat, 'second')
    assert len(writes) == 2 and not creates


def test_dav_existing_source_href_selects_original_record_not_create(native, monkeypatch):
    books, data = prepare(native, monkeypatch)
    remote, = native.vcf_lesen(books['first'].contacts[0].text)['kontakte']
    local = data['kontakte'][0]
    source, href = 'generic-dav-addressbook:source-uid', 'https://fixture.invalid/book/original.vcf'
    native._dav_syncquelle_setzen(local, source, href, '"v1"', baseline=remote)
    local['uid'] = 'canonical-person-uid'
    result, creates, updates, deletes, count = native.sync_merge([copy.deepcopy(local)], {remote['uid']: remote}, [], 0,
        native.KONTAKT_FELDER, dav=(source, {}, {remote['uid']: {'href': href, 'etag': '"v1"'}}))
    assert not creates and len(updates) == 1 and not deletes and count['konflikte'] == 0, 'Known source href was ignored during UID lookup'
    contact, = result
    assert contact['uid'] == 'canonical-person-uid' and contact['syncQuellen'][source]['id'] == href


@pytest.mark.parametrize('refuse', (False, True))
def test_actual_dav_handler_preserves_two_original_uids_and_source_etags(native, monkeypatch, refuse):
    original = {'uid': 'provider-first', 'vorname': 'Alex', 'nachname': 'Fixture',
                'notiz': 'Original', 'geaendert': 1000}
    baseline, = native.vcf_lesen(native.vcard_text(original))['kontakte']
    sources = {name: 'generic-dav-addressbook:' + name for name in ('first', 'second')}
    class Dav:
        def __init__(self):
            self.refuse = refuse
            self.writes = []
            self.resources = {name: {'href': 'https://fixture.invalid/' + name + '/original.vcf',
                'etag': '"' + name + '-v1"', 'data': native.vcard_text(dict(baseline, uid='provider-' + name))}
                for name in sources}
        def collections(self, _kind):
            return [{'uid': source, 'name': name, 'href': 'https://fixture.invalid/' + name + '/'}
                    for name, source in sources.items()]
        def report(self, href, _kind): return [copy.deepcopy(self.resources[href.split('/')[-2]])]
        def put(self, href, text, etag=None, create=False):
            assert not create, 'Bound existing provider record was created again'
            name = href.split('/')[-2]; current = self.resources[name]
            assert etag == current['etag'] and href == current['href']
            assert native.vcf_lesen(text)['kontakte'][0]['uid'] == 'provider-' + name
            if self.refuse and name == 'first': raise RuntimeError('controlled stale original revision')
            self.writes.append((name, text))
            current.update(data=text, etag='"' + name + '-written"')
            return current['etag']
        def delete(self, *_): pytest.fail('Unexpected deletion')
    dav = Dav()
    monkeypatch.setattr(native, 'NextcloudDav', lambda _: dav)
    monkeypatch.setattr(native, 'configured_client', lambda _: object())
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: object())
    local = dict(copy.deepcopy(baseline), id='local', uid='canonical-person-uid', sync=True)
    for name, source in sources.items():
        resource = dav.resources[name]
        native._dav_syncquelle_setzen(local, source, resource['href'], resource['etag'])
    local.update(notiz='Canonical updated note', geaendert=2000)
    first_baseline = copy.deepcopy(local['syncQuellen'][sources['first']])
    data = {'kontakte': [local], 'syncMetadaten': {'nextcloud': {'adressbuecher': {
        source: {'initialisiert': True, 'letzterSync': 1000} for source in sources.values()}}}}
    def run_book(data, name):
        return native.Fenster._nextcloud_sync_ausfuehren(object(), {'daten': copy.deepcopy(data)}, [],
            sources[name], antworten=False, snapshot=False)
    first = run_book(data, 'first')
    assert first['ok'] is not refuse and len(first['kontakte']) == 1
    if refuse:
        assert first['kontakte'][0]['syncQuellen'][sources['first']] == first_baseline
    second = run_book(first, 'second')
    assert second['ok'] and second['kontakte'][0]['uid'] == 'canonical-person-uid'
    assert len(second['kontakte'][0]['syncQuellen']) == 2
    dav.refuse = False
    recovered = run_book(second, 'first')
    repeated = run_book(recovered, 'second')
    run_book(repeated, 'first')
    assert len(dav.writes) == 2 and {name for name, _ in dav.writes} == {'first', 'second'}


def test_duplicate_source_binding_refuses_planning_without_a_new_identity_guess(native, monkeypatch):
    books, data = prepare(native, monkeypatch)
    first = data['kontakte'][0]
    first['uid'] = 'canonical-one'
    second = dict(copy.deepcopy(first), id='second', uid='canonical-two', vorname='Different')
    remote, = native.vcf_lesen(books['first'].contacts[0].text)['kontakte']
    with pytest.raises(RuntimeError, match='ambiguous source binding'):
        native.sync_merge([first, second], {remote['uid']: remote}, [], 0,
            native.KONTAKT_FELDER, kontakt_quelle='eds:first')


@pytest.mark.parametrize('dav', (False, True))
def test_bound_original_uid_deletion_uses_source_id_and_keeps_canonical_tombstone(native, monkeypatch, dav):
    books, data = prepare(native, monkeypatch)
    remote, = native.vcf_lesen(books['first'].contacts[0].text)['kontakte']
    source = 'generic-dav-addressbook:original' if dav else 'eds:first'
    tombstone = dict(copy.deepcopy(data['kontakte'][0]), uid='canonical-person-uid', zeit=2000)
    meta = {remote['uid']: {'href': 'https://fixture.invalid/book/original.vcf', 'etag': '"v1"'}}
    if dav:
        native._dav_syncquelle_setzen(tombstone, source, meta[remote['uid']]['href'], '"v1"', baseline=remote)
    result, create, update, delete, count = native.sync_merge([], {remote['uid']: remote}, [tombstone], 0,
        native.KONTAKT_FELDER, **({'dav': (source, {}, meta)} if dav else {'kontakt_quelle': source}))
    assert not result and not create and not update and delete == [remote['uid']]
    assert count['remote_geloescht'] == 1
    retained = native.kontakt_grabsteine_nach_loeschung([tombstone], delete, set(), 3000,
        {remote['uid']: tombstone['uid']})
    assert len(retained) == 1 and retained[0]['uid'] == 'canonical-person-uid'


def test_canonical_uid_collision_does_not_reassign_a_known_original_source(native, monkeypatch):
    books, data = prepare(native, monkeypatch)
    remote, = native.vcf_lesen(books['first'].contacts[0].text)['kontakte']
    local = data['kontakte'][0]; local['uid'] = 'canonical-person-uid'
    unrelated = dict(copy.deepcopy(remote), uid='canonical-person-uid', vorname='Other')
    with pytest.raises(RuntimeError, match='ambiguous source binding'):
        native.sync_merge([local], {remote['uid']: remote, unrelated['uid']: unrelated}, [], 0,
            native.KONTAKT_FELDER, kontakt_quelle='eds:first')


@pytest.mark.parametrize('dav', (False, True))
def test_original_uid_binding_still_protects_a_concurrent_value_edit(native, monkeypatch, dav):
    books, data = prepare(native, monkeypatch)
    remote, = native.vcf_lesen(books['first'].contacts[0].text)['kontakte']
    local = data['kontakte'][0]
    source = 'generic-dav-addressbook:original' if dav else 'eds:first'
    href = 'https://fixture.invalid/book/original.vcf'
    if dav:
        native._dav_syncquelle_setzen(local, source, href, '"v1"', baseline=remote)
    local['uid'] = 'canonical-person-uid'
    remote.update(notiz='Concurrent source edit', geaendert=3000)
    result, create, update, delete, count = native.sync_merge([copy.deepcopy(local)], {remote['uid']: remote}, [], 0,
        native.KONTAKT_FELDER, **({'dav': (source, {}, {remote['uid']: {'href': href, 'etag': '"v2"'}})}
                                if dav else {'kontakt_quelle': source}))
    assert count['konflikte'] == 1 and not create and not update and not delete
    contact, = result
    assert contact['uid'] == 'canonical-person-uid'
    assert contact['kontaktProviderKonflikte'][source]['kontakt']['uid'] == remote['uid']
