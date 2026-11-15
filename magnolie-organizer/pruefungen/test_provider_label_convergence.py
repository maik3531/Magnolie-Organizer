"""Real Linux sync decisions and vCard roundtrips; no EDS/DAV service or user book."""
import copy
import json
import pytest
from test_startup_read_failure import native

A = 'generic-dav-addressbook:labels-a'
B = 'generic-dav-addressbook:labels-b'


def card(native, field, phase, time):
    kind = 'OTHER' if phase == 'base' else ('CELL' if phase == 'local' else 'HOME') if field == 'telefone' else ('HOME' if phase == 'local' else 'WORK')
    row = ({'strasse': 'Testweg 12', 'plz': '10115', 'ort': 'Berlin', 'region': 'Berlin', 'land': 'Germany'}
           if field == 'anschriften' else {'wert': '+49305550123' if field == 'telefone' else 'alex@example.test'})
    row.update(typen=[kind], label={'CELL': 'Mobile', 'HOME': 'Home', 'WORK': 'Work', 'OTHER': 'Original'}[kind])
    raw = {'uid': 'label-person', 'vorname': 'Alex', 'nachname': 'Fixture', 'geaendert': time, field: [row]}
    value, = native.vcf_lesen(native.vcard_text(raw))['kontakte']
    value.update(id='local', sync=True, geaendert=time)
    return value


def rows(native, value, field):
    getter = {'telefone': native._telefon_liste, 'emailEintraege': native._email_eintraege, 'anschriften': native._anschrift_liste}[field]
    return sorted(json.dumps({key: item for key, item in row.items()
                              if not (key == 'vcardParameter' and item == [])},
                             sort_keys=True, ensure_ascii=False) for row in getter(value))


class Book:
    def __init__(self, source, value, etag):
        self.source, self.value, self.etag = source, copy.deepcopy(value), etag
        self.href = '/labels/' + source.rsplit('-', 1)[-1] + '.vcf'
        self.writes = 0

    def sync(self, native, local):
        uid = self.value['uid']
        result, create, change, delete, count = native.sync_merge(copy.deepcopy(local), {uid: copy.deepcopy(self.value)}, [], 0,
            native.KONTAKT_FELDER, dav=(self.source, {}, {uid: {'href': self.href, 'etag': self.etag}}))
        assert not create and not delete and len(result) == 1
        assert count['konflikte'] == 0, 'Label-only source differences became a value conflict'
        for value in change:
            # Same native writer/parser as the live caller; acknowledge only this
            # source after its controlled write, never the other book's baseline.
            parsed, = native.vcf_lesen(native.vcard_text(value))['kontakte']
            self.value = parsed
            self.value['geaendert'] = 9000  # own provider transport/write time
            self.writes += 1
            self.etag = '"write-' + str(self.writes) + '"'
            native._dav_syncquelle_setzen(value, self.source, self.href, self.etag)
        native._dav_syncquelle_setzen(result[0], self.source, self.href, self.etag)
        return result


@pytest.mark.parametrize('field', ('telefone', 'emailEintraege', 'anschriften'))
@pytest.mark.parametrize('remote_newer', (False, True))
def test_two_sources_converge_without_own_write_clock_rollback(native, field, remote_newer):
    original = card(native, field, 'base', 1000)
    local = card(native, field, 'local', 2000)
    first = Book(A, original, '"a-v1"')
    second = Book(B, card(native, field, 'remote', 3000 if remote_newer else 1000), '"b-v2"')
    native._dav_syncquelle_setzen(local, A, first.href, first.etag, baseline=original)
    native._dav_syncquelle_setzen(local, B, second.href, '"b-v1"', baseline=original)
    contacts = first.sync(native, [local])
    contacts = second.sync(native, contacts)
    contacts = first.sync(native, contacts)
    contacts = second.sync(native, contacts)
    expected = card(native, field, 'remote' if remote_newer else 'local', 3000 if remote_newer else 2000)
    for value in (contacts[0], first.value, second.value):
        assert rows(native, value, field) == rows(native, expected, field), 'An older source kept its obsolete role/label'
    assert contacts[0]['geaendert'] == expected['geaendert'], 'Own provider write time replaced content provenance'
    assert set(contacts[0]['syncQuellen']) == {A, B}
    assert native._kontakt_label_vergleich(contacts[0]) == native._kontakt_label_vergleich(first.value)
    before = first.writes + second.writes
    contacts = first.sync(native, contacts)
    second.sync(native, contacts)
    assert first.writes + second.writes == before, 'Unchanged converged sources rewrote the same metadata'


@pytest.mark.parametrize('field', ('telefone', 'emailEintraege', 'anschriften'))
def test_eds_label_only_plan_preserves_source_and_no_false_conflict(native, field):
    original = card(native, field, 'base', 1000)
    local = card(native, field, 'local', 2000)
    remote = card(native, field, 'remote', 1000)
    source = 'eds:label-fixture'
    native._kontakt_eds_baseline(local, source, original)
    result, create, change, delete, count = native.sync_merge([local], {remote['uid']: remote}, [], 0,
        native.KONTAKT_FELDER, kontakt_quelle=source)
    assert count['konflikte'] == 0 and not create and not delete
    assert len(change) == 1, 'Older EDS labels were not queued for convergence'
    assert rows(native, change[0], field) == rows(native, card(native, field, 'local', 2000), field)
    assert result[0]['syncQuellen'][source]['inhaltSha256'] == native._sync_inhalt_hash(remote, native.KONTAKT_FELDER), 'Planning falsely acknowledged a source write'


def test_real_changed_value_still_requires_source_review(native):
    original = card(native, 'telefone', 'base', 1000)
    local = card(native, 'telefone', 'local', 2000)
    remote = card(native, 'telefone', 'remote', 3000)
    remote['telefone'][0]['wert'] = '+49305550999'
    remote['telefon'] = '+49305550999'; remote['mobil'] = ''
    native._dav_syncquelle_setzen(local, B, '/labels/b.vcf', '"v1"', baseline=original)
    result, create, change, delete, count = native.sync_merge([local], {remote['uid']: remote}, [], 0,
        native.KONTAKT_FELDER, dav=(B, {}, {remote['uid']: {'href': '/labels/b.vcf', 'etag': '"v2"'}}))
    assert count['konflikte'] == 1 and not create and not change and not delete
    assert result[0]['kontaktProviderKonflikte'][B]['mapping']['etag'] == '"v2"'


@pytest.mark.parametrize('field', ('telefone', 'emailEintraege', 'anschriften'))
def test_home_private_alias_does_not_queue_repeated_writes(native, field):
    local = card(native, field, 'local', 2000)
    local[field][0].update(label='Home', typen=['HOME'])
    if field == 'telefone':
        native._telefone_setzen(local, local[field])
    remote = copy.deepcopy(local)
    remote[field][0].update(label='Privat', rolle='private')
    native._dav_syncquelle_setzen(local, B, '/labels/b.vcf', '"v1"')
    for _ in range(2):
        result, create, change, delete, count = native.sync_merge([local], {remote['uid']: remote}, [], 0,
            native.KONTAKT_FELDER, dav=(B, {}, {remote['uid']: {'href': '/labels/b.vcf', 'etag': '"v2"'}}))
        assert count['konflikte'] == 0 and not create and not change and not delete
        local = result[0]


@pytest.mark.parametrize('local_time,remote_time', ((0, 3000), (2000, 0), (2000, 10**18)))
def test_unknown_or_future_times_retain_canonical_labels_and_pending_source(native, local_time, remote_time):
    local = card(native, 'telefone', 'local', local_time)
    remote = card(native, 'telefone', 'remote', remote_time if remote_time < 10**15 else 3000)
    remote['geaendert'] = remote_time
    native._dav_syncquelle_setzen(local, B, '/labels/b.vcf', '"v1"')
    baseline = copy.deepcopy(local['syncQuellen'][B])
    result, _, change, _, count = native.sync_merge([local], {remote['uid']: remote}, [], 0,
        native.KONTAKT_FELDER, dav=(B, {}, {remote['uid']: {'href': '/labels/b.vcf', 'etag': '"v2"'}}))
    assert count['konflikte'] == 0 and len(change) == 1
    assert result[0]['geaendert'] == local_time and result[0]['syncQuellen'][B] == baseline
    assert rows(native, result[0], 'telefone') == rows(native, card(native, 'telefone', 'local', local_time), 'telefone')


def test_readonly_source_never_receives_label_write(native):
    local = card(native, 'anschriften', 'local', 2000)
    remote = card(native, 'anschriften', 'remote', 1000)
    native._kontakt_eds_baseline(local, 'eds:readonly', remote)
    result, create, change, delete, count = native.sync_merge([local], {remote['uid']: remote}, [], 0,
        native.KONTAKT_FELDER, kontakt_quelle='eds:readonly', kontakt_nur_lesen=True)
    assert not create and not change and not delete and count['konflikte'] == 0
    assert rows(native, result[0], 'anschriften') == rows(native, local, 'anschriften')


def test_label_projection_preserves_values_groups_photo_and_unknown_metadata(native):
    local = card(native, 'telefone', 'local', 2000)
    exact_hash = native._sync_inhalt_hash(local, native.KONTAKT_FELDER)
    for mutate in (
        lambda c: c['telefone'][0].update(wert='+49309999999'),
        lambda c: c['telefone'][0].update(providerOpaque='unknown'),
        lambda c: c.update(foto='data:image/png;base64,fixture'),
        lambda c: c.update(vcardRoundtrip=c.get('vcardRoundtrip', []) + ['CATEGORIES:Team']),
        lambda c: c.update(vcardParameter={'TEL': ['X-UNKNOWN=fixture']}),
    ):
        changed = copy.deepcopy(local); mutate(changed)
        assert native._kontakt_label_vergleich(local, True) != native._kontakt_label_vergleich(changed, True)
    assert native._sync_inhalt_hash(local, native.KONTAKT_FELDER) == exact_hash
