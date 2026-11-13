import copy
import pytest
from test_startup_read_failure import native
from test_provider_label_convergence import card, Book, A


@pytest.mark.parametrize('field', ('nachname', 'firma', 'strasse', 'ort', 'anschriften'))
@pytest.mark.parametrize('read_only', (False, True))
def test_bound_source_sharp_s_is_not_a_conflict(native, field, read_only):
    local = card(native, 'telefone', 'local', 2000)
    remote, old = copy.deepcopy(local), copy.deepcopy(local)
    if field == 'anschriften':
        local[field] = [{'strasse': 'Großstraße 12', 'ort': 'Großstadt', 'region': 'Großregion'}]
        remote[field] = [{'strasse': 'Grossstrasse 12', 'ort': 'Grossstadt', 'region': 'Grossregion'}]
    else:
        local[field], remote[field], old[field] = 'Großstraße', 'Grossstrasse', 'Previous'
    remote['geaendert'] = 3000
    book = Book(A, remote, '"new"')
    native._dav_syncquelle_setzen(local, A, book.href, '"old"', baseline=old)
    before = copy.deepcopy(local)
    exact = native._sync_inhalt_hash(local, native.KONTAKT_FELDER)
    if read_only:
        result, create, change, delete, count = native.sync_merge(copy.deepcopy([local]), {remote['uid']: remote}, [], 0,
            native.KONTAKT_FELDER, dav=(A, {}, {remote['uid']: {'href': book.href, 'etag': book.etag}}), kontakt_nur_lesen=True)
        assert not create and not change and not delete and count['konflikte'] == 0
    else:
        result = book.sync(native, [local])
        result = book.sync(native, result)
    assert book.writes == 0 and result[0][field] == local[field]
    assert local == before and native._sync_inhalt_hash(local, native.KONTAKT_FELDER) == exact


def test_transliteration_is_not_identifier_or_unbound_person_equivalence(native):
    for field, a, b in (('email', 'groß@example.test', 'gross@example.test'), ('notiz', 'Maße', 'Masse')):
        assert native._kontakt_label_vergleich({field: a}, True, True) != native._kontakt_label_vergleich({field: b}, True, True)
    assert native._kontakt_label_vergleich({'nachname': 'Groß'}) != native._kontakt_label_vergleich({'nachname': 'Gross'})
