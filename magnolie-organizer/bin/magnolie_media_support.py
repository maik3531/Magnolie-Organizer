"""One ephemeral shared-settings support attempt on an authenticated WLAN parent.

This is not a dispatcher, a capability advertisement, settings agreement, or
file authority. The caller must bind `current` to the original native WLAN
owner and its acknowledged own-device metadata, and feed only decoded frames
from that parent. `current` is an in-memory, lock-free deny-only witness.
"""
import threading
import time
import uuid

from magnolie_telefon import SecureChannel, now_ms, valid_uuid


KIND = 'media_support.hello'
TTL = 10_000
_FIELDS = {'type', 'v', 'message_id', 'kind', 'created_ms', 'expires_ms', 'body'}


def offer(at):
    return dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=KIND,
                created_ms=at, expires_ms=at+TTL, body=dict(format=1, feature='shared_settings'))


def ack(message):
    return dict(type='ack', message_id=message['message_id'], status='accepted', error='none')


def valid(message, at):
    if type(message) is not dict or set(message) != _FIELDS:return False
    body = message['body']
    return (message['type']=='message' and type(message['v']) is int and message['v']==1
            and message['kind']==KIND and valid_uuid(message['message_id'],4)
            and type(message['created_ms']) is int and type(message['expires_ms']) is int
            and 0<=message['created_ms']<=at<message['expires_ms']<=253402300799999
            and message['expires_ms']-message['created_ms']<=TTL
            and type(body) is dict and set(body)=={'format','feature'}
            and type(body['format']) is int and body['format']==1 and body['feature']=='shared_settings')


class NativeMediaSupportAttempt:
    def __init__(self, channel, current, wall=now_ms, monotonic_ms=lambda:time.monotonic_ns()//1_000_000):
        if type(channel) is not SecureChannel or not callable(current):
            raise ValueError('native media support needs its secure parent')
        self._channel, self._current, self._wall, self._clock = channel, current, wall, monotonic_ms
        self._issued = monotonic_ms()
        self._lock = threading.Lock()
        self._retired = threading.Event()
        self._sent = self._written = self._local_ack = self._remote_ack = self._established = False
        self._remote_claimed = False
        self._offer = offer(wall())

    def close(self):
        self._retired.set()  # Never close or replace the shared socket.

    def _live(self, channel):
        if channel is not self._channel or self._retired.is_set():return False
        tick = self._clock()
        if (self._current() is not True or tick<self._issued
                or not self._established and tick-self._issued>=TTL):
            self.close()
        return not self._retired.is_set()

    def supports(self, channel):
        return self._live(channel) and self._established and not self._retired.is_set()

    def owns_ack(self, channel, message):
        """Retain receipt ownership even after retirement, never the outbox."""
        return (channel is self._channel and self._sent and message.get('type')=='ack'
                and message.get('message_id')==self._offer['message_id'])

    def _write(self, message):
        # The original channel calls this inside its writer gate. Do not take
        # the attempt lock or do any disk/remote work from the validation hook.
        def current():
            if not self._live(self._channel):raise PermissionError('media support attempt retired')
        try:
            self._channel.send_ephemeral(message, current)
            return True
        except (OSError, ValueError):
            self.close()
            return False

    def _publish_locked(self):
        if self._written and self._local_ack and self._remote_ack and self._live(self._channel):
            self._established = True

    def send(self):
        with self._lock:
            if self._sent or not self._live(self._channel):return False
            self._sent = True
        if not self._write(self._offer):return False
        with self._lock:
            self._written = self._live(self._channel)
            self._publish_locked()
            return self._written

    def receive(self, channel, message):
        with self._lock:
            if type(message) is not dict or not self._live(channel) or self._established:return False
            if message.get('type')=='ack':
                if not self._sent or self._local_ack or message.get('message_id')!=self._offer['message_id']:return False
                if message!=ack(self._offer):
                    self.close()
                    return False
                self._local_ack = True
                self._publish_locked()
                return True
            if self._remote_claimed or not valid(message, self._wall()) or message['message_id']==self._offer['message_id']:
                return False
            self._remote_claimed = True
        if not self._write(ack(message)):return False
        with self._lock:
            self._remote_ack = self._live(channel)
            self._publish_locked()
            return self._remote_ack
