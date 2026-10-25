"""#152: automatic sources are optional, fresh, explicit and IANA-bound."""
import copy
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_timezone as zones
from modul_laden import quellmodul_laden


def settings():
    return dict(timeZoneManagement='automatic', timeZoneDetection='auto',
        timeZone='Europe/Berlin', timeZoneManual='America/New_York')


@pytest.mark.parametrize('mode', ['off', 'manual'])
def test_disabled_or_manual_does_not_query_phone_gps_or_network(mode):
    calls = []
    result = zones.detect(dict(settings(), timeZoneManagement=mode),
        {name: lambda name=name: calls.append(name) for name in ('phone', 'gps', 'ip', 'system')}, now=1000000)
    assert calls == [] and result['automatic'] is False
    assert result['zone'] == ('Europe/Berlin' if mode == 'off' else 'America/New_York')


def test_fresh_own_phone_precedes_an_ip_vpn_location_without_changing_preferences():
    config = settings(); before = copy.deepcopy(config); calls = []
    result = zones.detect(config, {
        'phone': lambda: {'zone': 'Asia/Tokyo', 'captured_ms': 999000},
        'ip': lambda: calls.append('ip') or {'zone': 'Europe/Berlin'}}, now=1000000)
    assert result['zone'] == 'Asia/Tokyo' and result['source'] == 'phone'
    assert calls == [] and config == before


@pytest.mark.parametrize('captured', [0, 1000000 + 30001, True, 1000000.0])
def test_stale_future_or_invalid_phone_observation_cannot_override_a_fresh_location(captured):
    result = zones.detect(settings(), {
        'phone': lambda: {'zone': 'Asia/Tokyo', 'captured_ms': captured},
        'gps': lambda: {'zone': 'Europe/London', 'captured_ms': 999999}}, now=1000000)
    assert result['source'] == 'gps' and result['zone'] == 'Europe/London'


def test_selected_source_failure_uses_manual_fallback_instead_of_an_unselected_source():
    config = dict(settings(), timeZoneDetection='gps')
    calls = []
    result = zones.detect(config, {'gps': lambda: None, 'ip': lambda: calls.append('ip') or 'Asia/Tokyo'}, now=1000000)
    assert calls == [] and result['zone'] == 'America/New_York' and result['fallback'] is True


def test_country_or_utc_offset_alone_does_not_invent_a_zone_for_a_multi_zone_country():
    response = zones.from_ip(lambda _url: json.dumps({'country_code': 'US', 'utc_offset': '-0500'}))
    result = zones.detect(dict(settings(), timeZoneDetection='ip'), {'ip': lambda: response}, now=1000000)
    assert result['source'] == 'manual' and result['fallback'] is True
    assert zones.zone_id('Mars/Olympus') is None
    assert zones.zone_id('../../etc/passwd') is None
    assert zones.zone_id('UTC') == 'UTC'


def test_ip_service_is_bounded_to_explicit_zone_metadata():
    calls = []
    result = zones.from_ip(lambda url: calls.append(url) or '{"timezone":"America/St_Johns"}')
    assert result['zone'] == 'America/St_Johns' and calls == [zones.IP_URL]


def test_coordinate_lookup_keeps_location_time_and_uses_existing_forecast_provider():
    calls = []
    result = zones.from_coordinates({'latitude': 51.5, 'longitude': -.1, 'captured_ms': 999000},
        lambda url: calls.append(url) or '{"timezone":"Europe/London"}', now=1000000)
    assert result == {'zone': 'Europe/London', 'captured_ms': 999000}
    query = parse_qs(urlsplit(calls[0]).query)
    assert query['timezone'] == ['auto'] and query['latitude'] == ['51.5']


@pytest.mark.parametrize('point', [
    {'latitude': 91, 'longitude': 0, 'captured_ms': 999000},
    {'latitude': True, 'longitude': 0, 'captured_ms': 999000},
    {'latitude': 51, 'longitude': float('nan'), 'captured_ms': 999000},
    {'latitude': 51, 'longitude': 0, 'captured_ms': 0}])
def test_invalid_or_stale_coordinates_are_not_sent_to_the_network(point):
    calls = []
    with pytest.raises(ValueError):
        zones.from_coordinates(point, lambda url: calls.append(url), now=1000000)
    assert calls == []


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setitem(sys.modules, 'gi', None)
    return quellmodul_laden('timezone_settings_writer', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')


def test_native_profile_update_is_checked_and_does_not_rewrite_unchanged_observations(native, tmp_path):
    path = str(tmp_path / 'locale.json')
    config = dict(native.REGIONAL_STANDARD, timeZoneManagement='automatic', timeZoneDetection='ip', timeZoneManual='Europe/Berlin')
    assert native.regional_einstellungen_schreiben(config, path)
    before = native.regional_einstellungen_geprueft_lesen(path)
    calls = []
    def fetch(url):
        calls.append(url)
        return '{"timezone":"Asia/Tokyo"}'
    result = native.zeitzone_automatisch_aktualisieren(erwartet=before, pfad=path, holer=fetch, jetzt=1000000)
    assert result['native_changed'] is True and result['source'] == 'ip'
    assert result['regional']['timeZone'] == 'Asia/Tokyo' and result['regional']['timeZoneManual'] == 'Europe/Berlin'
    assert native.regional_einstellungen_geprueft_lesen(path) == result['regional']
    image = Path(path).read_bytes()
    repeated = native.zeitzone_automatisch_aktualisieren(erwartet=result['regional'], pfad=path, holer=fetch, jetzt=1000100)
    assert repeated['native_changed'] is False and Path(path).read_bytes() == image
    with pytest.raises(ValueError, match='regional_conflict'):
        native.zeitzone_automatisch_aktualisieren(erwartet=before, pfad=path, holer=fetch, jetzt=1000200)
    assert len(calls) == 2


def test_native_disabled_mode_and_changed_preferences_cannot_start_or_commit_location_queries(native, tmp_path):
    path = str(tmp_path / 'locale.json')
    assert native.regional_einstellungen_schreiben(dict(native.REGIONAL_STANDARD), path)
    before = native.regional_einstellungen_geprueft_lesen(path)
    calls = []
    assert native.zeitzone_automatisch_aktualisieren(erwartet=before, pfad=path, holer=lambda url: calls.append(url))['automatic'] is False
    assert calls == []
    enabled = dict(before, timeZoneManagement='automatic', timeZoneDetection='ip', timeZoneManual='Europe/Berlin')
    assert native.regional_einstellungen_schreiben(enabled, path)
    def change_during_fetch(_url):
        assert native.regional_einstellungen_schreiben(dict(enabled, timeZoneManagement='off'), path)
        return '{"timezone":"Asia/Tokyo"}'
    with pytest.raises(ValueError, match='regional_conflict'):
        native.zeitzone_automatisch_aktualisieren(erwartet=native.regional_einstellungen_geprueft_lesen(path), pfad=path, holer=change_during_fetch)
    assert native.regional_einstellungen_geprueft_lesen(path)['timeZoneManagement'] == 'off'
    assert native.regional_einstellungen_geprueft_lesen(path)['timeZone'] == 'system'


def test_native_detection_preview_does_not_change_zone_before_book_anchoring(native, tmp_path):
    path = str(tmp_path / 'locale.json')
    config = dict(native.REGIONAL_STANDARD, timeZone='Europe/Berlin', timeZoneManagement='automatic',
                  timeZoneDetection='ip', timeZoneManual='Europe/Berlin')
    assert native.regional_einstellungen_schreiben(config, path)
    before = native.regional_einstellungen_geprueft_lesen(path)
    image = Path(path).read_bytes()
    result = native.zeitzone_automatisch_aktualisieren(erwartet=before, pfad=path,
        holer=lambda _url: '{"timezone":"Asia/Tokyo"}', jetzt=1000000, anwenden=False)
    assert result['time_zone'] == 'Asia/Tokyo' and result['source'] == 'ip'
    assert result['native_changed'] is False and result['regional'] == before
    assert native.regional_einstellungen_geprueft_lesen(path) == before and Path(path).read_bytes() == image


def test_native_detection_rechecks_book_permission_after_optional_source_returns(native, tmp_path):
    path = str(tmp_path / 'locale.json')
    config = dict(native.REGIONAL_STANDARD, timeZoneManagement='automatic', timeZoneDetection='ip')
    assert native.regional_einstellungen_schreiben(config, path)
    before = native.regional_einstellungen_geprueft_lesen(path)
    permitted = [True]
    def changed_source(_url):
        permitted[0] = False
        return '{"timezone":"Asia/Tokyo"}'
    with pytest.raises(PermissionError, match='locked'):
        native.zeitzone_automatisch_aktualisieren(erwartet=before, pfad=path, holer=changed_source,
            erlaubt=lambda: permitted[0], anwenden=False)
    assert native.regional_einstellungen_geprueft_lesen(path) == before


@pytest.mark.parametrize('task', [False, True])
@pytest.mark.parametrize('shape', ['utc-fold', 'tzid', 'floating', 'date', 'series', 'duration'])
def test_real_ics_export_reimport_keeps_zone_context_and_wire_instants(native, monkeypatch, task, shape):
    monkeypatch.setitem(native._REGIONAL, 'timeZone', 'Europe/Berlin')
    component, ending = ('VTODO', 'DUE') if task else ('VEVENT', 'DTEND')
    starts = {
        'utc-fold': 'DTSTART:20261101T063047Z',
        'tzid': 'DTSTART;TZID=America/New_York:20261022T013047',
        'floating': 'DTSTART:20261022T013047',
        'date': 'DTSTART;VALUE=DATE:20261022',
        'series': 'DTSTART;TZID=America/New_York:20261022T013047',
        'duration': 'DTSTART;TZID=America/New_York:20261022T013047',
    }
    ends = {
        'utc-fold': ending + ':20261101T073047Z',
        'tzid': ending + ';TZID=America/New_York:20261022T023047',
        'floating': ending + ':20261022T023047',
        'date': ending + ';VALUE=DATE:20261023',
        'series': ending + ';TZID=America/New_York:20261022T023047',
        'duration': 'DURATION:PT1H',
    }
    recurrence = ['RRULE:FREQ=DAILY;COUNT=3', 'EXDATE;TZID=America/New_York:20261023T013047'] if shape == 'series' else []
    text = '\r\n'.join(['BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:' + component,
        'UID:owned-' + shape, 'SUMMARY:Owned zone fixture', starts[shape], ends[shape],
        *recurrence, 'X-OWNED:keep', 'END:' + component, 'END:VCALENDAR'])
    for _round in range(3):
        items = native.ics_lesen(text, quellen_id='owned-zone-source')['aufgaben' if task else 'termine']
        assert len(items) == 1
        text = native.ics_schreiben_aufgaben(items) if task else native.ics_schreiben_termine(items)
        lines = native._entfalte_zeilen(text)
        expected = [starts[shape], ends[shape], *recurrence, 'UID:owned-' + shape, 'X-OWNED:keep']
        assert all(line in lines for line in expected), ([line for line in expected if line not in lines], [line for line in lines if line.startswith(('DTSTART', 'DTEND', 'DUE', 'UID', 'X-OWNED'))])
