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


def _validate_exchange_body(body,key,scope,job,nonce,ready_version,*,allow_readback=False,manifest=None,predecessors=None):
    if type(body) is dict and type(body.get('format')) is int and body['format']==5:
        return _validate_batch_exchange(body,key,scope,job,nonce,ready_version,manifest,predecessors)
    media=type(body) is dict and body.get('format')==4
    readback=allow_readback and type(body) is dict and body.get('format')==2
    verification=allow_readback and type(body) is dict and body.get('format')==3
    extra={'purpose','peer_readback'} if verification else {'peer_readback'} if readback or media else set()
    if (type(body) is not dict or set(body)!={'format','database_key','scope','job_id','nonce','ready_version',
            'phase','offer','permission_epoch','acceptance','sent_bits','pending_chunk','peer_saved'} | extra
            or type(body['format']) is not int or body['format']!=(4 if media else 3 if verification else 2 if readback else 1) or body['database_key']!=list(key)
            or body['scope']!=scope or body['job_id']!=job or body['nonce']!=nonce or body['ready_version']!=ready_version
            or (body['phase'] not in _NativeSourceExchange.PHASES|{'peer_readback'} if media else
                body['phase'] not in ('offer_planned','offer_sent','peer_readback') if verification else
                body['phase']!='peer_readback' if readback else body['phase'] not in _NativeSourceExchange.PHASES)):
        raise TransferError('media_source_exchange_invalid_record')
    if media and (type(body['offer']) is not dict or body['offer'].get('kind')!='file_transfer.media_offer' or
            (type(body['peer_readback']) is not dict or type(body['peer_saved']) is not dict or type(body['acceptance']) is not dict or
             body['pending_chunk'] is not None or type(body['sent_bits']) is not int or body['sent_bits']<1
             if body['phase']=='peer_readback' else body['peer_readback'] is not None)):
        raise TransferError('media_source_exchange_invalid_record')
    if (readback or verification) and (body['acceptance'] is not None or type(body['sent_bits']) is not int or body['sent_bits']!=0
            or body['pending_chunk'] is not None or body['peer_saved'] is not None
            or (type(body['peer_readback']) is not dict if body['phase']=='peer_readback' else body['peer_readback'] is not None)
            or verification and body['purpose']!='published_verification'):
        raise TransferError('media_source_exchange_invalid_record')


def _read_source_exchange(jobs,db,key,job,ready):
    """Passive exact metadata only; never construct a sender or source reader."""
    name=jobs._catalog._exchange+job;row=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()
    if row is None:return None
    cipher=row[0]
    if type(cipher) is not bytes or not 29<=len(cipher)<=_NativeSourceExchange.BATCH_MAX_BYTES+28:
        raise TransferError('media_source_exchange_invalid_record')
    plain=jobs._authority.protection.unseal(cipher,name);body=strict_json(plain)
    batch=type(body) is dict and body.get('format')==5
    if not batch and len(cipher)>_NativeSourceExchange.MAX_BYTES+28:raise TransferError('media_source_exchange_invalid_record')
    if batch and ready.body['format']!=4:raise TransferError('media_source_exchange_invalid_record')
    from magnolie_file_transfer import FileManifest
    recovered = type(body) is dict and 'recovery' in body
    original = dict(body, phase='peer_saved', peer_readback=None) if recovered else body
    if recovered:
        del original['recovery']
    _validate_exchange_body(original,key,jobs._scope,job,ready.body['nonce'],ready.version,
        manifest=FileManifest.parse(ready.body['manifest']) if batch else None,
        predecessors=ready.body['predecessors'] if batch else None)
    if canonical(body)!=plain:raise TransferError('media_source_exchange_invalid_record')
    if recovered:
        from magnolie_media_saved_recovery_proof import verify_recovered_pc_exchange
        peer = jobs._authority.current_peer()
        if peer is None or ready.body.get('pairing_epoch') != peer.pairing_epoch:
            raise TransferError('media_source_recovery_original_pairing_required')
        verify_recovered_pc_exchange(body, ready.body, jobs._authority.identity.receiver_identity_sha256,
                                     peer.identity_sha256)
    return NativeSourceExchangeObservation(sha256(cipher).hexdigest(),body)


class _NativeSourceExchange:
    MAX_BYTES=16384
    BATCH_MAX_BYTES=262144
    PHASES=frozenset(('offer_planned','offer_sent','accepted','peer_saved'))
    def __init__(self,sender):
        from magnolie_media_source_sender import _NativeMediaSourceSender
        if type(sender) is not _NativeMediaSourceSender:raise TransferError('media_source_exchange_native_sender_required')
        self._sender=sender;self._jobs=sender._jobs
        self._key='native_media_source_exchange_v1/'+self._jobs._scope+'/'+sender._job

    def _decode(self,cipher,key):
        bound=self.BATCH_MAX_BYTES if self._sender._batch is not None else self.MAX_BYTES
        if type(cipher) is not bytes or not 29<=len(cipher)<=bound+28:
            raise TransferError('media_source_exchange_invalid_record')
        plain=self._sender._authority.protection.unseal(cipher,self._key);body=strict_json(plain)
        self._validate(body,key)
        if canonical(body)!=plain:raise TransferError('media_source_exchange_invalid_record')
        return NativeSourceExchangeObservation(sha256(cipher).hexdigest(),body)

    def _validate(self,body,key):
        batch=self._sender._batch is not None
        if batch != (type(body) is dict and body.get('format')==5):
            raise TransferError('media_source_exchange_invalid_record')
        _validate_exchange_body(body,key,self._jobs._scope,self._sender._job,self._sender._cache._job_nonce,self._sender._cache._job_version,
            manifest=self._sender._cache.manifest if batch else None,
            predecessors=self._sender._batch_predecessors() if batch and body.get('phase') in ('peer_saved','peer_readback') else None)

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
                if body['offer'].get('kind')=='file_transfer.media_offer':body.update(format=4,peer_readback=None)
                if self._sender._batch is not None:body.update(format=5,peer_readback=None)
            else:
                for name in ('format','database_key','scope','job_id','nonce','ready_version','offer','permission_epoch'):
                    if body.get(name)!=before.body[name]:raise TransferError('media_source_exchange_original_attempt_required')
                allowed={'offer_planned':{'offer_sent'},'offer_sent':{'accepted'},'accepted':{'accepted','peer_saved'},'peer_saved':set()}
                if before.body['format'] in (4,5):allowed['peer_saved']={'peer_readback'};allowed['peer_readback']=set()
                if body.get('phase') not in allowed[before.body['phase']]:raise TransferError('media_source_exchange_invalid_transition')
                if before.body['acceptance'] is not None and body.get('acceptance')!=before.body['acceptance']:
                    raise TransferError('media_source_exchange_original_attempt_required')
                if before.body['format']==5:
                    _batch_transition(before.body,body)
            plain=canonical(body)
            if len(plain)>(self.BATCH_MAX_BYTES if self._sender._batch is not None else self.MAX_BYTES):raise TransferError('media_source_exchange_record_size')
            cipher=self._sender._authority.protection.seal(plain,self._key);self._decode(cipher,key)
            self._sender._lease_current()
            if expected is None:db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(self._key,cipher))
            else:db.execute('UPDATE meta SET value=? WHERE key=?',(cipher,self._key))
            self._jobs._catalog.advance(db,key,catalog)
            self._sender._lease_current()
        self._sender._lease_current();result=self.lookup()
        if result is None or result.version!=sha256(cipher).hexdigest():raise TransferError('media_source_exchange_readback_failed')
        return result


def _batch_delivery_complete(media,bits,predecessors):
    """Zero output is allowed only for an exact unchanged native predecessor.

    Never synthesize sent bits. Historical full sends remain readable; partial
    output, changes and new members still require every original chunk.
    """
    from magnolie_file_control import _hex
    files=media.manifest.files
    ids={file.id for file in files}
    if type(bits) is not dict or set(bits)!=ids:return False
    for file in files:
        count=bits[file.id]
        if type(count) is not int:return False
        if count==(1<<file.chunks)-1:continue
        if count!=0 or not media.pc_batch or type(predecessors) is not dict or set(predecessors)!=ids:return False
        previous=predecessors[file.id]
        origin=media.pc_origins[file.id]
        if (type(previous) is not dict or not _hex(previous.get('publication_sha256'))
                or origin['previous_publication_sha256']!=previous['publication_sha256']
                or type(previous.get('size')) is not int or previous['size']!=file.size or previous.get('sha256')!=file.sha256):
            return False
    return True


def _validate_batch_exchange(body,key,scope,job,nonce,ready_version,manifest,predecessors):
    from magnolie_file_transfer import FileManifest
    from magnolie_file_control import _hex, MAX_TTL_MS
    from magnolie_media_offer import validate_media_offer
    from magnolie_file_accept_message import parse_acceptance
    from magnolie_file_saved_message import parse_saved
    from magnolie_telefon import valid_uuid
    if (type(manifest) is not FileManifest or set(body)!={'format','database_key','scope','job_id','nonce','ready_version',
            'phase','offer','permission_epoch','acceptance','sent_bits','pending_chunk','peer_saved','peer_readback'}
            or body['database_key']!=list(key) or body['scope']!=scope or body['job_id']!=job
            or body['nonce']!=nonce or body['ready_version']!=ready_version or not _hex(body['permission_epoch'])
            or body['phase'] not in _NativeSourceExchange.PHASES|{'peer_readback'}):
        raise TransferError('media_source_exchange_invalid_record')
    offer=body['offer']
    if type(offer) is not dict:raise TransferError('media_source_exchange_invalid_record')
    media=validate_media_offer(offer,manifest.sender_id,manifest.receiver_id,now=offer.get('created_ms'),allow_pc_batch=True)
    if media.manifest!=manifest:raise TransferError('media_source_exchange_invalid_record')
    bits=body['sent_bits'];files={f.id:f for f in manifest.files}
    if (type(bits) is not dict or set(bits)!=set(files)
            or any(type(v) is not int or not 0<=v<(1<<files[fid].chunks) for fid,v in bits.items())):
        raise TransferError('media_source_exchange_invalid_record')
    if body['phase'] in ('offer_planned','offer_sent'):
        if body['acceptance'] is not None or any(bits.values()) or any(body[k] is not None for k in ('pending_chunk','peer_saved','peer_readback')):
            raise TransferError('media_source_exchange_invalid_record')
        return
    accepted=body['acceptance']
    if type(accepted) is not dict:raise TransferError('media_source_exchange_invalid_record')
    parsed=parse_acceptance(accepted,now=accepted.get('created_ms'))
    if (parsed.offer_id!=offer['message_id'] or parsed.manifest_sha256!=manifest.fingerprint
            or parsed.transfer_id!=manifest.transfer_id or parsed.permission_epoch!=body['permission_epoch']
            or accepted['created_ms']<offer['created_ms'] or accepted['expires_ms']>offer['expires_ms']):
        raise TransferError('media_source_exchange_invalid_record')
    pending=body['pending_chunk']
    if pending is not None:
        if (body['phase']!='accepted' or type(pending) is not dict
                or set(pending)!={'request_id','request_sha256','file_id','chunk_index','response_sha256'}
                or not valid_uuid(pending['request_id'],version=4) or not _hex(pending['request_sha256']) or not _hex(pending['response_sha256'])
                or type(pending['file_id']) is not str or pending['file_id'] not in files or type(pending['chunk_index']) is not int
                or not 0<=pending['chunk_index']<files[pending['file_id']].chunks):
            raise TransferError('media_source_exchange_invalid_record')
    if body['phase']=='accepted':
        if body['peer_saved'] is not None or body['peer_readback'] is not None:raise TransferError('media_source_exchange_invalid_record')
        return
    if pending is not None or not _batch_delivery_complete(media,bits,predecessors):raise TransferError('media_source_exchange_invalid_record')
    saved=body['peer_saved']
    if type(saved) is not dict:raise TransferError('media_source_exchange_invalid_record')
    parsed_saved=parse_saved(saved,manifest,now=saved.get('created_ms'))
    deadline=accepted['expires_ms'] if media.pc_batch else offer['expires_ms']
    if (any(getattr(parsed_saved,k)!=getattr(parsed,k) for k in ('transfer_id','manifest_sha256','acceptance_sha256','permission_epoch','destination_token'))
            or saved['created_ms']<offer['created_ms'] or saved['expires_ms']>deadline
            or len({r.receipt_sha256 for r in parsed_saved.receipts})!=len(files)):
        raise TransferError('media_source_exchange_invalid_record')
    if (type(body['peer_readback']) is not dict if body['phase']=='peer_readback' else body['peer_readback'] is not None):
        raise TransferError('media_source_exchange_invalid_record')
    if body['phase']=='peer_readback':
        from magnolie_file_published_batch_readback import CONTEXT, destination_token, READBACK_DOMAIN, KIND
        packet=body['peer_readback'];raw=packet.get('body')
        if (set(packet)!={'type','v','message_id','kind','created_ms','expires_ms','body'}
                or packet.get('type')!='message' or type(packet.get('v')) is not int or packet['v']!=1
                or not valid_uuid(packet.get('message_id'),version=4)
                or type(raw) is not dict or set(raw)!=CONTEXT|{'destination_token','binding_sha256','readback_sha256'}
                or packet.get('kind')!=KIND or type(packet.get('created_ms')) is not int or type(packet.get('expires_ms')) is not int
                or not offer['created_ms']<=packet['created_ms']<packet['expires_ms']<=deadline
                or packet['expires_ms']-packet['created_ms']>MAX_TTL_MS):
            raise TransferError('media_source_exchange_invalid_record')
        context={k:raw[k] for k in CONTEXT}
        if (destination_token(context)!=raw['destination_token'] or not _hex(raw['binding_sha256'])
                or sha256(READBACK_DOMAIN.encode()+canonical({k:v for k,v in raw.items() if k!='readback_sha256'})).hexdigest()!=raw['readback_sha256']
                or raw['offer_id']!=offer['message_id'] or raw['manifest_sha256']!=manifest.fingerprint
                or raw['transfer_id']!=manifest.transfer_id or raw['source_id']!=manifest.source_id
                or raw['permission_epoch']!=body['permission_epoch'] or raw['media_type']!=media.media_type
                or set(raw['members'])!=set(files)):
            raise TransferError('media_source_exchange_invalid_record')
        receipts={r.file_id:r for r in parsed_saved.receipts}
        for f in manifest.files:
            member=raw['members'][f.id]
            if (member['size']!=f.size or member['sha256']!=f.sha256 or member['mime_type']!=media.mime_types[f.id]
                    or member['publication_sha256']!=receipts[f.id].receipt_sha256):
                raise TransferError('media_source_exchange_invalid_record')
        return media, parsed_saved


def _batch_transition(before,after):
    if before['peer_saved'] is not None and after.get('peer_saved')!=before['peer_saved']:
        raise TransferError('media_source_exchange_original_attempt_required')
    if before['phase']!='accepted':
        if before['sent_bits']!=after.get('sent_bits') or before['pending_chunk']!=after.get('pending_chunk'):
            raise TransferError('media_source_exchange_invalid_transition')
        return
    pending=before['pending_chunk'];next_pending=after.get('pending_chunk')
    expected=copy.deepcopy(before['sent_bits'])
    if after.get('phase')=='peer_saved':
        if pending is not None or next_pending is not None or after.get('sent_bits')!=expected:
            raise TransferError('media_source_exchange_invalid_transition')
        return
    if pending is None:
        if next_pending is None or after.get('sent_bits')!=expected:raise TransferError('media_source_exchange_invalid_transition')
    else:
        expected[pending['file_id']]|=1<<pending['chunk_index']
        if next_pending is not None or after.get('sent_bits')!=expected:raise TransferError('media_source_exchange_invalid_transition')
