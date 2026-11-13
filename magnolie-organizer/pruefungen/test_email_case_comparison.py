"""#603: keep spelling, ignore e-mail case, retain meaningful characters."""
import copy
import pytest
from test_startup_read_failure import native
from test_provider_label_convergence import card, Book, A, B


@pytest.mark.parametrize('field', ('email', 'emails', 'emailEintraege'))
def test_two_sources_email_case(native, field):
    def email(address):
        value = card(native, 'emailEintraege', 'local', 2000)
        for name in ('email', 'emails', 'emailEintraege'):
            value.pop(name, None)
        value[field] = address if field == 'email' else [address] if field == 'emails' else [{'wert': address, 'typen': ['HOME']}]
        return value
    local = email('Alex.Example+tag@Example.Test')
    lower = email('alex.example+tag@example.test')
    old = email('old@example.test')
    first, second = Book(A, lower, '"a-v2"'), Book(B, lower, '"b-v2"')
    native._dav_syncquelle_setzen(local, A, first.href, '"a-v1"', baseline=old)
    native._dav_syncquelle_setzen(local, B, second.href, '"b-v1"', baseline=old)
    before = copy.deepcopy(local)
    exact = native._sync_inhalt_hash(local, native.KONTAKT_FELDER)
    result = first.sync(native, [local])
    result = second.sync(native, result)
    result = first.sync(native, result)
    assert first.writes == second.writes == 0
    assert result[0][field] == lower[field]
    assert local == before and native._sync_inhalt_hash(local, native.KONTAKT_FELDER) == exact
    assert set(result[0]['syncQuellen']) == {A, B}
    first.value, second.value = email('Alex.Example+tag@Example.Test'), email('Alex.Example+tag@Example.Test')
    first.etag, second.etag = '"a-v3"', '"b-v3"'
    _, create, change, delete, count = native.sync_merge(copy.deepcopy(result), {first.value['uid']: copy.deepcopy(first.value)}, [], 0,
        native.KONTAKT_FELDER, dav=(A, {}, {first.value['uid']: {'href': first.href, 'etag': first.etag}}), kontakt_nur_lesen=True)
    assert not create and not change and not delete and count['konflikte'] == 0
    result = first.sync(native, result)
    result = second.sync(native, result)
    result = first.sync(native, result)
    assert first.writes == second.writes == 1
    assert native._email_liste(first.value) == native._email_liste(second.value) == ['alex.example+tag@example.test']
    for different in ('alex.example@example.test', 'alexexample+tag@example.test', 'alex.example+other@example.test'):
        assert native._kontakt_label_vergleich(local, True) != native._kontakt_label_vergleich(email(different), True)
