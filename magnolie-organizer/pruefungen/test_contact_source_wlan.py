"""Manager-independent native kernel route/WLAN gate; no network packets."""
import errno
import io
import socket
import struct

import pytest

from test_startup_read_failure import native


@pytest.mark.parametrize('mode', ['wifi4', 'wifi6', 'wifi-both', 'different-wifi', 'ethernet',
    'mobile', 'tunnel', 'mixed-families', 'no-route', 'route-changed', 'route-failed', 'no-gi',
    'link-down', 'no-carrier', 'sysfs-missing', 'unsafe-interface'])
def test_native_egress_wlan_gate_does_not_require_networkmanager_or_another_daemon(native, monkeypatch, mode):
    routes = ['wlan0', None]
    if mode == 'wifi6': routes = [None, 'wlan0']
    if mode == 'wifi-both': routes = ['wlan0', 'wlan0']
    if mode == 'different-wifi': routes = ['wlan0', 'wlan1']
    if mode in ('ethernet', 'mobile', 'tunnel'): routes = [{'ethernet': 'eth0', 'mobile': 'wwan0', 'tunnel': 'tun0'}[mode], None]
    if mode == 'mixed-families': routes = ['wlan0', 'eth0']
    if mode == 'no-route': routes = [None, None]
    if mode == 'unsafe-interface': routes = ['../private', None]
    calls = []
    def kernel(family):
        calls.append(family)
        if mode == 'route-failed': raise OSError('Controlled kernel observation failure')
        if mode == 'route-changed' and len(calls) > 2: return 'eth0'
        return routes[0 if family == socket.AF_INET else 1]
    monkeypatch.setattr(native, '_kontakt_quellen_kernel_route', kernel)
    # No Gio, GLib, D-Bus, network manager or external binary is required.
    monkeypatch.setattr(native, 'Gio', None)
    monkeypatch.setattr(native, 'GLib', None)
    actual_isdir, actual_exists = native.os.path.isdir, native.os.path.exists
    monkeypatch.setattr(native.os.path, 'isdir', lambda path:
        path in ('/sys/class/net/wlan0/wireless', '/sys/class/net/wlan1/wireless')
        if str(path).startswith('/sys/class/net/') else actual_isdir(path))
    monkeypatch.setattr(native.os.path, 'exists', lambda path:
        False if str(path).startswith('/sys/class/net/') else actual_exists(path))
    def read_link(path, **kwargs):
        assert str(path).startswith('/sys/class/net/wlan') and kwargs['encoding'] == 'ascii'
        if mode == 'sysfs-missing': raise OSError('Controlled absent native link properties')
        if path.endswith('/operstate'): return io.StringIO('down' if mode == 'link-down' else 'up')
        assert path.endswith('/carrier')
        return io.StringIO('0' if mode == 'no-carrier' else '1')
    monkeypatch.setattr(native, 'open', read_link, raising=False)
    assert native.kontakt_quellen_wlan_verfuegbar() is (mode in (
        'wifi4', 'wifi6', 'wifi-both', 'different-wifi', 'no-gi'))
    assert len(calls) <= 4


@pytest.mark.parametrize('mode', ['ipv4', 'ipv6', 'no-route', 'permission', 'timeout', 'bad-sequence',
    'bad-sender', 'bad-type', 'bad-family', 'non-unicast', 'short-header', 'truncated', 'bad-attribute',
    'missing-interface', 'duplicate-interface', 'unknown-interface', 'interrupted'])
def test_actual_route_request_and_strict_reply_parser_only_talk_to_local_kernel(native, monkeypatch, mode):
    family = socket.AF_INET6 if mode == 'ipv6' else socket.AF_INET
    requests = []
    class Channel:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def settimeout(self, value): assert value == 0.5
        def bind(self, address): assert address == (0, 0)
        def sendto(self, request, address):
            assert address == (0, 0), 'Route lookup sent outside local kernel'
            size, kind, flags, sequence, pid = struct.unpack_from('=IHHII', request)
            assert size == len(request) and kind == 26 and flags == 1 and pid == 0
            assert request[16] == family
            attribute_size, attribute_kind = struct.unpack_from('=HH', request, 28)
            assert attribute_kind == 1 and attribute_size == len(request) - 28
            assert request[32:] == socket.inet_pton(family, '2001:db8::1' if family == socket.AF_INET6 else '192.0.2.1')
            requests.append(request)
        def recvfrom(self, limit):
            assert limit == 8192 and len(requests) == 1
            if mode == 'timeout': raise TimeoutError('Controlled kernel lookup timeout')
            sequence = struct.unpack_from('=I', requests[0], 8)[0]
            if mode == 'bad-sequence': sequence ^= 1
            sender = (42 if mode == 'bad-sender' else 0, 0)
            route = struct.pack('=BBBBBBBBI', socket.AF_INET6 if mode == 'bad-family' else family,
                                32, 0, 0, 254, 0, 0, 2 if mode == 'non-unicast' else 1, 0)
            attribute = struct.pack('=HHI', 8, 4, 7)
            if mode == 'missing-interface': attribute = b''
            if mode == 'duplicate-interface': attribute *= 2
            if mode == 'bad-attribute': attribute = struct.pack('=HHI', 2, 4, 7)
            body = route + attribute
            kind = 24
            if mode in ('no-route', 'permission'):
                kind, body = 2, struct.pack('=i', -(errno.ENETUNREACH if mode == 'no-route' else errno.EPERM))
            if mode == 'bad-type': kind = 99
            flags = 16 if mode == 'interrupted' else 0
            packet = struct.pack('=IHHII', 16 + len(body), kind, flags, sequence, 0) + body
            if mode == 'short-header': packet = packet[:8]
            if mode == 'truncated': packet = packet[:-1]
            return packet, sender
    def channel(domain, kind, protocol):
        assert (domain, kind, protocol) == (socket.AF_NETLINK, socket.SOCK_RAW, socket.NETLINK_ROUTE)
        return Channel()
    def interface(index):
        assert index == 7
        if mode == 'unknown-interface': raise OSError('Controlled removed interface')
        return 'wlan0'
    monkeypatch.setattr(socket, 'socket', channel)
    monkeypatch.setattr(socket, 'if_indextoname', interface)
    if mode in ('ipv4', 'ipv6', 'no-route'):
        assert native._kontakt_quellen_kernel_route(family) == (None if mode == 'no-route' else 'wlan0')
    else:
        with pytest.raises((OSError, ValueError)): native._kontakt_quellen_kernel_route(family)
    assert len(requests) == 1
