"""Genuine synthetic confirmed section removal; never a private excluded book (#570)."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from test_or6_import import rotate
from magnolie_or6 import _Document, read_or6

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-section-removal.json').read_text())


def fixture(name):
    item = CONTRACT['files'][name]
    raw = gzip.decompress(base64.b64decode(item['gzip_base64'], validate=True))
    assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    return raw


@pytest.mark.parametrize('name', ('section-removed-verified-v2-570.or6', 'section-removed-reopened-v2-570.or6'))
def test_original_confirmed_removal_never_restores_pages_or_changes_other_collections(name):
    before_raw = fixture('section-before-remove-570.or6'); after_raw = fixture(name)
    before_doc, after_doc = _Document(before_raw), _Document(after_raw)
    assert sum(tag == 0x510 for tag, _ in before_doc.blocks.values()) == 2
    assert sum(tag == 0x510 for tag, _ in after_doc.blocks.values()) == 0
    before, after = read_or6(before_raw), read_or6(after_raw)
    assert len(before['notizen']) == CONTRACT['expected']['beforeNotes']
    assert after['notizen'] == []
    for key in CONTRACT['expected']['unchangedCollections']:
        assert before[key] == after[key], 'Removing the source notebook changed an unrelated collection'
    # A byte-for-byte caller buffer cannot be modified by the read-only importer.
    assert hashlib.sha256(after_raw).hexdigest() == CONTRACT['files'][name]['sha256']
