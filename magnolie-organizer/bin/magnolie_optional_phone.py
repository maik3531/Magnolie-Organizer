"""Desktop build composition only, never a runtime contributor-key or media grant.

Notes/APK composition is deliberately independent of this desktop module.
"""
import json
from pathlib import Path
import re


FEATURES = frozenset(('photo_sync', 'phone_camera'))
PHOTO_PREFIXES = ('magnolie_file_', 'magnolie_photo_', 'magnolie_transfer_', 'magnolie_media_backup', 'magnolie_media_source')
PHOTO_MODULES = frozenset(('magnolie_catalog_membership.py', 'magnolie_job_catalog_witness.py',
    'magnolie_media_storage_bootstrap.py', 'magnolie_media_retention.py', 'magnolie_media_trash.py', 'magnolie_media_trash_ui.py', 'magnolie_publication_journal.py',
    'magnolie_media_sync.py', 'magnolie_media_transport.py', 'magnolie_media_preview.py', 'magnolie_media_offer.py'))
CAMERA_PREFIXES = ('magnolie_phone_camera', 'magnolie_phone_webcam')


def composition(config):
    if type(config) is not dict:
        raise ValueError('invalid desktop build composition')
    # Existing prepared distributions include the producer's branding verifier.
    # This is NOT the user's entered key and does not unlock runtime functions.
    full = type(config.get('contributorHash')) is str and re.fullmatch('[0-9a-fA-F]{64}', config['contributorHash']) is not None
    selected = config.get('phoneFeatures', {})
    if (type(selected) is not dict or not set(selected) <= FEATURES
            or any(type(value) is not bool for value in selected.values())):
        raise ValueError('invalid desktop build composition')
    return {name: selected.get(name, full) for name in sorted(FEATURES)}


def read_composition(data_directory):
    path = Path(data_directory) / 'build-config.json'
    if path.is_symlink(): raise ValueError('invalid desktop build composition')
    if not path.exists(): return composition({})
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('invalid desktop build composition')
    return composition(json.loads(path.read_text(encoding='utf-8')))


def available(feature):
    if feature not in FEATURES: return False
    bindir = Path(__file__).resolve().parent
    candidates = ((bindir.parent,) if bindir.name == 'python' and bindir.parent.name == 'magnolie-organizer' else
        (bindir.parent / 'share' / 'magnolie-organizer', bindir.parent))
    for directory in candidates:
        if (directory / 'build-config.json').exists() or (directory / 'build-config.json').is_symlink():
            try: return read_composition(directory)[feature]
            except (OSError, ValueError): return False
    return False


def selected_modules(modules, selected):
    if type(selected) is not dict or set(selected) != FEATURES or any(type(value) is not bool for value in selected.values()):
        raise ValueError('invalid desktop build composition')
    return {name for name in modules if not (
        not selected['photo_sync'] and (name.startswith(PHOTO_PREFIXES) or name in PHOTO_MODULES)
        or not selected['phone_camera'] and name.startswith(CAMERA_PREFIXES))}
