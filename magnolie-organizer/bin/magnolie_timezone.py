"""Optional location-source selection; calendar arithmetic stays in the existing engines."""
import json
import math
import os
import re
import time
import uuid
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


IP_URL = 'https://ipapi.co/json/'
PHONE_VERSION = 12


def zone_id(value, system=False):
    if not isinstance(value, str) or len(value) > 128:
        return None
    value = value.strip()
    if system and value == 'system':
        return value
    if value in ('GMT', 'Etc/UTC', 'Etc/GMT', 'Z'):
        value = 'UTC'
    if value != 'UTC' and (not re.fullmatch(r'[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+', value) or '..' in value):
        return None
    try:
        ZoneInfo(value)
        return value
    except (ValueError, KeyError):
        return None


def phone_request(request_id):
    try:
        value = uuid.UUID(request_id)
        if value.version != 4 or str(value) != request_id:
            raise ValueError('invalid_time_zone_request')
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('invalid_time_zone_request') from error
    return {'version': PHONE_VERSION, 'request_id': request_id}


def validate_phone_report(value):
    if not isinstance(value, dict) or set(value) != {'version', 'request_id', 'state', 'time_zone', 'captured_ms'}:
        raise ValueError('invalid_time_zone_status')
    phone_request(value['request_id'])
    if type(value['version']) is not int or value['version'] != PHONE_VERSION or type(value['captured_ms']) is not int or not 0 <= value['captured_ms'] <= 253402300799999:
        raise ValueError('invalid_time_zone_status')
    zone = value['time_zone']
    if value['state'] == 'unavailable' and zone == '':
        return value
    if value['state'] != 'available' or not isinstance(zone, str) or zone != zone.strip() or zone_id(zone) is None:
        raise ValueError('invalid_time_zone_status')
    return value


def system_zone():
    environment = str(os.environ.get('TZ') or '').lstrip(':')
    if zone_id(environment):
        return environment
    candidates = []
    try:
        with open('/etc/timezone', encoding='utf-8') as source:
            candidates.append(source.read(256).strip())
    except OSError:
        pass
    path = os.path.realpath('/etc/localtime')
    if '/zoneinfo/' in path:
        candidates.append(path.split('/zoneinfo/', 1)[1])
    for candidate in candidates:
        if zone_id(candidate):
            return candidate
    return None


def detect(settings, sources, now=None):
    """Never invokes a sensor/network/phone source unless automatic mode is enabled."""
    now = int(time.time() * 1000) if now is None else now
    mode = settings.get('timeZoneManagement', 'off')
    manual = zone_id(settings.get('timeZoneManual', settings.get('timeZone', 'system')), system=True)
    if mode != 'automatic':
        zone = zone_id(settings.get('timeZone', 'system'), system=True) if mode == 'off' else manual
        return {'zone': zone or 'system', 'source': 'manual', 'captured_ms': now, 'fallback': False, 'automatic': False}
    if manual is None:
        raise ValueError('invalid_time_zone')
    preference = settings.get('timeZoneDetection', 'auto')
    order = ('phone', 'gps', 'ip', 'system') if preference == 'auto' else (preference,)
    for name in order:
        if name not in ('phone', 'gps', 'ip', 'system') or not callable(sources.get(name)):
            continue
        try:
            value = sources[name]()
            captured = value.get('captured_ms', now) if isinstance(value, dict) else now
            if type(captured) is not int or not now - 300000 <= captured <= now + 30000:
                continue
            zone = zone_id(value.get('zone') if isinstance(value, dict) else value, system=name == 'system')
            if zone:
                return {'zone': zone, 'source': name, 'captured_ms': captured, 'fallback': False, 'automatic': True}
        except Exception:
            # Optional sources may be absent, denied, offline or temporarily busy.
            continue
    if manual == 'system' and callable(sources.get('system')):
        try:
            value = sources['system']()
            zone = zone_id(value.get('zone') if isinstance(value, dict) else value, system=True)
            if zone:
                return {'zone': zone, 'source': 'system', 'captured_ms': now, 'fallback': True, 'automatic': True}
        except Exception:
            pass
    return {'zone': manual, 'source': 'manual', 'captured_ms': now, 'fallback': True, 'automatic': True}


def from_ip(fetch):
    data = json.loads(fetch(IP_URL))
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('timezone_source_unavailable')
    return {'zone': zone_id(data.get('timezone'))}


def from_coordinates(point, fetch, now=None):
    if not isinstance(point, dict):
        raise ValueError('timezone_source_unavailable')
    latitude, longitude = point.get('latitude'), point.get('longitude')
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float) or
            not math.isfinite(latitude) or not math.isfinite(longitude) or
            not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('invalid_timezone_location')
    now = int(time.time() * 1000) if now is None else now
    captured = point.get('captured_ms', now)
    if type(captured) is not int or not now - 300000 <= captured <= now + 30000:
        raise ValueError('stale_timezone_location')
    url = 'https://api.open-meteo.com/v1/forecast?' + urlencode({
        'latitude': latitude, 'longitude': longitude, 'current': 'temperature_2m',
        'forecast_days': 1, 'timezone': 'auto'})
    data = json.loads(fetch(url))
    if not isinstance(data, dict):
        raise ValueError('timezone_source_unavailable')
    return {'zone': zone_id(data.get('timezone')), 'captured_ms': captured}


def geoclue_location(bus=None, timeout=3):
    """Read one bounded GeoClue fix; release the temporary client on every exit."""
    from gi.repository import Gio, GLib
    bus = bus or Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    deadline = time.monotonic() + timeout
    client = None
    def call(path, interface, method, signature=None, args=(), reply=None):
        remaining = max(1, int((deadline - time.monotonic()) * 1000))
        if time.monotonic() >= deadline:
            raise TimeoutError('timezone_location_timeout')
        return bus.call_sync('org.freedesktop.GeoClue2', path, interface, method,
            GLib.Variant(signature, args) if signature else None,
            GLib.VariantType.new(reply) if reply else None, Gio.DBusCallFlags.NONE,
            remaining, None).unpack()
    try:
        client = call('/org/freedesktop/GeoClue2/Manager', 'org.freedesktop.GeoClue2.Manager', 'GetClient', reply='(o)')[0]
        if not isinstance(client, str) or not client.startswith('/org/freedesktop/GeoClue2/Client/'):
            raise ValueError('invalid_timezone_location')
        for name, value in [('DesktopId', GLib.Variant('s', 'magnolie-organizer')), ('RequestedAccuracyLevel', GLib.Variant('u', 6))]:
            call(client, 'org.freedesktop.DBus.Properties', 'Set', '(ssv)', ('org.freedesktop.GeoClue2.Client', name, value), '()')
        call(client, 'org.freedesktop.GeoClue2.Client', 'Start', reply='()')
        while time.monotonic() < deadline:
            location = call(client, 'org.freedesktop.DBus.Properties', 'Get', '(ss)', ('org.freedesktop.GeoClue2.Client', 'Location'), '(v)')[0]
            if isinstance(location, str) and location.startswith('/org/freedesktop/GeoClue2/Location/'):
                fields = call(location, 'org.freedesktop.DBus.Properties', 'GetAll', '(s)', ('org.freedesktop.GeoClue2.Location',), '(a{sv})')[0]
                stamp = fields.get('Timestamp', ())
                captured = int(stamp[0] * 1000 + stamp[1] / 1000) if isinstance(stamp, (tuple, list)) and len(stamp) == 2 else 0
                if captured > 0:
                    return {'latitude': fields.get('Latitude'), 'longitude': fields.get('Longitude'), 'captured_ms': captured}
            time.sleep(min(.05, max(0, deadline - time.monotonic())))
        raise TimeoutError('timezone_location_timeout')
    finally:
        if client:
            try:
                bus.call_sync('org.freedesktop.GeoClue2', client, 'org.freedesktop.GeoClue2.Client', 'Stop', None, None,
                    Gio.DBusCallFlags.NO_AUTO_START, 300, None)
            except Exception:
                pass
