from test_startup_read_failure import native


def test_vcard_categories_roundtrip_and_added_category_is_not_replacement(native):
    source = 'BEGIN:VCARD\nVERSION:3.0\nUID:group-fixture\nN:Person;Synthetic;;;\nFN:Synthetic Person\nCATEGORIES:Family,Team\\, North\nX-UNKNOWN:preserve\nEND:VCARD\n'
    card = native.vcf_lesen(source)['kontakte'][0]
    assert native._kontakt_konflikt_inhalt(card)['gruppen'] == ['Family', 'Team, North']
    encoded = native.vcard_text(card)
    assert 'CATEGORIES:Family,Team\\, North' in encoded and 'X-UNKNOWN:preserve' in encoded
    changed = dict(card, vcardRoundtrip=[line for line in card['vcardRoundtrip'] if not line.startswith('CATEGORIES:')] + ['CATEGORIES:Family,Team\\, North,Work'])
    assert native._kontakt_nur_ergaenzungen(card, changed)
