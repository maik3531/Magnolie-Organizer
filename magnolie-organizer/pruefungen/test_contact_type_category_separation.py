"""Known field roles are not arbitrary labels, groups or privacy grants (#600)."""
import pytest

from test_startup_read_failure import native


def card(label):
    return ('BEGIN:VCARD\r\nVERSION:3.0\r\nUID:category-fixture\r\n'
            'N:Fixture;Alex;;;\r\nFN:Alex Fixture\r\n'
            'item1.TEL;TYPE=VOICE:+49305550123\r\nitem1.X-ABLabel:' + label + '\r\n'
            'CATEGORIES:Home,Privat,OR6-600 Custom\r\nEND:VCARD\r\n')


@pytest.mark.parametrize('label', ('Immobilienbuero', 'Automobilclub', 'Wohnmobilverein'))
def test_unknown_label_is_not_a_mobile_type_and_categories_survive_reimports(native, label):
    text = card(label)
    for _ in range(3):
        contact, = native.vcf_lesen(text)['kontakte']
        phone, = contact['telefone']
        assert set(phone['typen']) == {'VOICE'}
        assert phone['label'] == label
        assert 'CATEGORIES:Home,Privat,OR6-600 Custom' in contact['vcardRoundtrip']
        assert not contact.get('vertraulich') and not phone.get('rolle')
        text = native.vcard_text(contact)


@pytest.mark.parametrize('label,expected', (
    ('Home', 'HOME'), ('Privat', 'HOME'), ('Private', 'HOME'), ('Zuhause', 'HOME'),
    ('Work', 'WORK'), ('Arbeit', 'WORK'), ('Geschaeftlich', 'WORK'),
    ('Mobile', 'CELL'), ('Mobil', 'CELL'), ('Handy', 'CELL'), ('iPhone', 'CELL'),
    ('Mobiltelefon', 'CELL'), ('Mobile phone', 'CELL'),
    ('Privates Mobiltelefon', 'CELL'),
))
def test_exact_known_phone_aliases_do_not_change_group_membership(native, label, expected):
    contact, = native.vcf_lesen(card(label))['kontakte']
    assert expected in contact['telefone'][0]['typen']
    assert 'CATEGORIES:Home,Privat,OR6-600 Custom' in contact['vcardRoundtrip']
    assert not contact.get('vertraulich')
