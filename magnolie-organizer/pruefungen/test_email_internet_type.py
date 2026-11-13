from test_startup_read_failure import native


def test_email_internet_is_transport_type_not_a_role(native):
    def card(types):
        return {'emailEintraege': [{'wert': 'fixture@example.test', 'typen': types}]}
    assert native._kontakt_label_vergleich(card([])) == native._kontakt_label_vergleich(card(['INTERNET']))
    assert native._kontakt_label_vergleich(card(['HOME'])) == native._kontakt_label_vergleich(card(['HOME', 'INTERNET']))
    assert native._kontakt_label_vergleich(card(['HOME'])) != native._kontakt_label_vergleich(card(['WORK', 'INTERNET']))
