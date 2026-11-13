import copy
import pytest
from test_startup_read_failure import native
from test_provider_label_convergence import card, Book, A


@pytest.mark.parametrize('spelling', ('Maik3531(at)Gmail.com', 'Maik3531[at]Gmail.com', 'Maik3531[AT]Gmail.com'))
def test_email_field_import_and_sync(native, spelling):
    parsed = native.vcf_lesen('BEGIN:VCARD\r\nVERSION:3.0\r\nUID:mail-fixture\r\nFN:Synthetic\r\nEMAIL:' + spelling + '\r\nEND:VCARD\r\n')['kontakte']
    assert len(parsed) == 1 and native._email_liste(parsed[0]) == ['Maik3531@Gmail.com']
    local = card(native, 'emailEintraege', 'local', 2000)
    local['emailEintraege'][0]['wert'] = spelling
    local['email'], local['emails'] = spelling, [spelling]
    local['notiz'] = 'Keep ' + spelling
    remote = copy.deepcopy(local)
    native._kontakt_emails_klein(remote)
    book = Book(A, remote, '"v1"')
    native._dav_syncquelle_setzen(local, A, book.href, '"old"', baseline=local)
    result = book.sync(native, [local])
    assert book.writes == 0 and result[0]['email'] == 'maik3531@gmail.com'
    assert result[0]['notiz'] == 'Keep ' + spelling


def test_ambiguous_obfuscation_is_not_guessed(native):
    assert native._email_adresse('a(at)b(at)example.test') == ''
    assert native._email_adresse('a[at]b[at]example.test') == ''
