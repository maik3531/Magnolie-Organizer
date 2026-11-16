"""Offline AppStream screenshot contracts; no store submission or network access."""
from pathlib import Path
import struct
import unittest
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[1]
LANG = '{http://www.w3.org/XML/1998/namespace}lang'


class AppStreamScreenshots(unittest.TestCase):
    def metadata(self):
        return ET.parse(ROOT / 'magnolie-organizer.appdata.xml').getroot()

    def default(self):
        screenshots = self.metadata().findall('./screenshots/screenshot')
        defaults = [item for item in screenshots if item.get('type') == 'default']
        self.assertEqual(1, len(defaults))
        return defaults[0]

    def test_identity_and_english_german_captions(self):
        component = self.metadata()
        self.assertEqual('desktop-application', component.get('type'))
        self.assertEqual('io.gitlab.maik3531.MagnolieOrganizer', component.findtext('id'))
        self.assertEqual('io.gitlab.maik3531.MagnolieOrganizer.desktop', component.findtext('launchable'))
        captions = {item.get(LANG, 'en'): (item.text or '').strip() for item in self.default().findall('caption')}
        self.assertTrue(captions.get('en'))
        self.assertTrue(captions.get('de'))

    def test_image_url_is_commit_pinned_with_default_english_source(self):
        images = self.default().findall('image')
        self.assertTrue(images)
        for image in images:
            self.assertEqual('source', image.get('type'))
            # AppStream requires the default English source without xml:lang="en".
            self.assertIsNone(image.get(LANG))
            self.assertTrue(image.text.strip().endswith('-en.png'))
            self.assertRegex(image.text.strip(), r'^https://raw\.githubusercontent\.com/maik3531/Magnolie-Organizer/[0-9a-f]{40}/magnolie-organizer/screenshots/[a-z0-9-]+\.png$')

    def test_actual_png_dimensions_and_crc_match_metadata(self):
        for image in self.default().findall('image'):
            name = image.text.strip().rsplit('/', 1)[-1]
            self.assertRegex(name, r'^[a-z0-9-]+\.png$')
            data = (ROOT / 'screenshots' / name).read_bytes()
            self.assertEqual(b'\x89PNG\r\n\x1a\n', data[:8])
            width, height = struct.unpack('>II', data[16:24])
            self.assertEqual((int(image.get('width')), int(image.get('height'))), (width, height))
            self.assertGreaterEqual(width, 620)
            self.assertGreaterEqual(height, 351)
            offset = 8
            while offset < len(data):
                size = struct.unpack('>I', data[offset:offset + 4])[0]
                content = data[offset + 4:offset + 8 + size]
                crc = struct.unpack('>I', data[offset + 8 + size:offset + 12 + size])[0]
                self.assertEqual(crc, zlib.crc32(content) & 0xffffffff)
                offset += size + 12
            self.assertEqual(len(data), offset)


if __name__ == '__main__': unittest.main()
