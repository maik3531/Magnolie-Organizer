#!/usr/bin/env python3
"""Production encrypted developer reads; loopback and synthetic established keys only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import sys
import tempfile
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone

PHONE = '22222222-2222-4222-8222-222222222222'


def main():
    with tempfile.TemporaryDirectory(prefix='developer-read-host-') as directory:
        service = phone.PhoneService(str(Path(directory) / 'phone'), 'Synthetic desktop')
        service.enabled = True
        peer = {'device_id': PHONE, 'display_name': 'Synthetic phone', 'static_public': phone.b64(b'p' * 32),
            'state': 'paired', 'grants': phone.desktop_grants(), 'local_grants': phone.desktop_grants(),
            'capabilities': phone.desktop_capabilities(), 'last_contact_ms': 0,
            'personal_sync': {'own_device': True, 'remote_own_device': False, 'auto_wifi': False, 'last_report': {}}}
        service.store.peers.append(peer)
        service.store.save_peers()
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as workers:
            listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(25)
            print(listener.getsockname()[1], flush=True)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                channel = phone.SecureChannel(connection, bytes([7]) * 32,
                    bytes([13]) * 32, bytes([14]) * 4, bytes([11]) * 32, bytes([12]) * 4)
                service.connections[PHONE] = channel; service.connection_transports[PHONE] = 'wifi'
                assert service._developer_peer(PHONE) is None
                service._ensure_desktop_updates(PHONE)
                for message in service.store.pending(PHONE):
                    service._send_message(channel, PHONE, message)

                def reads():
                    report = service.read_developer_diagnostics(PHONE)
                    assert report['format'] == 1 and report['app_version']
                    assert report['events'][-1]['stage'] == 'online'
                    assert len(report['events']) <= 128
                    assert report['version'] == 13 and report['crash_report']['available'] is True
                    assert 'Synthetic first-focus crash' in report['crash_report']['text']
                    # Notes independently revokes developer mode, WLAN transport, then own-device consent.
                    for scenario in ('fresh_controls_missing', 'disabled', 'bluetooth', 'own_revoked'):
                        try:
                            service.read_developer_diagnostics(PHONE)
                        except PermissionError as error:
                            assert 'not_granted' in str(error), (scenario, error)
                        else:
                            raise AssertionError('Notes released developer report: ' + scenario)
                    assert not service.developer_requests and not service.store.status(PHONE)

                operation = None
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try:
                        service._payload(peer, channel, channel.receive())
                    except socket.timeout:
                        pass
                    except Exception:
                        # Report immediately, before executor cleanup waits for its bounded reader.
                        traceback.print_exc(file=sys.stderr)
                        raise
                    if operation is None and service._developer_peer(PHONE):
                        operation = workers.submit(reads)
                    for message in service.store.pending(PHONE):
                        service._send_message(channel, PHONE, message)
                    if operation is not None and operation.done():
                        operation.result()
                        channel.send({'type': 'close', 'reason': 'normal'})
                        connection.settimeout(5)
                        while True:
                            packet = channel.receive()
                            if packet.get('type') == 'close':
                                break
                            service._payload(peer, channel, packet)
                        connection.shutdown(socket.SHUT_WR)
                        print('Python/Notes encrypted developer read and Notes disabled/BT/own revocation: PASS', flush=True)
                        return
                raise TimeoutError('developer fixture did not finish')


if __name__ == '__main__':
    main()
