#!/usr/bin/env python3
"""Demonstrate supported vCard emergency contacts at the actual Python restore."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--checkout', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
root, out = args.checkout.resolve(), args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(root / 'magnolie-organizer/pruefungen'))
from modul_laden import quellmodul_laden

source = root / 'magnolie-organizer/bin/magnolie-organizer'
native = quellmodul_laden('emergency_restore_probe', source)
persons = [
    {'name': 'Alex Example', 'telefon': '+12025550101', 'status': 'Family'},
    {'name': 'Berta Example', 'telefon': '+12025550102', 'status': 'Friend'},
]
seed = native._kontaktpersonen_setzen(
    {'id': 'contact-local', 'uid': 'old-uid', 'vorname': 'Current'}, persons)
vcf = native.vcf_schreiben([seed])
(out / 'emergency-contacts.vcf').write_text(vcf)
snapshot_contact = native.vcf_lesen(vcf)['kontakte'][0]
snapshot_contact['id'] = 'contact-local'
assert snapshot_contact['kontaktpersonen'] == persons
current_contact = copy.deepcopy(snapshot_contact)
current_contact['uid'] = 'new-uid'
native._kontaktpersonen_setzen(current_contact, [])
snapshot = {'kontakte': [snapshot_contact]}
current = {'kontakte': [current_contact]}
before = copy.deepcopy((snapshot, current))
restored = native.journal_restore_daten(snapshot, current, ['contacts'], 'additive')
contact = restored['kontakte'][0]
result = {
    'checkout_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip(),
    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'vcard_sha256': hashlib.sha256(vcf.encode()).hexdigest(),
    'field_in_supported_contract': 'kontaktpersonen' in native.KONTAKT_FELDER,
    'snapshot_persons_from_actual_vcard_roundtrip': snapshot_contact['kontaktpersonen'],
    'snapshot_person_count': len(native._kontaktpersonen_liste(snapshot_contact)),
    'restored_person_list': contact.get('kontaktpersonen'),
    'restored_person_count_after_actual_normalization': len(native._kontaktpersonen_liste(contact)),
    'restored_legacy_first_person_name': contact.get('kontaktpersonName'),
    'restored_card_count': len(restored['kontakte']),
    'current_uid_preserved': contact['uid'] == current_contact['uid'],
    'inputs_unchanged': (snapshot, current) == before,
    'scope': 'Actual Python vCard writer, reader, contact normalization and restore; no native GUI claim.',
}
(out / 'python-contact-persons.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
