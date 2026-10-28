"""KDE Connect systemvolume: native output sinks, separate from MPRIS players."""
import json
import math
import shutil
import subprocess
import threading

VOLUME_PACKET = 'kdeconnect.systemvolume'
VOLUME_REQUEST = 'kdeconnect.systemvolume.request'


def volume_request(body):
    if not isinstance(body, dict):
        raise ValueError('invalid_system_volume_request')
    if body == {'requestSinks': True} and type(body.get('requestSinks')) is bool:
        return None, {}
    if (not set(body) <= {'name', 'volume', 'muted', 'enabled'} or
            not isinstance(body.get('name'), str) or not 1 <= len(body['name']) <= 512 or
            any(ord(char) < 32 for char in body['name']) or len(body) < 2):
        raise ValueError('invalid_system_volume_request')
    if 'volume' in body and (type(body['volume']) is not int or not 0 <= body['volume'] <= 100):
        raise ValueError('invalid_system_volume_request')
    if any(key in body and type(body[key]) is not bool for key in ('muted', 'enabled')):
        raise ValueError('invalid_system_volume_request')
    return body['name'], {key: value for key, value in body.items() if key != 'name'}


class DesktopVolume:
    def __init__(self, executable, run=subprocess.run, environment=None):
        self.executable = executable
        self.run = run
        self.environment = environment
        self.lock = threading.RLock()

    @classmethod
    def create(cls):
        executable = shutil.which('pactl')
        if not executable:
            return None
        try:
            result = cls(executable)
            result.snapshot()
            return result
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _command(self, *arguments):
        result = self.run([self.executable, *arguments], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1.5,
            check=True, env=self.environment)
        if len(result.stdout) > 1024 * 1024:
            raise ValueError('system_volume_response_too_large')
        return result.stdout

    def _outputs(self):
        sinks = json.loads(self._command('--format=json', 'list', 'sinks'))
        default = self._command('get-default-sink').decode('utf-8').strip()
        if not isinstance(sinks, list) or len(sinks) > 128:
            raise ValueError('invalid_system_volume_response')
        result = []
        for sink in sinks:
            if not isinstance(sink, dict):
                continue
            name, index = sink.get('name'), sink.get('index')
            if (not isinstance(name, str) or not 1 <= len(name) <= 512 or
                    any(ord(char) < 32 for char in name) or type(index) is not int or not 0 <= index <= 2**31 - 1 or
                    type(sink.get('mute')) is not bool or not isinstance(sink.get('volume'), dict)):
                continue
            channels = [value.get('value') for value in sink['volume'].values() if isinstance(value, dict)]
            if not channels or any(type(value) is not int or not 0 <= value <= 65536 * 16 for value in channels):
                continue
            description = sink.get('description')
            if not isinstance(description, str) or not description or len(description) > 512:
                description = name
            result.append((index, {'name': name, 'description': description,
                'volume': math.floor(max(channels) * 100 / 65536 + .5), 'maxVolume': 100,
                'muted': sink['mute'], 'enabled': name == default}, tuple(channels)))
        return result

    def snapshot(self):
        with self.lock:
            return {'sinkList': [sink for _, sink, _ in self._outputs()]}

    def receive(self, body, permitted=lambda: True):
        name, actions = volume_request(body)
        with self.lock:
            if not permitted():
                raise ValueError('system_volume_source_changed')
            outputs = self._outputs()
            if name is None:
                return [{'sinkList': [sink for _, sink, _ in outputs]}]
            matches = [(index, sink) for index, sink, _ in outputs if sink['name'] == name]
            if len(matches) != 1:
                raise ValueError('system_volume_output_unavailable')
            index = matches[0][0]
            def change(command, value):
                if not permitted():
                    raise ValueError('system_volume_source_changed')
                current = [channels for native_id, sink, channels in self._outputs()
                    if native_id == index and sink['name'] == name]
                if len(current) != 1 or not permitted():
                    raise ValueError('system_volume_source_changed')
                if command == 'set-sink-volume':
                    channels = current[0]
                    maximum = max(channels)
                    target = round(value * 65536 / 100)
                    # Scale the channel vector instead of resetting a user's left/right balance.
                    values = [str(round(channel * target / maximum) if maximum else target) for channel in channels]
                elif command == 'set-default-sink':
                    values = []
                else:
                    values = [value]
                self._command(command, str(index), *values)
            if 'volume' in actions:
                change('set-sink-volume', actions['volume'])
                # Match KDE's systemvolume behaviour: an explicit volume action unmutes the output.
                change('set-sink-mute', '0')
            if 'muted' in actions:
                change('set-sink-mute', '1' if actions['muted'] else '0')
            if actions.get('enabled') is True:
                change('set-default-sink', None)
            if not permitted():
                raise ValueError('system_volume_source_changed')
            # Report the actual native state, not the requested value or mere command acceptance.
            return [self.snapshot()]
