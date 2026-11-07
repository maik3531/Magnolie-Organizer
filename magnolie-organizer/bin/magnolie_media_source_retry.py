"""Bounded private source retry journal (#411), not phone-row recovery rights.

Keep the original exchange untouched and freeze earlier retry states on append.
Fresh actual preparation/control/offer/accept/chunk evidence is mandatory; no
old sent bits, acceptance or Saved can be inherited. Existing phone duplicate
guards remain unchanged, so this is not an end-to-end resume handler.
"""
from hashlib import sha256
import copy
import secrets

from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError
from magnolie_file_accept_message import parse_acceptance
from magnolie_media_source_exchange import _NativeSourceExchange,NativeSourceExchangeObservation,_validate_exchange_body,_read_source_exchange
from magnolie_telefon import canonical,strict_json


def _decode_retry_head(jobs,key,job,nonce,ready_version,original_version,cipher):
    name=jobs._catalog._retry+job
    if type(cipher) is not bytes or not 29<=len(cipher)<=_NativeSourceRetryExchange.MAX_BYTES+28:
        raise TransferError('media_source_retry_invalid_head')
    plain=jobs._authority.protection.unseal(cipher,name);body=strict_json(plain)
    if (type(body) is not dict or set(body)!={'format','scope','database_key','job_id','original_exchange_version','attempts'}
            or type(body['format']) is not int or body['format']!=1 or body['scope']!=jobs._scope
            or body['database_key']!=list(key) or body['job_id']!=job or body['original_exchange_version']!=original_version
            or canonical(body)!=plain or type(body['attempts']) is not list
            or not 1<=len(body['attempts'])<=_NativeSourceRetryExchange.MAX_ATTEMPTS):raise TransferError('media_source_retry_invalid_head')
    ids=set()
    for index,attempt in enumerate(body['attempts']):
        if (type(attempt) is not dict or set(attempt)!={'id','previous_head','record'} or type(attempt['id']) is not str
                or len(attempt['id'])!=32 or not _hex(attempt['id']*2) or attempt['id'] in ids
                or (attempt['previous_head'] is not None if index==0 else not _hex(attempt['previous_head']))):
            raise TransferError('media_source_retry_invalid_head')
        ids.add(attempt['id']);_validate_exchange_body(attempt['record'],key,jobs._scope,job,nonce,ready_version,allow_readback=True)
        if attempt['record']['format']==3 and (index==0 or body['attempts'][index-1]['record']['phase'] not in ('peer_saved','peer_readback')):
            raise TransferError('media_source_verification_completed_retry_required')
        if index:
            previous=body['attempts'][index-1]['record']
            if (previous['phase'] in ('peer_saved','peer_readback') and attempt['record']['format']!=3
                    or previous.get('purpose')=='published_verification' and previous['phase']!='peer_readback'):
                raise TransferError('media_source_retry_completed_held')
        if len(canonical(attempt['record']))>_NativeSourceExchange.MAX_BYTES:raise TransferError('media_source_retry_invalid_head')
    return NativeSourceExchangeObservation(sha256(cipher).hexdigest(),body)


def _read_retry_history(jobs,db,key,job,ready,original_version):
    """Authenticated metadata witness only, never current wire/READ authority."""
    original=_read_source_exchange(jobs,db,key,job,ready)
    if original is None or original.version!=original_version or original.body['phase']=='peer_saved':
        raise TransferError('media_source_retry_original_exchange_required')
    row=db.execute('SELECT value FROM meta WHERE key=?',(jobs._catalog._retry+job,)).fetchone()
    if row is None:return None
    return _decode_retry_head(jobs,key,job,ready.body['nonce'],ready.version,original_version,row[0])


class _NativeSourceRetryExchange(_NativeSourceExchange):
    MAX_BYTES=262144
    MAX_ATTEMPTS=8
    def __init__(self,sender,original,original_version,previous_version):
        super().__init__(sender)
        self._original=original;self._original_version=original_version
        self._key=self._jobs._catalog._retry+sender._job
        self._active_version=previous_version;self._attempt=secrets.token_hex(16)
        self.require_owner()

    def _validate(self,body,key):
        _validate_exchange_body(body,key,self._jobs._scope,self._sender._job,self._sender._cache._job_nonce,
            self._sender._cache._job_version,allow_readback=True)

    def _head(self,db,key):
        original=self._original._read(db,key)
        if original is None or original.version!=self._original_version:
            raise TransferError('media_source_retry_original_exchange_required')
        if original.body['phase']=='peer_saved':raise TransferError('media_source_retry_completed_held')
        row=db.execute('SELECT value FROM meta WHERE key=?',(self._key,)).fetchone()
        if row is None:return None
        return _decode_retry_head(self._jobs,key,self._sender._job,self._sender._cache._job_nonce,
            self._sender._cache._job_version,self._original_version,row[0])

    def require_owner(self):
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');self._jobs._catalog.verify(db,key);head=self._head(db,key)
            if (None if head is None else head.version)!=self._active_version:
                raise TransferError('media_source_retry_head_changed')
            if head is None or head.body['attempts'][-1]['id']!=self._attempt:
                completed=head is not None and head.body['attempts'][-1]['record']['phase'] in ('peer_saved','peer_readback')
                if self._sender._verification:
                    if not completed:raise TransferError('media_source_verification_completed_retry_required')
                    from magnolie_media_source_retirement import verify_retirement_exchange
                    ready=self._jobs._read(db,key,self._sender._job)
                    verify_retirement_exchange(self._jobs,db,key,ready,dict(format=2,job_id=self._sender._job,
                        exchange_version=self._original_version,retry_version=head.version,retry_attempt_id=head.body['attempts'][-1]['id']))
                elif completed or head is not None and head.body['attempts'][-1]['record'].get('purpose')=='published_verification':
                    raise TransferError('media_source_retry_completed_held')
            if db.execute('SELECT 1 FROM meta WHERE key=?',(self._jobs._catalog._retirement+self._sender._job,)).fetchone():
                from magnolie_media_source_retirement import _NativeSourceRetirement,_NativeSourceRetirementJournal
                owner=getattr(self._sender._active,'retirement',None)
                record=_NativeSourceRetirementJournal(self._jobs)._read(db,key,self._sender._job)
                if type(owner) is not _NativeSourceRetirement or owner._sender is not self._sender or not owner._permits_retry_record(record):
                    raise TransferError('media_source_retry_retirement_held')

    def history(self):
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');catalog=self._jobs._catalog.verify(db,key);head=self._head(db,key)
        self._jobs._catalog.observe(catalog);return head

    def lookup(self):
        head=self.history()
        if head is None or head.body['attempts'][-1]['id']!=self._attempt:return None
        return NativeSourceExchangeObservation(head.version,head.body['attempts'][-1]['record'])

    def require_new_acceptance(self,accepted):
        # Chunk requests bind acceptance hash/token, not offer_id. A fresh offer
        # must not turn old live requests into requests for this new attempt.
        self.require_owner()
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');self._jobs._catalog.verify(db,key);head=self._head(db,key)
            if head is None or head.version!=self._active_version or head.body['attempts'][-1]['id']!=self._attempt:
                raise TransferError('media_source_retry_original_attempt_required')
            previous=[self._original._read(db,key).body]
            previous.extend(attempt['record'] for attempt in head.body['attempts'][:-1])
            for record in previous:
                message=record['acceptance']
                if message is None:continue
                old=parse_acceptance(message,now=message['created_ms'])
                if accepted.acceptance_sha256==old.acceptance_sha256 or accepted.destination_token==old.destination_token:
                    raise TransferError('media_source_retry_acceptance_reused')

    def write(self,expected,body):
        self._sender._lease_current()
        with self._jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=self._jobs._catalog.verify(db,key);head=self._head(db,key)
            if (None if head is None else head.version)!=self._active_version:raise TransferError('media_source_retry_head_changed')
            attempts=[] if head is None else head.body['attempts'];body=copy.deepcopy(body)
            if expected is None:
                if len(attempts)>=self.MAX_ATTEMPTS:raise TransferError('media_source_retry_capacity')
                if any(value['id']==self._attempt for value in attempts):raise TransferError('media_source_retry_original_attempt_required')
                body.update(format=1,database_key=list(key),scope=self._jobs._scope,job_id=self._sender._job,
                    nonce=self._sender._cache._job_nonce,ready_version=self._sender._cache._job_version)
                if self._sender._verification:body.update(format=3,purpose='published_verification',peer_readback=None)
                if (body['phase']!='offer_planned' or body['acceptance'] is not None or body['sent_bits']!=0
                        or body['pending_chunk'] is not None or body['peer_saved'] is not None):
                    raise TransferError('media_source_retry_empty_attempt_required')
                attempts.append(dict(id=self._attempt,previous_head=self._active_version,record=body))
            else:
                if head is None or head.version!=expected.version or attempts[-1]['id']!=self._attempt:
                    raise TransferError('media_source_retry_original_attempt_required')
                before=attempts[-1]['record']
                if self._sender._verification and (before.get('purpose')!='published_verification' or body.get('purpose')!=before['purpose']):
                    raise TransferError('media_source_verification_readback_only')
                for name in ('database_key','scope','job_id','nonce','ready_version','offer','permission_epoch'):
                    if body.get(name)!=before[name]:raise TransferError('media_source_retry_original_attempt_required')
                readback=(before['format']==1 and body.get('format')==2 and before['phase']=='offer_sent' and body.get('phase')=='peer_readback')
                if body.get('format')!=before['format'] and not readback:raise TransferError('media_source_retry_original_attempt_required')
                allowed={'offer_planned':{'offer_sent'},'offer_sent':{'accepted','peer_readback'},'accepted':{'accepted','peer_saved'},'peer_saved':set(),'peer_readback':set()}
                if body.get('phase') not in allowed[before['phase']]:raise TransferError('media_source_exchange_invalid_transition')
                if before['acceptance'] is not None and body.get('acceptance')!=before['acceptance']:
                    raise TransferError('media_source_retry_original_attempt_required')
                attempts[-1]['record']=body
            self._validate(body,key)
            if len(canonical(body))>_NativeSourceExchange.MAX_BYTES:raise TransferError('media_source_exchange_record_size')
            value=dict(format=1,scope=self._jobs._scope,database_key=list(key),job_id=self._sender._job,
                original_exchange_version=self._original_version,attempts=attempts)
            plain=canonical(value)
            if len(plain)>self.MAX_BYTES:raise TransferError('media_source_retry_record_size')
            cipher=self._sender._authority.protection.seal(plain,self._key)
            self._sender._lease_current()
            db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(self._key,cipher))
            self._head(db,key);self._jobs._catalog.advance(db,key,catalog)
            self._sender._lease_current()
        # Actual commit precedes publishing native ownership of this head. The
        # original live cache/book OS lane remains held through independent readback.
        self._active_version=sha256(cipher).hexdigest();self._sender._lease_current()
        result=self.lookup()
        if result is None or result.version!=self._active_version:raise TransferError('media_source_retry_readback_failed')
        return result
