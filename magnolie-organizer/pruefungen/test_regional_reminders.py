"""Native notification text, synthetic values, no notifications sent (#85)."""
from pathlib import Path
import locale
import re

import pytest
from modul_laden import quellmodul_laden


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'gi', None)
    return quellmodul_laden('regional_reminders_test', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')


@pytest.mark.parametrize('region,marker', [('en-US', 'PM'), ('de-DE', 'PM'), ('fr-FR', 'PM'),
    ('es-ES', 'p.'), ('it-IT', 'PM'), ('nl-NL', 'p.m.'), ('pt-PT', 'PM|da tarde'), ('ru-RU', 'PM'),
    ('cs-CZ', 'odp.'), ('pl-PL', 'PM'), ('hsb-DE', r'pop\.|popołdnju'), ('da-DK', 'PM'), ('nb-NO', 'p.m.'),
    ('hi-IN', 'pm'), ('zh-CN', '下午'), ('ja-JP', '午後'), ('ar-EG', 'م'), ('uk-UA', 'пп'),
    ('be-BY', 'PM'), ('tr-TR', 'ÖS')])
def test_native_clock_uses_regional_period_without_global_locale_mutation(native, region, marker):
    native._REGIONAL.update(language=region.split('-')[0], formatLocale=region, hourCycle='h12')
    native._icu_uhrzeit_api()  # The tested desktop runtime must supply its real ICU.
    before = locale.setlocale(locale.LC_TIME)
    shown = native.uhrzeit_kurz('14:35:47')
    assert re.search(marker, shown), (region, shown)
    assert '47' not in shown
    assert native.uhrzeit_kurz('00:00') != native.uhrzeit_kurz('12:00')
    _, body = native.erinnerungstext(dict(titel='Synthetic', datum='2026-10-04', zeit='14:35:47'))
    assert shown in body
    assert locale.setlocale(locale.LC_TIME) == before


def test_system_and_explicit_clock_choice_are_independent(native):
    native._REGIONAL.update(language='en', formatLocale='en-US', hourCycle='system')
    assert 'PM' in native.uhrzeit_kurz('14:35')
    native._REGIONAL['hourCycle'] = 'h23'
    assert native.uhrzeit_kurz('14:35') == '14:35'
    native._REGIONAL.update(language='de', formatLocale='de-DE', hourCycle='system')
    assert native.uhrzeit_kurz('14:35') == '14:35'
    native._REGIONAL['hourCycle'] = 'h12'
    assert 'PM' in native.uhrzeit_kurz('14:35')
    assert native.uhrzeit_kurz('') == ''
