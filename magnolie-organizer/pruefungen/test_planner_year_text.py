"""Calc must receive actual inline font sizes, not ignored paragraph defaults."""
import io
import xml.etree.ElementTree as ET
import zipfile

from test_category_colors import codec

NS = {key: 'urn:oasis:names:tc:opendocument:xmlns:' + value for key, value in {
    'text': 'text:1.0', 'style': 'style:1.0', 'fo': 'xsl-fo-compatible:1.0'}.items()}


def test_year_holiday_names_have_calc_inline_size_without_changing_text_or_page_geometry(codec):
    label = 'Tag der Deutschen Einheit'
    contents = [[{'datum': '3 Sa', 'eintraege': [{'text': label, 'art': 'feiertag', 'farbe': '#b01820'}]} for _ in range(12)]]
    data = codec.adressen_ods_bytes('Jahresplaner 2026', [str(n) for n in range(12)],
        [['3 Sa\n' + label] * 12], logo_pfad='', kompakt=True, kalenderinhalte=contents)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ET.fromstring(archive.read('content.xml'))
        paragraphs = root.findall('.//text:p[@text:style-name="calendarYearEntry"]', NS)
        assert len(paragraphs) == 12
        for paragraph in paragraphs:
            assert ''.join(paragraph.itertext()) == label
            span = paragraph.find('text:span', NS)
            assert span is not None, 'Calc ignores the small paragraph font: holiday text needs a real text span'
            name = span.get('{' + NS['text'] + '}style-name')
            style = root.find('.//style:style[@style:name="' + name + '"]', NS)
            assert style.get('{' + NS['style'] + '}family') == 'text'
            assert style.find('style:text-properties', NS).get('{' + NS['fo'] + '}font-size') == '3.6pt'
        assert b'style:scale-to-pages="1"' in archive.read('styles.xml')
