"""Editable monthly ODS, using synthetic records only (#82)."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest
from modul_laden import quellmodul_laden

NS = {'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
      'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
      'number': 'urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0'}


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'gi', None)
    return quellmodul_laden('time_sheet_test', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')


def record(start, end, pause=0, zone='UTC'):
    minute = lambda value: int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() // 60)
    return dict(id=str(uuid4()), startMinute=minute(start), endMinute=minute(end) if end else None,
                pauseMinutes=pause, zone=zone, type='Synthetic activity', note='=HYPERLINK("not a formula")')


def report(entries=(), twelve=True):
    parts = lambda pairs: [dict(type=kind, value=value) for kind, value in pairs]
    return dict(month='2026-10', monthTitle='October 2026', name='Synthetic name', locale='en-US',
        labels=dict(title='Time tracking', name='Name', date='Date', signature='Signature', total='Total', clock='Time',
            columns=['Date', 'Activity', 'Start', 'End date', 'End', 'Hours', 'Pause (minutes)', 'Total time', 'Note', 'Clock change (min)']),
        digits='0123456789', weekdays=['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], periods=['AM', 'PM'],
        dateParts=parts([('month', '10'), ('literal', '/'), ('day', '04'), ('literal', '/'), ('year', '2026')]),
        timeParts=parts([('hour', '02'), ('literal', ':'), ('minute', '35')] + ([('literal', ' '), ('dayPeriod', 'PM')] if twelve else [])),
        entries=list(entries))


def unpack(native, data):
    archive = ZipFile(BytesIO(native.zeiterfassung_ods_bytes(data)))
    assert archive.infolist()[0].filename == 'mimetype'
    assert archive.infolist()[0].compress_type == 0
    content = ET.fromstring(archive.read('content.xml'))
    ET.fromstring(archive.read('styles.xml'))
    ET.fromstring(archive.read('META-INF/manifest.xml'))
    return content


def test_month_has_free_days_multiple_entries_and_correct_overnight_dst_totals(native):
    data = report([
        record('2026-10-31T13:00:00Z', '2026-10-31T17:00:00Z', 15, 'America/New_York'),
        record('2026-11-01T02:00:00Z', '2026-11-01T11:00:00Z', 30, 'America/New_York')])
    content = unpack(native, data)
    table = content.find('.//table:table', NS)
    rows = table.findall('table:table-row', NS)
    daily = rows[4:-3]  # Four top rows; two headers live in table-header-rows.
    assert len(daily) == 32
    last = daily[-1].findall('table:table-cell', NS)
    assert last[3].get('{%s}date-value' % NS['office']) == '2026-11-01'
    assert last[9].get('{%s}value' % NS['office']) == '-60'
    assert float(last[5].get('{%s}value' % NS['office'])) == pytest.approx(540 / 1440)
    assert float(last[7].get('{%s}value' % NS['office'])) == pytest.approx(510 / 1440)
    total = rows[-3].findall('table:table-cell', NS)
    assert float(total[7].get('{%s}value' % NS['office'])) == pytest.approx(735 / 1440)
    assert total[7].get('{%s}formula' % NS['table']).startswith('of:=SUM(')
    assert all(cell.get('{%s}formula' % NS['table']) for cell in (last[5], last[7], last[10]))
    assert '=HYPERLINK' in ''.join(last[8].itertext())
    assert last[8].get('{%s}value-type' % NS['office']) == 'string'
    assert last[8].get('{%s}formula' % NS['table']) is None


def test_duration_does_not_wrap_and_clock_format_is_independent(native):
    entry = record('2026-10-01T00:00:00Z', '2026-10-08T01:00:00Z', 30)
    for twelve in (False, True):
        content = unpack(native, report([entry], twelve))
        assert '168:30' in list(content.itertext())
        assert bool(content.findall('.//number:am-pm', NS)) == twelve
        assert not content.findall('.//number:seconds', NS)
        duration_style = next(style for style in content.findall('.//number:time-style', NS)
            if style.get('{urn:oasis:names:tc:opendocument:xmlns:style:1.0}name') == 'durationFormat')
        assert duration_style.get('{%s}truncate-on-overflow' % NS['number']) == 'false'


def test_selected_days_limit_rows_and_totals_without_losing_multiple_entries(native):
    data = report([record('2026-10-01T08:00:00Z', '2026-10-01T09:00:00Z'),
                   record('2026-10-02T08:00:00Z', '2026-10-02T16:00:00Z'),
                   record('2026-10-31T08:00:00Z', '2026-10-31T09:00:00Z'),
                   record('2026-10-31T10:00:00Z', '2026-10-31T11:00:00Z')])
    data['days'] = [31, 1]
    content = unpack(native, data)
    rows = content.find('.//table:table', NS).findall('table:table-row', NS)
    daily = rows[4:-3]
    assert len(daily) == 3
    assert [row.find('table:table-cell', NS).get('{%s}date-value' % NS['office']) for row in daily] == [
        '2026-10-01', '2026-10-31', '2026-10-31']
    assert float(rows[-3].findall('table:table-cell', NS)[7].get('{%s}value' % NS['office'])) == pytest.approx(180/1440)
    data['days'] = []
    with pytest.raises(ValueError): native.zeiterfassung_ods_bytes(data)


def test_regional_cached_text_and_open_records(native):
    data = report([record('2026-10-04T14:35:00Z', None)])
    data.update(locale='ar-EG', digits='٠١٢٣٤٥٦٧٨٩', periods=['ص', 'م'])
    content = unpack(native, data)
    assert '٠٢:٣٥ م' in list(content.itertext())
    data['entries'][0]['endMinute'] = data['entries'][0]['startMinute'] - 1
    with pytest.raises(ValueError):
        native.zeiterfassung_ods_bytes(data)


@pytest.mark.parametrize('enabled,regions,expected', [
    (True, ['DE-TH'], True), (True, ['TH'], True), (True, ['DE-BY'], False),
    (True, [], True), (False, [], False), (False, ['DE-TH'], False)])
def test_inherited_holiday_toggle_and_region_apply_without_hiding_sundays(native, enabled, regions, expected):
    data = report()
    data['calendar'] = dict(enabled=enabled, country='DE', regions=regions, holidays=[
        dict(date='2026-10-31', name='Synthetic regional holiday', country='DE', nationwide=False, regions=['DE-TH']),
        dict(date='2026-10-03', name='Synthetic national holiday', country='DE', nationwide=True, regions=[]),
        dict(date='2026-10-02', name='Wrong country holiday', country='AT', nationwide=True, regions=[])])
    content = unpack(native, data)
    rows = content.find('.//table:table', NS).findall('table:table-row', NS)[4:-3]
    cells = lambda day: rows[day - 1].findall('table:table-cell', NS)
    style = '{%s}style-name' % NS['table']
    assert cells(4)[0].get(style) == 'dateSunday'
    assert cells(31)[0].get(style) == ('dateHoliday' if expected else 'date')
    assert cells(3)[0].get(style) == ('dateHoliday' if enabled else 'date')
    assert cells(2)[0].get(style) == 'date'
    assert ('Synthetic regional holiday' in ''.join(content.itertext())) == expected
    assert ('Synthetic national holiday' in ''.join(content.itertext())) == enabled
    assert 'Wrong country holiday' not in ''.join(content.itertext())
