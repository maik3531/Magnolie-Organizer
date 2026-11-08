"""Shared media intent codec (#338); no personal settings, IO or grants.

Matches Notes MediaSyncSettings. Each media field has its own edit clock even
when two fields reuse the same underlying Boolean register validator. Native
transport must separately prove persisted/sent/ACK/peer-echo identity.
"""
import copy
from contextlib import contextmanager

import magnolie_shared_sync as shared

VERSION=1
DISCOVERY_VERSION=23
KIND='file_transfer.shared_settings'
START_KIND='file_transfer.sync_request'
RESULT_KIND='file_transfer.sync_result'
FIELDS={'photos_enabled':'custom_enabled','videos_enabled':'time_enabled','auto_mode':'auto_mode',
    'skip_deletions':'skip_deletions','collection_mode':'content_mode','direction':'content_mode','enabled':'custom_enabled',
    'photos_only':'skip_deletions'}
DEFAULTS=dict(enabled=False,photos_enabled=True,videos_enabled=False,collection_mode='phone_inventory',
    auto_mode='manual',skip_deletions=False,direction='phone_to_pc',photos_only=False)
MODES={'collection_mode':{'phone_inventory':'phone_scope','entire_collection':'two_way','import_only':'phone_import'},
    'direction':{'phone_to_pc':'phone_import','two_way':'two_way','pc_to_phone':'phone_scope'},'auto_mode':{'manual':'manual','wifi':'wifi'}}


def _value(field,value,to_registers):
    if field not in MODES:return value
    modes=MODES[field] if to_registers else {value:key for key,value in MODES[field].items()}
    if type(value) is not str or value not in modes:raise ValueError('invalid media setting mode')
    return modes[value]


def _edits(field,raw,to_registers):
    if type(raw) is not dict:raise ValueError('invalid media register')
    result={}
    for actor,edit in raw.items():
        if type(edit) is not dict or set(edit)!={'counter','value'}:raise ValueError('invalid media edit')
        result[actor]=dict(edit,value=_value(field,edit['value'],to_registers))
    return result


def _register(field,raw):
    if field not in FIELDS:raise ValueError('unknown media setting')
    return shared.validate(dict(format=shared.VERSION,settings={FIELDS[field]:_edits(field,raw,True)}))


def validate(body):
    if (type(body) is not dict or set(body)!={'format','settings'} or type(body['format']) is not int or body['format']!=VERSION
            or type(body['settings']) is not dict or not 1<=len(body['settings'])<=len(FIELDS)):
        raise ValueError('invalid media settings')
    for field,raw in body['settings'].items():_register(field,raw)
    return body


def scoped(body,local_actor,peer_actor,*,complete=True):
    validate(body)
    shared.actor(local_actor);shared.actor(peer_actor)
    if local_actor==peer_actor or complete and set(body['settings'])!=set(FIELDS):raise ValueError('incomplete or foreign media settings')
    for field,raw in body['settings'].items():shared.scoped(_register(field,raw),local_actor,peer_actor)
    return body


def create(local_actor):
    shared.actor(local_actor)
    return validate(dict(format=VERSION,settings={field:{local_actor:dict(counter=0,value=value)} for field,value in DEFAULTS.items()}))


def normalize_stored(body,local_actor,peer_actor):
    """Project only complete protected seven-field records, never wire patches.

    Old choices/clocks remain byte-for-byte values; a passive read writes nothing.
    The new filter starts OFF so migration does not narrow an existing inventory.
    """
    scoped(body,local_actor,peer_actor,complete=False)
    keys=set(body['settings'])
    if keys not in (set(FIELDS),set(FIELDS)-{'photos_only'}):raise ValueError('incomplete stored media settings')
    result=copy.deepcopy(body)
    if 'photos_only' not in keys:
        result['settings']['photos_only']={local_actor:dict(counter=0,value=False)}
    return scoped(result,local_actor,peer_actor)


def configured(body):
    """Independent stored choices for display; not effective wire authority."""
    validate(body)
    result={field:_value(field,shared.effective(_register(field,raw))[FIELDS[field]],False) for field,raw in body['settings'].items()}
    modes=body['settings'].get('auto_mode')
    if modes is not None:
        newest=max(edit['counter'] for edit in modes.values())
        result['auto_mode']='manual' if any(edit['counter']==newest and edit['value']=='manual' for edit in modes.values()) else 'wifi'
    return result


def effective(body):
    result=configured(body)
    # Import scope never exports. Keep the independent stored direction for
    # switching back to an inventory scope without rewriting its edit history.
    if result.get('collection_mode')=='import_only' and 'direction' in result:result['direction']='phone_to_pc'
    return result


def change(body,local_actor,peer_actor,field,value):
    scoped(body,local_actor,peer_actor)
    if field not in FIELDS:raise ValueError('unknown media setting')
    changed=shared.change(_register(field,body['settings'][field]),local_actor,peer_actor,FIELDS[field],_value(field,value,True))
    result=copy.deepcopy(body);result['settings'][field]=_edits(field,changed['settings'][FIELDS[field]],False)
    return validate(result)


def merge(body,incoming,local_actor,peer_actor,*,current_choices=False):
    if type(current_choices) is not bool:raise ValueError('invalid media merge mode')
    scoped(body,local_actor,peer_actor);scoped(incoming,local_actor,peer_actor,complete=False)
    result=copy.deepcopy(body)
    combine=shared.merge_current_choices if current_choices else shared.merge
    for field,raw in incoming['settings'].items():
        merged=combine(_register(field,result['settings'][field]),_register(field,raw),local_actor,peer_actor)
        result['settings'][field]=_edits(field,merged['settings'][FIELDS[field]],False)
    return validate(result)


def requested_for(body,media_type,*,to_phone=False):
    validate(body)
    if set(body['settings'])!=set(FIELDS) or media_type not in ('images','video') or type(to_phone) is not bool:
        raise ValueError('complete media scope required')
    values=effective(body)
    return values['enabled'] and values['photos_enabled' if media_type=='images' else 'videos_enabled'] and (
        values['direction'] in (('two_way','pc_to_phone') if to_phone else ('two_way','phone_to_pc')))


def validate_start(body):
    if type(body) is not dict or set(body)!={'format','settings'} or type(body['format']) is not int or body['format']!=VERSION:
        raise ValueError('invalid media start')
    validate(body['settings'])
    if set(body['settings']['settings'])!=set(FIELDS):raise ValueError('complete media settings required')
    return body


def validate_result(body):
    if (type(body) is not dict or set(body)!={'format','request_id','state'} or type(body['format']) is not int or body['format']!=VERSION
            or body['state'] not in ('content_pass','review','held')):raise ValueError('invalid media result')
    shared.actor(body['request_id']);return body


class NativeMediaSettingsStore:
    """Existing native own-phone metadata only; no defaults on passive reads.

    This is independent of personal format 9 and native source/receive consent.
    It is not wired to discovery or a sender factory. Native transport must
    still establish actual secure output, ACK and peer echo before any intent
    projection can reach source IO.
    """
    def __init__(self,authority):
        from magnolie_file_native_authority import NativeDesktopFileAuthority
        if type(authority) is not NativeDesktopFileAuthority:raise ValueError('native media settings authority required')
        import threading
        self._authority=authority;self._store=authority.binding.store_owner;self._gate=threading.RLock()
        self._peer_id=authority.binding.peer_id;self._public=authority.binding.static_public
        self._local=authority.identity.receiver_id
        peer=authority.current_peer()
        if peer is None:raise PermissionError('media_settings_native_owner_changed')
        self._key='media_settings:'+self._peer_id+':'+peer.identity_sha256
        self._fresh()

    def _fresh(self):
        from magnolie_telefon import strict_json
        peer=self._authority.current_peer()
        if peer is None or not peer.metadata_supported:raise PermissionError('media_settings_native_owner_changed')
        self._store._shared_settings_binding(self._peer_id,self._public)
        peers=strict_json(self._authority.protection.read_native_peers_blob())['items']
        status=peers[0]['capabilities'].get('items',{}).get('device_status',{}) if len(peers)==1 else {}
        if status.get('available') is not True or DISCOVERY_VERSION not in status.get('versions',[]):
            raise PermissionError('media_settings_peer_unsupported')

    @contextmanager
    def _database(self):
        import sqlite3
        from pathlib import Path
        # Never create a replacement metadata database on a passive read/fault.
        db=sqlite3.connect(Path(self._store.database_path).absolute().as_uri()+'?mode=rw',uri=True)
        try:
            with db:yield db
        finally:db.close()

    def read(self):
        from magnolie_telefon import strict_json
        with self._gate:
            self._fresh()
            with self._database() as db:row=db.execute('SELECT value FROM meta WHERE key=?',(self._key,)).fetchone()
            if row is None:self._fresh();return None
            body=strict_json(self._store._decrypt(row[0],'media_settings',self._key))
            body=normalize_stored(body,self._local,self._peer_id);self._fresh();return body

    def _update(self,apply):
        from magnolie_telefon import canonical,strict_json
        with self._gate:
            self._fresh()
            with self._database() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT value FROM meta WHERE key=?',(self._key,)).fetchone()
                previous=strict_json(self._store._decrypt(row[0],'media_settings',self._key)) if row else create(self._local)
                previous=normalize_stored(previous,self._local,self._peer_id)
                updated=apply(previous);scoped(updated,self._local,self._peer_id);self._fresh()
                if row is None or updated!=previous:
                    encrypted=self._store._encrypt(canonical(updated),'media_settings',self._key);self._fresh()
                    db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(self._key,encrypted))
            observed=self.read()
            if observed!=updated:raise PermissionError('media_settings_commit_readback_changed')
            return observed

    def change(self,field,value):
        return self._update(lambda body:change(body,self._local,self._peer_id,field,value))

    def merge(self,incoming):
        scoped(incoming,self._local,self._peer_id,complete=False)
        return self._update(lambda body:merge(body,incoming,self._local,self._peer_id,current_choices=True))
