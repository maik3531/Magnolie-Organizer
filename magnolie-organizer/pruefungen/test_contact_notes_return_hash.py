"""#628: native Notes fingerprint interoperability, never a renderer save ACK."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_contact_notes_return import notes_content_hash


VECTORS = json.loads((Path(__file__).resolve().parents[2] / 'contracts/contact-original-return-hash-v1-vectors.json').read_text())['vectors']


@pytest.mark.parametrize('vector', VECTORS, ids=lambda vector: vector['name'])
def test_existing_native_notes_content_hash_matches_the_shared_projection(vector):
    assert notes_content_hash(vector['contact']) == vector['sha256']


@pytest.mark.parametrize('value', [None, [], {'auto': True}, {'vorname': True}, {'vcardName': 'N:bad'},
    {'vorname': '\ud800'}, {'telefone': [{'art': 'privat', 'wert': 123}]}, {'gruppen': [None]}])
def test_hash_projection_never_coerces_document_flags_or_wrong_types(value):
    with pytest.raises(ValueError):
        notes_content_hash(value)
