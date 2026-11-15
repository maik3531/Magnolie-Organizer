"""Linux EDS already rejects changed/missing original readback identities (#617)."""
import copy

import pytest
from test_startup_read_failure import native
from test_contact_source_failure_isolation import prepare, run, WireContact


@pytest.mark.parametrize('identity', ('changed', 'missing'))
def test_eds_original_uid_readback_guard_holds_only_failed_source(native, monkeypatch, identity):
    books, data = prepare(native, monkeypatch)
    before = copy.deepcopy(data['kontakte'][0]['syncQuellen'])
    original_uid = data['kontakte'][0]['uid']
    write = native.eds_kontakt_aendern

    def changed_readback(book, text):
        write(book, text)
        if book is books['first']:
            replacement = '' if identity == 'missing' else 'UID:unexpected-source-identity\r\n'
            changed = text.replace('UID:' + original_uid + '\r\n', replacement)
            assert changed != text, 'Synthetic source UID was not changed'
            book.contacts = [WireContact(changed)]

    monkeypatch.setattr(native, 'eds_kontakt_aendern', changed_readback)
    failed = run(native, data, 'first')
    assert failed['ok'] is False and books['first'].writes == 1
    assert failed['kontakte'][0]['sync'] is True
    assert failed['kontakte'][0]['uid'] == original_uid
    assert failed['kontakte'][0]['syncQuellen'] == before
    other = run(native, failed, 'second')
    assert other['ok'] and books['second'].writes == 1
    assert other['kontakte'][0]['uid'] == original_uid
    assert other['kontakte'][0]['syncQuellen']['eds:first'] == before['eds:first']
