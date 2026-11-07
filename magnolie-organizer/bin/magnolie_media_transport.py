"""Exact native shared-media agreement (#338), not source/receive authority.

Construction starts no listener or worker. Production discovery remains closed.
Native dispatch must deliver only messages decrypted on this exact channel;
the runtime-ready callback is a lock-free local joined-backend observation.
"""
import copy
import threading
import uuid

import magnolie_media_sync as media
from magnolie_telefon import SecureChannel,canonical,now_ms,CLOCK_SKEW_MS


class NativeMediaIntent:
    """An exact in-process agreement witness; never a READ/write permission."""
    def __init__(self,body):
        self._body=copy.deepcopy(body);self._values=media.effective(body)

    @property
    def body(self):return copy.deepcopy(self._body)

    def requested_for(self,kind,*,to_phone=False):
        return media.requested_for(self._body,kind,to_phone=to_phone)


class NativeMediaSettingsTransport:
    MAX_TTL_MS=86400000
    MAX_MESSAGES=128

    def __init__(self,authority,runtime_ready,*,clock=now_ms):
        from magnolie_file_native_authority import NativeDesktopFileAuthority
        if (type(authority) is not NativeDesktopFileAuthority or not callable(runtime_ready) or not callable(clock)
                or type(authority.native_channel) is not SecureChannel):
            raise ValueError('native secure media transport required')
        self._store=media.NativeMediaSettingsStore(authority);self._authority=authority
        self._channel=authority.native_channel;self._ready=runtime_ready;self._clock=clock
        self._gate=threading.RLock();self._closed=threading.Event();self._withdrawn=threading.Event();self._generation=0
        self._sent=self._acknowledged=self._received=self._intent=None
        self._attempts={};self._received_ids={}

    def _fresh(self):
        if self._withdrawn.is_set():self._invalidate();self._withdrawn.clear()
        if self._closed.is_set() or self._ready() is not True:raise PermissionError('media_runtime_unavailable')
        self._store._fresh()

    def _invalidate(self):
        self._generation+=1;self._sent=self._acknowledged=self._received=self._intent=None;self._attempts.clear()

    def invalidate(self):
        with self._gate:self._invalidate()

    def close(self):
        self._closed.set();self._intent=None
        if self._gate.acquire(blocking=False):
            try:self._invalidate()
            finally:self._gate.release()
        # The shared secure socket belongs to its native connection, not us.

    def intent_for(self,kind,*,to_phone=False):
        # Safe in a protected source guard: no store/session/transport monitor.
        if self._closed.is_set() or self._authority._revoked.is_set() or self._ready() is not True:
            self._intent=None;self._withdrawn.set();return None
        token=self._intent
        return token if token is not None and token.requested_for(kind,to_phone=to_phone) else None

    def _publish(self):
        self._fresh();body=self._store.read()
        if body is None or not body==self._sent==self._acknowledged==self._received:
            self._intent=None
        elif self._intent is None or self._intent.body!=body:self._intent=NativeMediaIntent(body)

    def change(self,field,value):
        with self._gate:
            if self._closed.is_set():raise PermissionError('media_transport_closed')
            self._invalidate()
            return self._store.change(field,value)

    def send_settings(self):
        with self._gate:
            try:
                self._fresh();body=self._store.read()
                if body is None:self._invalidate();return None
                if body==self._sent:self._publish();return None
                self._intent=None
                at=self._clock()
                message=dict(type='message',v=1,message_id=str(uuid.uuid4()),kind=media.KIND,
                    created_ms=at,expires_ms=at+self.MAX_TTL_MS,body=copy.deepcopy(body))
                self._validate_message(message)
                generation=self._generation;self._attempts.clear();self._attempts[message['message_id']]=copy.deepcopy(body)
                self._channel.send(message) # Actual encrypted socket write, not a queued callback.
                self._fresh()
                if generation!=self._generation or self._store.read()!=body:
                    self._invalidate();return None
                self._sent=copy.deepcopy(body);self._publish();return message
            except BaseException:
                self._invalidate();raise

    def _validate_message(self,message):
        at=self._clock()
        if (type(at) is not int or not 0<=at<=253402300799999 or type(message) is not dict or set(message)!={'type','v','message_id','kind','created_ms','expires_ms','body'}
                or message['type']!='message' or type(message['v']) is not int or message['v']!=1 or message['kind']!=media.KIND
                or type(message['created_ms']) is not int or type(message['expires_ms']) is not int
                or not 0<=message['created_ms']<message['expires_ms']<=253402300799999
                or not 1<=message['expires_ms']-message['created_ms']<=self.MAX_TTL_MS
                or message['created_ms']>at+CLOCK_SKEW_MS or at>=message['expires_ms'] or len(canonical(message))>8192):
            raise ValueError('invalid media settings envelope')
        media.shared.actor(message['message_id']);media.validate(message['body'])

    def observe(self,channel,message):
        if channel is not self._channel:return False
        if type(message) is not dict:return False
        with self._gate:
            if message.get('type')=='ack':return self._ack(message)
            if message.get('type')!='message' or message.get('kind')!=media.KIND:return False
            try:
                self._fresh();self._validate_message(message);body=message['body'];identifier=message['message_id']
                previous=self._received_ids.get(identifier)
                if previous is not None and previous!=body:raise ValueError('media message equivocation')
                if previous is None and len(self._received_ids)>=self.MAX_MESSAGES:raise ValueError('media session capacity')
                if self._intent is not None and self._intent.body!=body:self._intent=None
                generation=self._generation;self._store.merge(body);self._fresh()
                self._channel.send(dict(type='ack',message_id=identifier,status='duplicate' if previous is not None else 'accepted',error='none'))
                self._fresh()
                if generation!=self._generation:self._invalidate();return True
                self._received_ids[identifier]=copy.deepcopy(body);self._received=copy.deepcopy(body)
                self.send_settings();self._publish();return True
            except BaseException:
                self._invalidate();raise

    def _ack(self,message):
        try:
            self._fresh()
            if (set(message)!={'type','message_id','status','error'} or message['status'] not in ('accepted','duplicate','rejected')
                    or type(message['error']) is not str):raise ValueError('invalid media settings acknowledgement')
            media.shared.actor(message['message_id'])
            attempted=self._attempts.pop(message['message_id'],None)
            if attempted is None:return False
            self._acknowledged=attempted if message['status'] in ('accepted','duplicate') and message['error']=='none' else None
            self._publish();return True
        except BaseException:
            self._invalidate();raise
