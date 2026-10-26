#!/usr/bin/env python3
"""Publish unretouched native Android screenshots made with synthetic Notes entries.

Inputs are bounded native-test evidence directories. Private paths and logs are
never included in the public image manifest. Without --apply, only verify.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image


def digest(data):
    return hashlib.sha256(data).hexdigest()


def evidence(directory, navigation=False):
    original = directory / 'android-source-result.json'
    record = json.loads(original.read_text())
    if navigation and not record.get('passed'):
        verified = json.loads((directory / 'native-navigation-verification.json').read_text())
        assert verified.get('passed') is True
        assert verified['originalReportSha256'] == digest(original.read_bytes())
        assert verified['artifactSha256'] == record['artifactSha256']
        assert verified['recoveredLogSha256'] == digest((directory / 'android-final-logcat-recovered.raw').read_bytes())
        assert not verified['crashLines'] and verified['checks'] == record['checks']
    else:
        assert record.get('passed') is True and not record.get('crashLines')
    assert record.get('sourceProbe') is True and len(record['artifactSha256']) == 64
    assert record['display']['pixels'] == '720x1280'
    return record


def dialog_crop(directory, tag, labels):
    source = directory / ('android-final-' + tag + '.xml')
    if not source.is_file():
        source = directory / ('android-final-' + tag + '-after.xml')
    tree = ET.parse(source).getroot()
    parents = {child: parent for parent in tree.iter() for child in parent}
    node = next(node for node in tree.iter('node') if node.get('text') == labels[0])
    while node is not None:
        texts = [child.get('text', '') for child in node.iter('node')]
        bounds = list(map(int, re.findall(r'\d+', node.get('bounds', ''))))
        if len(bounds) == 4 and all(any(label in text for text in texts) for label in labels):
            x1, y1, x2, y2 = bounds
            if 200 <= x2 - x1 < 700 and 150 <= y2 - y1 < 1100:
                return (max(0, x1 - 8), max(0, y1 - 8), min(720, x2 + 8), min(1280, y2 + 8))
        node = parents.get(node)
    raise ValueError('Native dialog crop not found: ' + tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gestures', type=Path, required=True)
    parser.add_argument('--navigation', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    gesture = evidence(args.gestures)
    navigation = evidence(args.navigation, True)
    assert gesture['artifactSha256'] == navigation['artifactSha256']
    assert 'notes-native-rtl-physical-left-right-actions-retained' in gesture['checks']
    assert 'notes-native-due-today-label-renders-accessible-orange' in navigation['checks']
    web = Path(__file__).resolve().parents[1] / 'web'
    captures = {
        'notes-native-properties.png': (args.gestures, 'properties-Notes-dialog'),
        'notes-native-task-properties.png': (args.gestures, 'properties-Tasks-dialog'),
        'notes-native-delete.png': (args.gestures, 'swipe-Notes-delete-question'),
        'notes-native-swipe-settings.png': (args.gestures, 'swipe-configured-settings'),
        'notes-native-sort.png': (args.navigation, 'navigation-note-sort-default'),
        'notes-native-task-sort.png': (args.navigation, 'navigation-task-sort-default'),
        'notes-native-due-today.png': (args.navigation, 'navigation-task-due-today-orange'),
        'notes-native-about.png': (args.navigation, 'navigation-about-online'),
    }
    labels = {
        'notes-native-properties.png': ['Properties', 'Original application', 'Back'],
        'notes-native-task-properties.png': ['Properties', 'Original application', 'Back'],
        'notes-native-delete.png': ['Delete', 'Delete this entry?', 'Cancel'],
        'notes-native-sort.png': ['Sort notes', 'Group by day', 'Save', 'Cancel'],
        'notes-native-task-sort.png': ['Sort tasks', 'Manual order', 'Save', 'Cancel'],
        'notes-native-about.png': ['About Magnolie Notes', 'Published Notes version:', 'GitHub', 'Back'],
    }
    manifest = {'format': 2, 'kind': 'native-android-synthetic-examples',
                'apkSha256': gesture['artifactSha256'], 'images': {}}
    for name, (directory, tag) in captures.items():
        source = directory / ('android-final-' + tag + '.png')
        assert source.is_file() and not source.is_symlink() and 0 < source.stat().st_size <= 16 * 1024 * 1024
        raw = source.read_bytes()
        with Image.open(source) as image:
            assert image.format == 'PNG' and image.size == (720, 1280)
            image.load()
            crop = dialog_crop(directory, tag, labels[name]) if name in labels else (
                (18, 720, 702, 1115) if name == 'notes-native-swipe-settings.png' else (20, 395, 700, 612))
            region = image.crop(crop)
            output = io.BytesIO(); region.save(output, format='PNG')
            encoded_image = output.getvalue()
            with Image.open(io.BytesIO(encoded_image)) as check:
                assert check.tobytes() == region.tobytes(), 'Native screenshot pixels changed'
            manifest['images'][name] = {'sha256': digest(encoded_image), 'sourceSha256': digest(raw),
                'sourceWidth': 720, 'sourceHeight': 1280, 'crop': list(crop), 'width': region.width, 'height': region.height}
        destination = web / name
        if args.apply:
            destination.write_bytes(encoded_image)
        assert destination.read_bytes() == encoded_image
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    target = web / 'notes-native-images.json'
    if args.apply:
        target.write_bytes(encoded)
    assert target.read_bytes() == encoded
    print(f'NOTES NATIVE IMAGES PASS: {len(captures)} lossless native crops; no private paths exported')


if __name__ == '__main__':
    main()
