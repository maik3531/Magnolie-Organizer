"""Source metadata checks, not F-Droid scanner/build/signature acceptance."""
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
METADATA = ROOT / 'fastlane/metadata/android'


@pytest.mark.parametrize('locale', ['de-DE', 'en-US'])
def test_store_descriptions_fit_limits_and_name_the_optional_phone_role(locale):
    short = (METADATA/locale/'short_description.txt').read_text().strip()
    full = (METADATA/locale/'full_description.txt').read_text().strip()
    assert 1 <= len(short) <= 80 and 1 <= len(full) <= 4000
    assert 'Organizer' in short
    assert ('Telefonverbindung' if locale == 'de-DE' else 'phone link') in short
    for name in ('Magnolie Notes', 'KDE Connect', 'Android', 'Bluetooth', 'RFCOMM', 'NSD/mDNS', 'GitHub', 'GPS', 'SMS', 'RCS'):
        assert name in full
    if locale == 'de-DE':
        assert 'unabhängig vom Notizabgleich und ohne KDE Connect' in full
        assert 'Magnolie Notes-Telefonverbindung → Erweiterte Funktionen' in full
        assert 'noch nicht freigeschaltet' in full and 'noch keine verfügbare Funktion' in full
        assert 'ohne Notizinhalte oder Kontozugangsdaten zu senden' in full
        assert 'keine APK-Updates selbst' in full
    else:
        assert 'independently of note synchronization and without KDE Connect' in full
        assert 'Magnolie Notes phone connection → Advanced functions' in full
        assert 'not yet enabled' in full and 'not yet an available feature' in full
        assert 'without sending note content or account credentials' in full
        assert 'does not download/install APK updates itself' in full


@pytest.mark.parametrize('locale', ['de-DE', 'en-US'])
def test_photo_access_and_existing_optional_integrations_are_not_general_permissions(locale):
    full = (METADATA/locale/'full_description.txt').read_text()
    if locale == 'de-DE':
        for phrase in ('Alle Integrationen sind optional', 'nicht beim App-Start', 'ausgewählte Bilder',
                       'kein allgemeiner Schreib-/Löschzugriff', 'Kontaktfotos', 'Schreiben braucht eine eigene Berechtigung',
                       'kein allgemeiner Zugriff auf private App-Daten', 'keine GPS-Koordinaten',
                       'automatischer Personal Sync bleibt WLAN-beschränkt', 'systemverwaltetem Freisprech-Audio'):
            assert phrase in full
    else:
        for phrase in ('All integrations are optional', 'not requested at startup', 'selected images',
                       'no general write/delete access', 'contact photos', 'Writing needs separate permission',
                       'not general access to private app data', 'not GPS coordinates',
                       'automatic Personal Sync remains Wi-Fi-only', 'system-managed hands-free audio'):
            assert phrase in full


def test_current_manifest_photo_scope_is_explained_without_advertising_future_capture():
    manifest = ET.parse(ROOT/'magnolie-notes/app/src/main/AndroidManifest.xml').getroot()
    android = '{http://schemas.android.com/apk/res/android}'
    permissions = {entry.get(android+'name'):entry for entry in manifest.findall('uses-permission')}
    notes = (ROOT/'magnolie-notes/F-DROID.md').read_text()
    for permission in ('READ_EXTERNAL_STORAGE', 'READ_MEDIA_IMAGES', 'READ_MEDIA_VISUAL_USER_SELECTED'):
        assert 'android.permission.'+permission in permissions and permission in notes
    assert permissions['android.permission.READ_EXTERNAL_STORAGE'].get(android+'maxSdkVersion') == '32'
    assert 'android.permission.CAMERA' not in permissions and 'android.permission.RECORD_AUDIO' not in permissions
    assert 'nicht als bereits verfügbare APK-Funktionen beworben' in notes
    assert 'Beschreibungstext allein ersetzt weder F-Droids Prüfung' in notes


def test_fdroid_metadata_locations_and_notes_readme_share_the_backend_boundary():
    notes = (ROOT/'magnolie-notes/F-DROID.md').read_text()
    for locale in ('de-DE', 'en-US'):
        assert f'../fastlane/metadata/android/{locale}/' in notes
        for name in ('short_description.txt', 'full_description.txt'):
            assert (METADATA/locale/name).is_file()
    readme = (ROOT/'magnolie-notes/LIESMICH.md').read_text()
    assert 'Magnolie Notes-Telefonverbindung → Erweiterte Funktionen' in readme
    assert 'unabhängig vom Notizabgleich' in readme and 'ohne KDE Connect' in readme
    assert 'noch keine freigegebenen APK-Funktionen' in readme
