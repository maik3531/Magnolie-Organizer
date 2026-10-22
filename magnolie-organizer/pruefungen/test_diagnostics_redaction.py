"""Shared redaction contract: storage/export boundaries preserve useful context."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_crash import mask_sensitive


def test_shared_vectors_and_idempotent_star_markers():
    source = Path(__file__).resolve().parents[2] / 'contracts/diagnostics-redaction-v1.json'
    for entry in json.loads(source.read_text())['cases']:
        assert mask_sensitive(entry['input']) == entry['expected']
        assert mask_sensitive(entry['expected']) == entry['expected']
