#!/usr/bin/env python3
"""Source integration contracts. These do not compile or emulate Android."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'app/src/main/java/io/gitlab/maik3531/magnolienotes'
def read(path): return (SRC / path).read_text()

class LanContracts(unittest.TestCase):
    def test_current_sdk_manifest_and_migration_stop(self):
        build = (ROOT / 'app/build.gradle.kts').read_text()
        for value in ('compileSdk = 35', 'targetSdk = 35', 'minSdk = 26', 'check(requireNotNull(targetSdk) < 37)'):
            self.assertIn(value, build)
        self.assertNotIn('ACCESS_LOCAL_NETWORK', (ROOT / 'app/src/main/AndroidManifest.xml').read_text())
    def test_no_background_prompt(self):
        for path in ('MagnolieApp.kt', 'baum/BaumDienst.kt', 'baum/Baumwerk.kt', 'netz/LanFreigabe.kt'):
            text = read(path)
            self.assertNotIn('RequestPermission', text)
            self.assertNotIn('requestPermissions(', text)
        self.assertIn('LanFreigabe.initialisieren(this)', read('MagnolieApp.kt'))
        self.assertIn('werk.lanAbgleichen()', read('baum/BaumDienst.kt'))
    def test_lan_stop_preserves_bluetooth_and_persistent_state(self):
        method = read('baum/Server.kt').split('@Synchronized fun lanAnhalten() {')[1].split('private fun neuerArbeiter')[0]
        for forbidden in ('sitzungen.clear', 'empfangGeneration', 'bluetooth', 'ablage'):
            self.assertNotIn(forbidden, method)
        method = read('baum/Baumwerk.kt').split('@Synchronized fun lanAbgleichen() {')[1].split('fun dienstAnhalten')[0]
        for forbidden in ('bluetoothAnhalten', 'aendereBaum', 'baumTransporteAbbrechen'):
            self.assertNotIn(forbidden, method)
    def test_both_discoveries_reject_late_callbacks(self):
        for path in ('baum/Entdeckung.kt', 'telefon/TelefonEntdeckung.kt'):
            text = read(path).split('fun suchen(')[1]
            self.assertIn('aktiv.set(false)', text)
            self.assertGreaterEqual(text.count('LanFreigabe.aktuell(lanMarke)'), 4)
            self.assertIn('LanFreigabe.beobachten', text)
            self.assertIn('LanFreigabe.WARTET', text)
    def test_permission_callback_replays_no_peer_action(self):
        text = read('MainActivity.kt').split('val lanFreigabe =')[1].split('fun lanEinrichten')[0]
        for forbidden in ('BaumDienst.starten', 'TelefonDienst.start', 'beginPairing', 'frageAn', 'allesSynchronisieren'):
            self.assertNotIn(forbidden, text)
        self.assertIn('LanFreigabe.erlaubt()', text)
    def test_wlan_guard_does_not_enter_bluetooth_pipe(self):
        text = read('telefon/TelefonBluetooth.kt')
        tcp = text.split('internal class TelefonTcpRoehre')[1].split('// RFCOMM')[0]
        self.assertIn('LanFreigabe.beobachten(socket)', tcp)
        bt = text.split('private class BluetoothRoehre')[1].split('internal object TelefonTransportwahl')[0]
        self.assertNotIn('LanFreigabe', bt)
        self.assertNotIn('lanWache', bt)
    def test_remote_address_pinned_and_local_checked(self):
        text = read('baum/Transport.kt').split('class WlanTransport')[1].split('class BluetoothTransport')[0]
        self.assertIn('LanFreigabe.ziel(host)', text)
        self.assertIn('InetSocketAddress(ziel, port)', text)
        self.assertIn('if (lanMarke != null)', text)
    def test_wlan_registration_is_inside_cleanup_owner(self):
        text = read('baum/Transport.kt').split('class WlanTransport')[1].split('class BluetoothTransport')[0]
        start = text.index('var lanWache: AutoCloseable? = null')
        guarded = text.index('try {', start)
        self.assertLess(guarded, text.index('LanFreigabe.beobachten(verbindung)'))
        self.assertIn('finally {\n                        synchronized(sperre)', text)
    def test_invitation_checks_token_before_acquisition(self):
        text = read('telefon/TelefonEinladung.kt').split('internal class TelefonEinladungsEmpfang')[1]
        self.assertLess(text.index('LanFreigabe.marke()'), text.index('ServerSocket(0, 1)'))
        self.assertIn('catch (error: Exception) { runCatching { listener.close() }; throw error }', text)
    def test_live_bluetooth_is_not_marked_offline_by_lan_denial(self):
        text = read('telefon/TelefonWerk.kt').split('fun wifiChanged(available: Boolean)')[1].split('fun ', 1)[0]
        self.assertIn('(!nutzbar || System.nanoTime() < bluetoothFirstSessionUntil)) return', text)
        self.assertLess(text.index('(!nutzbar ||'), text.index('_state.value ='))
    def test_tcp_registration_failure_releases_socket(self):
        text = read('telefon/TelefonBluetooth.kt').split('internal class TelefonTcpRoehre')[1].split('// RFCOMM')[0]
        self.assertIn('catch (error: Exception) { runCatching { socket.close() }; throw error }', text)
        self.assertIn('try { lanWache.close() } finally { socket.close() }', text)
    def test_waiting_message_is_localized(self):
        files = list((ROOT / 'app/src/main/res').glob('values*/strings.xml'))
        self.assertEqual(len(files), 20)
        for file in files:
            values = ET.parse(file).getroot().findall("string[@name='lan_freigabe_wartet']")
            self.assertEqual(len(values), 1, str(file))
            self.assertTrue(values[0].text and values[0].text.strip(), str(file))
        self.assertIn('R.string.lan_freigabe_wartet', read('netz/LanFreigabe.kt'))

if __name__ == '__main__': unittest.main()
