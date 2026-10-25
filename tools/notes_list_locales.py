#!/usr/bin/env python3
"""Generate and verify localized Android list controls without touching other strings."""
import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--catalog', type=Path, default=Path(__file__).with_suffix('.json'))
    parser.add_argument('--resource', default='list_view.xml')
    args = parser.parse_args()
    assert args.resource.endswith('.xml') and Path(args.resource).name == args.resource
    text = json.loads(args.catalog.read_text())
    keys = text['keys']
    assert len(set(keys)) == len(keys)
    languages = {code: values for code, values in text.items() if code != 'keys'}
    assert len(languages) == 20
    for code, values in languages.items():
        assert len(values) == len(keys) and all(values)
        folder = 'values' if code == 'en' else 'values-' + code.replace('zh_CN', 'zh-rCN')
        path = ROOT / 'magnolie-notes/app/src/main/res' / folder / args.resource
        if args.apply:
            lines = ['<?xml version="1.0" encoding="utf-8"?>', '<resources>']
            for key, value in zip(keys, values):
                lines.append('    <string name="' + key + '">' + escape(value).replace("'", "\\'") + '</string>')
            path.write_text('\n'.join([*lines, '</resources>', '']))
        actual = {node.get('name'): (node.text or '').replace("\\'", "'") for node in ET.parse(path).getroot()}
        assert actual == dict(zip(keys, values)), code
    print('NOTES LIST LOCALES PASS: 20 languages,', len(keys), 'controls each')


if __name__ == '__main__':
    main()
