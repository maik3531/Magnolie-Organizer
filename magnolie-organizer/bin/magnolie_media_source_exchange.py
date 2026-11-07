"""Protected source-side wire-attempt history (#400); never Saved/READ rights.

Separate from the immutable cache-ready journal. There is no restart adoption,
retirement or repair. Only the actual live private sender advances an attempt.
"""
from dataclasses import dataclass
from hashlib import sha256
import copy

from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical,strict_json


@dataclass(frozen=True)
class NativeSourceExchangeObservation:
    version: str
    _body: dict
    @property
    def body(self):return copy.deepcopy(self._body)
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False
    @property
    def permits_retirement(self):return False


class _NativeSourceExchange:
    MAX_BYTES=16384
    PHASES=frozenset(('offer_planned','offer_sent','accepted','peer_saved'))
    def __init__(self,sender):
        from magnolie_media_source_sender import _NativeMediaSourceSender
        if type(sender) is not _NativeMediaSourceSender:raise TransferError('media_source_exchange_native_sender_required')
        self._sender=sender;self._jobs=sender._jobs
        self._key='native_media_source_exchange_v1/'+self._jobs._scope+'/'+sender._job

    def _decode(self,cipher,key):
        if type(cipher) is not bytes or not 29<=len(cipher)<=self.MAX_BYTES+28:
            raise TransferError('media_source_exchange_invalid_record')
        plain=self._sender._authority.protection.unseal(cipher,self._key);body=strict_json(plain)
        if (type(body) is not dict or set(body)!={'format','database_key','scope','job_id','nonce','ready_version',
                'phase','offer','permission_epoch','acceptance','sent_bits','pending_chunk','peer_saved'}
                or type(body['format']) is not int or body['format']!=1 or body['database_key']!=list(key)
                or body['scope']!=self._jobs._scope or body['job_id']!=self._sender._job
                or body['nonce']!=self._sender._cache._job_nonce or body['ready_version']!=self._sender._cache._job_version
                or body['phase'] not in self.PHASES or canonical(body)!=plain):
            raise TransferError('media_source_exchange_invalid_record')
        return NativeSourceExchangeObservation(sha256(cipher).hexdigest(),body)

    def _read(self,db,key):
        row=db.execute('SELECT value FROM meta WHERE key=?',(self._key,)).fetchone()
        return self._decode(row[0],key) if row else None

    def lookup(self):
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');catalog=self._jobs._catalog.verify(db,key);result=self._read(db,key)
        self._jobs._catalog.observe(catalog);return result

    def require(self,expected):
        actual=self.lookup()
        if actual is None or actual.version!=expected.version:raise TransferError('media_source_exchange_changed')
        return actual

    def write(self,expected,body):
        self._sender._lease_current()
        with self._jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=self._jobs._catalog.verify(db,key);before=self._read(db,key)
            if (before is not None if expected is None else before is None or before.version!=expected.version):
                raise TransferError('media_source_exchange_original_attempt_required')
            body=copy.deepcopy(body)
            if expected is None:
                body.update(format=1,database_key=list(key),scope=self._jobs._scope,job_id=self._sender._job,
                    nonce=self._sender._cache._job_nonce,ready_version=self._sender._cache._job_version)
            else:
                for name in ('format','database_key','scope','job_id','nonce','ready_version','offer','permission_epoch'):
                    if body.get(name)!=before.body[name]:raise TransferError('media_source_exchange_original_attempt_required')
                allowed={'offer_planned':{'offer_sent'},'offer_sent':{'accepted'},'accepted':{'accepted','peer_saved'},'peer_saved':set()}
                if body.get('phase') not in allowed[before.body['phase']]:raise TransferError('media_source_exchange_invalid_transition')
                if before.body['acceptance'] is not None and body.get('acceptance')!=before.body['acceptance']:
                    raise TransferError('media_source_exchange_original_attempt_required')
            plain=canonical(body)
            if len(plain)>self.MAX_BYTES:raise TransferError('media_source_exchange_record_size')
            cipher=self._sender._authority.protection.seal(plain,self._key);self._decode(cipher,key)
            self._sender._lease_current()
            if expected is None:db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(self._key,cipher))
            else:db.execute('UPDATE meta SET value=? WHERE key=?',(cipher,self._key))
            self._jobs._catalog.advance(db,key,catalog)
            self._sender._lease_current()
        self._sender._lease_current();result=self.lookup()
        if result is None or result.version!=sha256(cipher).hexdigest():raise TransferError('media_source_exchange_readback_failed')
        return result
