from test_startup_read_failure import native


def test_email_case_is_not_sharp_s_transliteration(native):
    def card(address):
        return {'email': address}
    assert native._kontakt_label_vergleich(card('Alex@Example.Test')) == native._kontakt_label_vergleich(card('alex@example.test'))
    assert native._kontakt_label_vergleich(card('groß@example.test')) != native._kontakt_label_vergleich(card('gross@example.test'))
    assert native._kontakt_konflikt_inhalt(card('groß@example.test')) != native._kontakt_konflikt_inhalt(card('gross@example.test'))
