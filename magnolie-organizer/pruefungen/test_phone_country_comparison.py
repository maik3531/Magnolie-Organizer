"""#602: source spelling is not a phone identity or a new sync edit."""
import copy
import pytest
from test_startup_read_failure import native
from test_provider_label_convergence import card, Book, A


@pytest.mark.parametrize('country,national,international', [
    ('DE', '0123456', '+49123456'), ('DE', '030 123456', '+4930123456'),
    ('GB', '07700 900123', '+447700900123'), ('IT', '02 12345678', '+390212345678')])
def test_actual_sync_country_equivalence(native, monkeypatch, country, national, international):
    original_key = native._telefon_schluessel
    monkeypatch.setattr(native, '_telefon_schluessel', lambda value, land=None: original_key(value, country if land is None else land))
    for spelling in (national, '00' + international[1:], international):
        local = card(native, 'telefone', 'local', 2000)
        local['telefone'][0]['wert'] = spelling
        local['telefon'] = spelling
        local['mobil'] = ''
        incoming = copy.deepcopy(local)
        incoming['telefone'][0]['wert'] = international
        incoming['telefon'] = international
        book = Book(A, incoming, '"v1"')
        native._dav_syncquelle_setzen(local, A, book.href, '"old"', baseline=local)
        before = copy.deepcopy(local)
        exact = native._sync_inhalt_hash(local, native.KONTAKT_FELDER)
        result = book.sync(native, [local])
        result = book.sync(native, result)
        assert book.writes == 0
        assert result[0]['telefone'][0]['wert'] == spelling
        assert book.value['telefone'][0]['wert'] == international
        assert local == before
        assert native._sync_inhalt_hash(local, native.KONTAKT_FELDER) == exact


def test_country_and_extensions_never_guessed(native):
    for country in ('', 'ZZ', 'GB'):
        assert native._telefon_schluessel('0123456', country) != native._telefon_schluessel('+49123456', country)
    assert native._telefon_schluessel('0123456 ext 1', 'DE') == native._telefon_schluessel('+49123456 ext 1', 'DE')
    assert native._telefon_schluessel('0123456 ext 1', 'DE') != native._telefon_schluessel('+49123456 ext 2', 'DE')
