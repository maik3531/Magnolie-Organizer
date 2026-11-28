"""Private native prepared-source wire lifecycle (#400).

The ordinary private composition retains its own source-only controls. The
normal native connection instead lends its exact established session and keeps
its cleanup lane until actual output drains; it never creates a second epoch.
This is not a discovery flag, backup or retirement API. Every source requires
an actual prepared owner plus original consent, not frozen metadata. Every wire operation owns
the actual original-book/cache IO lease until the secure write has drained.
"""
from contextlib import contextmanager
from hashlib import sha256
import base64
import threading
import uuid

from magnolie_file_control import KIND as CONTROL,MAX_TTL_MS,FileControlPacket,FileGrantState,NativeLocalFileGrant,NativeFileControlSession,_hex
from magnolie_file_offer import create_offer
from magnolie_file_accept_message import KIND as ACCEPT,parse_acceptance
from magnolie_file_chunk_message import REQUEST as CHUNK_REQUEST,RESULT as CHUNK,parse_request
from magnolie_file_saved_message import KIND as SAVED,parse_saved
from magnolie_file_published_readback import KIND as PUBLISHED_READBACK,parse_readback
from magnolie_media_offer import KIND as MEDIA_OFFER,create_media_offer,validate_media_offer
from magnolie_media_mime import PREFIX_BYTES,identify
from magnolie_file_sources import _body
from magnolie_file_transfer import TransferError
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_exchange import _NativeSourceExchange,_batch_delivery_complete
from magnolie_telefon import SecureChannel,canonical,now_ms


class _NativeMediaSourceSender:
    def __init__(self,source,job_id,*,boundary=lambda _:None,_retry=None,_verification=False,_connection=None,_batch=None):
        from magnolie_media_source_pc import native_source_kind
        self._local_collection=native_source_kind(source)=='collection'
        self._batch=_batch
        if _batch is not None:
            from magnolie_media_source_batch import NativeCollectionMediaBatch
            from magnolie_media_source_batch_cache import FrozenNativeMediaBatch
            if (type(_batch) is not NativeCollectionMediaBatch or source._original_batch is not _batch
                    or _batch._owner is not source or type(_batch._cache) is not FrozenNativeMediaBatch
                    or _batch._id!=job_id or _retry is not None or _verification):
                raise TransferError('media_source_sender_original_batch_required')
            _batch._require()
        if (type(job_id) is not str
                or (_batch is None and job_id not in source._prepared) or not callable(boundary)):
            raise TransferError('media_source_sender_actual_preparation_required')
        if self._local_collection and (_retry is not None or _verification):
            raise TransferError('media_collection_sender_composition_required')
        self._source=source;self._job=job_id;self._prepared=_batch if _batch is not None else source._prepared[job_id]
        self._cache=_batch._cache if _batch is not None else self._prepared.cache
        self._authority=source._authority;self._channel=self._authority.native_channel
        self._connection=_connection
        if _connection is not None:
            from magnolie_file_desktop_connection import NativeDesktopFileConnection
            if (type(_connection) is not NativeDesktopFileConnection or _connection._authority is not self._authority
                    or _connection._channel is not self._channel
                    or getattr(_connection,'_media_pc_source' if self._local_collection else '_media_source',None) is not source or _retry is not None):
                raise TransferError('media_source_sender_original_connection_required')
            if _batch is not None:_connection._require_pc_batch_counterpart()
        if type(self._channel) is not SecureChannel:raise TransferError('media_source_sender_secure_channel_required')
        self._closed=threading.Event();self._gate=threading.Lock();self._active=threading.local();self._boundary=boundary
        self._jobs=_NativeSourceJobs(self._authority);self._record=None;self._binding=None;self._requests=set()
        self._request_limit=max(2048,2*sum(f.chunks for f in self._cache.manifest.files)) if _batch is not None else 2048
        self._retry_spec=_retry
        self._verification=_verification
        if _verification:
            from magnolie_media_source_reprepare import _NativeSourceRepreparation
            proof=self._prepared.repreparation
            if (type(proof) is not _NativeSourceRepreparation or proof._source is not source or proof._job!=job_id
                    or not proof._used or getattr(proof,'_completed_cache',None) is not self._cache
                    or _retry is None):
                raise TransferError('media_source_verification_fresh_repreparation_required')
        original=_NativeSourceExchange(self)
        if _retry is None:
            self._journal=original
            if original.lookup() is not None:raise TransferError('media_source_sender_existing_attempt_held')
        else:
            if (type(_retry) is not tuple or len(_retry)!=2 or not _hex(_retry[0]) or _retry[1] is not None and not _hex(_retry[1])):
                raise TransferError('media_source_retry_exact_history_required')
            from magnolie_media_source_retry import _NativeSourceRetryExchange
            self._journal=_NativeSourceRetryExchange(self,original,*_retry)
        self._controls=(_connection._controls if _connection is not None else
            NativeFileControlSession(self._authority.identity,self._peer,self._local))

    @classmethod
    def retry(cls,source,job_id,original_exchange_version,previous_retry_version=None,*,boundary=lambda _:None):
        return cls(source,job_id,boundary=boundary,_retry=(original_exchange_version,previous_retry_version))

    @classmethod
    def verify_published(cls,source,job_id,original_exchange_version,completed_retry_version=None,*,boundary=lambda _:None):
        return cls(source,job_id,boundary=boundary,_retry=(original_exchange_version,completed_retry_version),_verification=True)

    def close(self):
        # Cancellation never releases the source/cache OS lease or socket from
        # an actual outstanding operation. The connection owns the socket.
        self._closed.set()

    def _permission(self):
        if self._connection is not None:
            self._connection._ready()
            if self._connection._media_sender is not self or self._controls is not self._connection._controls:
                raise TransferError('media_source_sender_original_connection_required')
            if getattr(self._connection,'_media_pc_source' if self._local_collection else '_media_source',None) is not self._source:
                raise TransferError('media_source_sender_original_connection_required')
        if self._batch is not None:
            if self._connection is not None:self._connection._require_pc_batch_counterpart()
            if (self._closed.is_set() or self._source._original_batch is not self._batch or self._batch._cache is not self._cache):
                raise TransferError('media_source_sender_retired')
            self._batch._require()
        else:
            if (self._closed.is_set() or self._source._prepared.get(self._job) is not self._prepared
                    or self._prepared.failed.is_set()):raise TransferError('media_source_sender_retired')
            self._prepared.permission()
        self._jobs.require_version(self._job,self._cache._job_version)
        if self._retry_spec is not None:self._journal.require_owner()
        else:
            with self._jobs._database() as (db,key):
                db.execute('BEGIN');self._jobs._catalog.verify(db,key)
                if db.execute('SELECT 1 FROM meta WHERE key=?',(self._jobs._catalog._retry+self._job,)).fetchone():
                    raise TransferError('media_source_sender_newer_attempt_held')

    def _peer(self):
        if not getattr(self._active,'checking_batch_binding',False):self._permission()
        peer=self._authority.current_peer()
        return peer.control_peer(self,ready=True,handlers_ready=True) if peer is not None else None

    def _local(self):
        if not getattr(self._active,'checking_batch_binding',False):self._permission()
        snapshot=self._source._preferences.read();policy=snapshot.policy
        if policy is None:raise TransferError('media_source_sender_consent_required')
        revision=policy.permission_revision if policy.permission_revision is not None else policy.revision
        # This private source-only composition cannot expose RECEIVE or alter
        # ProtectedPhotoPreferences.native_local_state's production SEND=false.
        return NativeLocalFileGrant(FileGrantState(revision,policy.permission_epoch,True,False),self,True)

    def _lease_current(self):
        self._permission();reader=getattr(self._active,'reader',None)
        if reader is None:raise TransferError('media_source_sender_io_lease_required')
        reader._permission()

    def _current(self):
        self._lease_current()
        if self._record is not None:
            self._journal.require(self._record)
            offer=self._record.body['offer'];at=now_ms()
            if at<offer['created_ms'] or at>=offer['expires_ms']:raise TransferError('media_source_sender_offer_expired')
        if self._binding is not None:
            # This synchronous binding lookup is already inside the checked
            # original IO lease above. Only the private session calls _peer
            # and _local; both still read their live inputs for every binding.
            private_batch=self._batch is not None and self._connection is None
            if private_batch:self._active.checking_batch_binding=True
            try:binding=self._controls.binding(self._binding.destination_token,sender_is_local=True)
            finally:
                if private_batch:self._active.checking_batch_binding=False
            if binding!=self._binding:raise TransferError('media_source_sender_binding_changed')
            if private_batch:
                if self._closed.is_set():raise TransferError('media_source_sender_retired')
                if self._record is not None and now_ms()>=offer['expires_ms']:raise TransferError('media_source_sender_offer_expired')

    @contextmanager
    def _operation(self,*,incoming=False):
        if self._connection is None:
            with self._source_operation(incoming=incoming) as reader:yield reader
        else:
            # One connection lane also serializes controls and protects cleanup
            # through the actual cache/socket drain. Never take a second session.
            with self._connection._operation(incoming=incoming):
                with self._source_operation(incoming=incoming) as reader:yield reader

    @contextmanager
    def _source_operation(self,*,incoming=False):
        # A response may arrive before the actual send has returned. Serialize
        # it behind that bounded output, rather than discarding a positive ACK.
        acquired=self._gate.acquire(timeout=MAX_TTL_MS/1000) if incoming else self._gate.acquire(blocking=False)
        if not acquired:raise TransferError('media_source_sender_busy')
        try:
            self._permission()
            with (self._batch.cached_reader() if self._batch is not None else self._source.prepared_cache(self._job)) as reader:
                self._active.reader=reader
                try:self._current();yield reader;self._current()
                finally:self._active.reader=None
        except BaseException:
            self.close();raise
        finally:self._gate.release()

    @staticmethod
    def _message(kind,body,expires=None):
        at=now_ms()
        return dict(type='message',v=1,message_id=str(uuid.uuid4()),kind=kind,created_ms=at,
            expires_ms=min(at+MAX_TTL_MS,expires) if expires is not None else at+MAX_TTL_MS,body=body)

    def send_controls(self):
        if self._connection is not None:
            self._permission();return self._connection.send_controls()
        with self._operation():
            packet=self._controls.packet();message=self._message(CONTROL,packet.wire())
            self._current();self._channel.send(message);self._current();self._controls.mark_sent(packet)
            return message

    def observe_controls(self,channel,message):
        if self._connection is not None:
            if channel is not self._channel:raise TransferError('media_source_sender_foreign_channel')
            self._permission();return self._connection.receive(message)
        with self._operation(incoming=True):
            if channel is not self._channel:raise TransferError('media_source_sender_foreign_channel')
            packet=FileControlPacket.parse(_body(message,CONTROL,now_ms()))
            self._controls.observe_remote(packet,self._peer())

    def send_offer(self):
        return self._send_offer(media=False)

    def send_media_offer(self):
        if self._retry_spec is not None:raise TransferError('media_source_sender_media_retry_unavailable')
        return self._send_offer(media=True)

    def _send_offer(self,*,media):
        if self._local_collection and not media:raise TransferError('media_collection_sender_pc_origin_required')
        with self._operation() as reader:
            if self._record is not None:raise TransferError('media_source_sender_offer_already_attempted')
            binding=self._controls.binding('0'*64,sender_is_local=True)
            if binding is None:raise TransferError('media_source_sender_control_agreement_required')
            self._binding=binding
            if self._batch is not None:
                offer=self._batch_offer(reader)
            elif media:
                manifest=self._cache.manifest;file=manifest.files[0]
                kind=self._cache._media_type if self._local_collection else self._cache.original_references[file.id]['media_type']
                token=self._source._transport.intent_for(kind,to_phone=True)
                if token is None or sha256(canonical(token.body)).hexdigest()!=reader.media_intent_sha256:
                    raise TransferError('media_source_sender_original_intent_required')
                prefix=bytearray()
                try:
                    for index in range(file.chunks):
                        if len(prefix)>=min(file.size,PREFIX_BYTES):break
                        self._current();data=bytearray(reader.read_chunk(index))
                        try:prefix.extend(memoryview(data)[:min(len(data),PREFIX_BYTES-len(prefix))])
                        finally:data[:]=b'\0'*len(data)
                    mime=identify(prefix,file.size,kind)
                finally:prefix[:]=b'\0'*len(prefix)
                pc=None
                if self._local_collection:
                    origin=self._cache.pc_origin
                    if origin is None:raise TransferError('media_collection_sender_pc_origin_required')
                    previous=self._jobs.pc_previous_publication(self._cache.manifest.source_id,self._cache._job_version)
                    if self._connection is not None and self._connection._media_support is not None:
                        if kind!='video' or mime!='video/mp4' or previous is not None or file.size<=0 or self._cache.original_references:
                            raise TransferError('media_source_typed_video_counterpart_required')
                        worker=self._connection._mapped_worker
                        if (worker is None or self._connection._private_worker_intent('video',
                                automatic=worker._automatic,mixed=worker._mixed) is not token):
                            raise TransferError('media_source_sender_original_intent_required')
                    pc={file.id:dict(format=1,origin_sha256=sha256(b'magnolie-pc-media-origin-v1\0'+canonical(origin)).hexdigest(),
                        previous_publication_sha256=previous)}
                offer=create_media_offer(manifest,token.body,kind,{file.id:mime},self._cache.original_references,pc_origins=pc)
            else:offer=create_offer(self._cache.manifest)
            self._record=self._journal.write(None,dict(phase='offer_planned',offer=offer,permission_epoch=binding.permission_epoch,
                acceptance=None,sent_bits={file.id:0 for file in self._cache.manifest.files} if self._batch is not None else 0,
                pending_chunk=None,peer_saved=None))
            self._boundary('source_offer_planned');self._current()
            self._channel.send(offer);self._boundary('source_offer_output');self._current()
            body=self._record.body;body['phase']='offer_sent';self._record=self._journal.write(self._record,body)
            return offer

    def _accept(self,message):
        if self._record is None or self._record.body['phase']!='offer_sent':raise TransferError('media_source_sender_actual_offer_required')
        accepted=parse_acceptance(message);body=self._record.body;manifest=self._cache.manifest
        if (accepted.offer_id!=body['offer']['message_id'] or accepted.manifest_sha256!=manifest.fingerprint
                or accepted.transfer_id!=manifest.transfer_id or accepted.permission_epoch!=self._binding.permission_epoch
                or message['created_ms']<body['offer']['created_ms'] or message['expires_ms']>body['offer']['expires_ms']):
            raise TransferError('media_source_sender_acceptance_changed')
        binding=self._controls.binding(accepted.destination_token,sender_is_local=True)
        if binding is None or binding.permission_epoch!=accepted.permission_epoch:raise TransferError('media_source_sender_binding_changed')
        if self._retry_spec is not None:self._journal.require_new_acceptance(accepted)
        self._binding=binding;body.update(phase='accepted',acceptance=message)
        self._record=self._journal.write(self._record,body)

    def _accepted_request(self,message):
        if self._record is None or self._record.body['phase']!='accepted':raise TransferError('media_source_sender_acceptance_required')
        body=self._record.body;accepted=parse_acceptance(body['acceptance']);request=parse_request(message)
        expected=dict(transfer_id=accepted.transfer_id,manifest_sha256=accepted.manifest_sha256,
            acceptance_sha256=accepted.acceptance_sha256,permission_epoch=accepted.permission_epoch,destination_token=accepted.destination_token)
        file=next((f for f in self._cache.manifest.files if f.id==request['file_id']),None) if self._batch is not None else self._cache.manifest.files[0]
        if (any(request[key]!=value for key,value in expected.items()) or file is None or request['file_id']!=file.id or request['chunk_index']>=file.chunks
                or message['expires_ms']>body['acceptance']['expires_ms'] or body['pending_chunk'] is not None
                or message['message_id'] in self._requests or len(self._requests)>=self._request_limit):
            raise TransferError('media_source_sender_request_changed')
        return request

    def _chunk(self,message,reader):
        request=self._accepted_request(message);body=self._record.body
        data=bytearray(reader.read_chunk(request['file_id'],request['chunk_index']) if self._batch is not None else reader.read_chunk(request['chunk_index']))
        try:
            response=self._message(CHUNK,dict(request,request_id=message['message_id'],data_base64=base64.b64encode(data).decode('ascii'),
                data_sha256=sha256(data).hexdigest()),min(message['expires_ms'],body['acceptance']['expires_ms']))
        finally:data[:]=b'\0'*len(data)
        body['pending_chunk']=dict(request_id=message['message_id'],request_sha256=sha256(canonical(message)).hexdigest(),
            chunk_index=request['chunk_index'],response_sha256=sha256(canonical(response)).hexdigest())
        if self._batch is not None:body['pending_chunk']['file_id']=request['file_id']
        self._record=self._journal.write(self._record,body);self._requests.add(message['message_id'])
        self._boundary('source_chunk_planned');self._current()
        self._channel.send(response);self._boundary('source_chunk_output');self._current()
        body=self._record.body
        if self._batch is not None:body['sent_bits'][request['file_id']]|=1<<request['chunk_index']
        else:body['sent_bits']|=1<<request['chunk_index']
        body['pending_chunk']=None
        self._record=self._journal.write(self._record,body)

    def _saved(self,message):
        if self._record is None or self._record.body['phase']!='accepted':raise TransferError('media_source_sender_acceptance_required')
        body=self._record.body;accepted=parse_acceptance(body['acceptance']);saved=parse_saved(message,self._cache.manifest)
        if (any(getattr(saved,key)!=getattr(accepted,key) for key in ('transfer_id','manifest_sha256','acceptance_sha256','permission_epoch','destination_token'))
                or body['pending_chunk'] is not None or not self._all_sent(body)):
            raise TransferError('media_source_sender_saved_changed')
        if body['format'] in (4,5) and (message['created_ms']<body['offer']['created_ms'] or message['expires_ms']>body['offer']['expires_ms']):
            raise TransferError('media_source_sender_saved_changed')
        if self._batch is not None and message['expires_ms']>body['acceptance']['expires_ms']:
            raise TransferError('media_source_batch_acceptance_deadline_changed')
        body.update(phase='peer_saved',peer_saved=message);self._record=self._journal.write(self._record,body)

    def _readback(self,message):
        if self._batch is not None:return self._batch_readback(message)
        if self._record is not None and self._record.body['format']==4:
            return self._media_readback(message)
        if (self._retry_spec is None or self._record is None or self._record.body['phase']!='offer_sent'
                or self._record.body['acceptance'] is not None or self._record.body['sent_bits']!=0
                or self._record.body['pending_chunk'] is not None or self._record.body['peer_saved'] is not None):
            raise TransferError('media_source_sender_readback_offer_required')
        body=self._record.body;raw=message.get('body')
        if type(raw) is not dict or not _hex(raw.get('destination_token')):raise TransferError('media_source_sender_readback_invalid')
        binding=self._controls.binding(raw['destination_token'],sender_is_local=True)
        if binding is None or binding.permission_epoch!=body['permission_epoch']:raise TransferError('media_source_sender_binding_changed')
        file=self._cache.manifest.files[0];kind=self._cache.original_references[file.id]['media_type']
        parse_readback(message,body['offer'],binding,kind)
        self._binding=binding
        body.update(format=3 if self._verification else 2,phase='peer_readback',peer_readback=message)
        self._record=self._journal.write(self._record,body)

    def _media_readback(self,message):
        body=self._record.body;raw=message.get('body')
        if (body['phase']!='peer_saved' or body['pending_chunk'] is not None or body['peer_saved'] is None
                or body['sent_bits']!=(1<<self._cache.manifest.files[0].chunks)-1 or type(raw) is not dict or not _hex(raw.get('destination_token'))):
            raise TransferError('media_source_sender_readback_saved_required')
        binding=self._controls.binding(raw['destination_token'],sender_is_local=True)
        if binding is None or binding.permission_epoch!=body['permission_epoch']:raise TransferError('media_source_sender_binding_changed')
        manifest=self._cache.manifest;file=manifest.files[0]
        media=validate_media_offer(body['offer'],manifest.sender_id,manifest.receiver_id)
        parsed=parse_readback(message,media.offer,binding,media.media_type)
        saved=parse_saved(body['peer_saved'],manifest)
        if parsed.body['publication_sha256']!=saved.receipts[0].receipt_sha256 or parsed.body['mime_type']!=media.mime_types[file.id]:
            raise TransferError('media_source_sender_publication_changed')
        self._binding=binding;body.update(phase='peer_readback',peer_readback=message)
        self._record=self._journal.write(self._record,body)

    def observe(self,channel,message):
        with self._operation(incoming=True) as reader:
            if channel is not self._channel:raise TransferError('media_source_sender_foreign_channel')
            kind=message.get('kind') if type(message) is dict else None
            if self._verification and kind!=PUBLISHED_READBACK:
                raise TransferError('media_source_verification_readback_only')
            if kind==ACCEPT:self._accept(message)
            elif kind==CHUNK_REQUEST:self._chunk(message,reader)
            elif kind==SAVED:self._saved(message)
            elif kind==PUBLISHED_READBACK:self._readback(message)
            else:raise TransferError('media_source_sender_unexpected_message')

    def observation(self):
        # Historical only. A queried result cannot be adopted by a new sender.
        return self._journal.lookup()

    def _all_sent(self,body):
        manifest=self._cache.manifest
        if self._batch is None:return body['sent_bits']==(1<<manifest.files[0].chunks)-1
        media=validate_media_offer(body['offer'],manifest.sender_id,manifest.receiver_id,allow_pc_batch=True)
        return media.manifest==manifest and _batch_delivery_complete(media,body['sent_bits'],self._batch_predecessors())

    def _batch_predecessors(self):
        from dataclasses import asdict
        return {fid:asdict(selection.previous) if selection.previous is not None else None
                for fid,selection in self._batch._selections.items()}

    def _batch_offer(self,reader):
        # Complete predecessor snapshots originate in native source admission
        # and are revalidated under the all-member cache-plan transaction.
        manifest=self._cache.manifest;kind=self._batch._kind;token=self._source._transport.intent_for(kind,to_phone=True)
        if token is None or sha256(canonical(token.body)).hexdigest()!=sha256(canonical(self._batch._token.body)).hexdigest():
            raise TransferError('media_source_sender_original_intent_required')
        from magnolie_media_mime import identify_collection
        mime_types={};origins={}
        for file in manifest.files:
            prefix=bytearray()
            try:
                for index in range(file.chunks):
                    if len(prefix)>=min(file.size,PREFIX_BYTES):break
                    self._current();data=reader.read_chunk(file.id,index)
                    try:prefix.extend(memoryview(data)[:min(len(data),PREFIX_BYTES-len(prefix))])
                    finally:data[:]=b'\0'*len(data)
                mime_types[file.id]=identify_collection(prefix,file.size,kind)
            finally:prefix[:]=b'\0'*len(prefix)
            origin=self._batch._entries[file.id]['local_origin']
            previous=self._batch._selections[file.id].previous
            origins[file.id]=dict(format=1,origin_sha256=sha256(b'magnolie-pc-media-origin-v1\0'+canonical(origin)).hexdigest(),
                previous_publication_sha256=previous.publication_sha256 if previous is not None else None)
        return create_media_offer(manifest,token.body,kind,mime_types,{},pc_origins=origins,pc_batch=True)

    def _batch_readback(self,message):
        if self._record is None:raise TransferError('media_source_sender_readback_saved_required')
        body=self._record.body;raw=message.get('body')
        if (body['format']!=5 or body['phase']!='peer_saved' or body['peer_saved'] is None
                or body['pending_chunk'] is not None or not self._all_sent(body)
                or type(raw) is not dict or not _hex(raw.get('destination_token'))):
            raise TransferError('media_source_sender_readback_saved_required')
        binding=self._controls.binding(raw['destination_token'],sender_is_local=True)
        if binding is None or binding.permission_epoch!=body['permission_epoch']:raise TransferError('media_source_sender_binding_changed')
        accepted=parse_acceptance(body['acceptance'])
        manifest=self._cache.manifest;media=validate_media_offer(body['offer'],manifest.sender_id,manifest.receiver_id,allow_pc_batch=True)
        if not media.pc_batch or type(message.get('expires_ms')) is not int or message['expires_ms']>body['acceptance']['expires_ms']:
            raise TransferError('media_source_batch_acceptance_deadline_changed')
        if binding.permission_epoch!=accepted.permission_epoch:raise TransferError('media_source_sender_binding_changed')
        from magnolie_file_published_batch_readback import parse_batch_readback
        parsed=parse_batch_readback(message,media.offer,binding,media.media_type)
        saved=parse_saved(body['peer_saved'],manifest);receipts={r.file_id:r for r in saved.receipts}
        for file in manifest.files:
            member=parsed.body['members'][file.id]
            if member['publication_sha256']!=receipts[file.id].receipt_sha256 or member['mime_type']!=media.mime_types[file.id]:
                raise TransferError('media_source_sender_publication_changed')
        self._binding=binding;body.update(phase='peer_readback',peer_readback=message)
        self._record=self._journal.write(self._record,body)
