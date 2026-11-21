"""Native local trash projection: opaque IDs, never browser filesystem paths."""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import re
import time

from magnolie_file_transfer import TransferError
from magnolie_media_trash import NativeLocalMediaTrashAuthority,ProtectedMediaTrash
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_telefon import canonical


class NativeMediaTrashUi:
    PAGE_SIZE=128
    MAX_SCOPES=128
    MAX_PARENT_ENTRIES=4096

    def __init__(self,native_directory,current_ui,*,clock=time.monotonic):
        if not Path(native_directory).is_absolute() or not callable(current_ui):
            raise TransferError('media_trash_native_ui_required')
        self._root=str(native_directory);self._current_ui=current_ui;self._clock=clock;self._deadline=clock()+60

    def _current(self):
        if self._clock()>=self._deadline or self._current_ui() is not True:
            raise TransferError('media_trash_native_ui_changed')
        return True

    @contextmanager
    def _owner(self,scope):
        self._current()
        authority=NativeLocalMediaTrashAuthority(self._root,scope,local_guard=self._current)
        try:
            owner=ProtectedMediaTrash(authority)
            try:yield owner
            finally:owner.close()
        finally:authority.close()

    def _scopes(self):
        self._current()
        try:fd=os.open(self._root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        except FileNotFoundError:return () # No default native root/key creation.
        try:
            ProtectedPhotoPreferences._private(os.fstat(fd),directory=True)
            anchors=set();journals=set()
            with os.scandir(fd) as entries:
                for index,entry in enumerate(entries):
                    self._current()
                    if index>=self.MAX_PARENT_ENTRIES:raise TransferError('media_trash_native_scan_bound')
                    anchor=re.fullmatch(r'media-trash-anchor-v1-([0-9a-f]{64})\.seal',entry.name)
                    journal=re.fullmatch(r'media-trash-v1-([0-9a-f]{64})',entry.name)
                    if anchor:anchors.add(anchor.group(1))
                    if journal:journals.add(journal.group(1))
                    if len(anchors|journals)>self.MAX_SCOPES:raise TransferError('media_trash_native_scope_bound')
            if anchors!=journals:raise TransferError('media_trash_original_anchor_required')
            return tuple(sorted(anchors))
        finally:os.close(fd)

    def _inventory(self):
        rows=[]
        scopes=self._scopes()
        for scope in scopes:
            with self._owner(scope) as owner:
                snapshot,entries=owner.read()
                if not snapshot.associated:raise TransferError('media_trash_local_history_changed')
                for entry in sorted(entries,key=lambda value:(-value.sequence,value.operation)):
                    self._current()
                    if entry.state in ('restored','canceled','purged'):continue
                    rows.append(dict(scope=scope,operation=entry.operation,version=snapshot.version,
                        name=entry.mapping.relative_path.split('/')[-1],media_type=entry.mapping.association.media_type,state=entry.state))
        self._current()
        return scopes,rows

    @staticmethod
    def _empty_selection(scopes,rows):
        # Bind the confirmation to the complete overview, not a browser page.
        revision=sha256(canonical(dict(scopes=list(scopes),rows=rows))).hexdigest()
        return revision,[row for row in rows if row['state'] in ('trashed','purge_prepared')]

    def _list(self,cursor):
        scopes,rows=self._inventory()
        revision,selected=self._empty_selection(scopes,rows)
        if cursor>len(rows):raise TransferError('media_trash_page_changed')
        next_cursor=cursor+self.PAGE_SIZE
        return dict(entries=rows[cursor:next_cursor],next_cursor=next_cursor if next_cursor<len(rows) else None,
            total=len(rows),scopes=list(scopes),empty_revision=revision,empty_count=len(selected))

    def _empty(self,request):
        scopes,rows=self._inventory();revision,selected=self._empty_selection(scopes,rows)
        if revision!=request['version'] or len(selected)!=request['count']:
            raise TransferError('media_trash_stale_choice')
        completed=0;versions={row['scope']:row['version'] for row in selected}
        try:
            for row in selected:
                self._current()
                with self._owner(row['scope']) as owner:
                    snapshot,entries=owner.read()
                    if snapshot.version!=versions[row['scope']]:raise TransferError('media_trash_stale_choice')
                    entry=next((item for item in entries if item.operation==row['operation']),None)
                    if entry is None or entry.state!=row['state']:raise TransferError('media_trash_stale_choice')
                    # Each original continues to use the existing durable purge
                    # journal. Never replace a stale member or retry an uncertain one.
                    updated,entry=owner.purge_manual(owner.issue_action(),snapshot,entry.operation,self._current)
                    if entry.state!='purged':raise TransferError('media_trash_purge_not_current')
                    versions[row['scope']]=updated.version;completed+=1
        except Exception:
            # Even zero verified completions does not prove that no bytes were released.
            return dict(ok=False,supported=True,request_id=request['request_id'],action='empty',completed_count=completed)
        return dict(ok=True,supported=True,request_id=request['request_id'],action='empty',completed_count=completed)

    @staticmethod
    def validate_request(request):
        if type(request) is not dict:raise TransferError('media_trash_invalid_request')
        action=request.get('action');fields={'cmd','request_id','action'}
        if (request.get('cmd')!='medien_papierkorb' or type(request.get('request_id')) is not str
                or re.fullmatch(r'[A-Za-z0-9_-]{8,80}',request['request_id']) is None):
            raise TransferError('media_trash_invalid_request')
        if action=='list':
            if not fields<=set(request) or not set(request)<=fields|{'cursor'}:
                raise TransferError('media_trash_invalid_request')
            cursor=request.get('cursor',0)
            if type(cursor) is not int or not 0<=cursor<=NativeMediaTrashUi.MAX_SCOPES*ProtectedMediaTrash.MAX_OPERATIONS:
                raise TransferError('media_trash_invalid_request')
        elif action in ('restore','cancel','purge','thumbnail','preview'):
            wanted=fields|{'scope','operation','version'}|({'confirmed'} if action=='purge' else set())
            if (set(request)!=wanted or action=='purge' and request.get('confirmed') is not True or any(type(request.get(key)) is not str
                    or re.fullmatch(pattern,request[key]) is None for key,pattern in (
                        ('scope',r'[0-9a-f]{64}'),('operation',r'[0-9a-f]{32}'),('version',r'[0-9a-f]{64}')))):
                raise TransferError('media_trash_invalid_request')
        elif action=='empty':
            if (set(request)!=fields|{'version','count','confirmed'} or request['confirmed'] is not True
                    or type(request['version']) is not str or re.fullmatch(r'[0-9a-f]{64}',request['version']) is None
                    or type(request['count']) is not int or not 1<=request['count']<=NativeMediaTrashUi.MAX_SCOPES*ProtectedMediaTrash.MAX_OPERATIONS):
                raise TransferError('media_trash_invalid_request')
        else:raise TransferError('media_trash_invalid_request')
        return action

    def handle(self,request):
        action=self.validate_request(request);self._current()
        if action=='empty':return self._empty(request)
        restored_name=None
        if action!='list':
            with self._owner(request['scope']) as owner:
                snapshot,entries=owner.read()
                if snapshot.version!=request['version']:raise TransferError('media_trash_stale_choice')
                entry=next((value for value in entries if value.operation==request['operation']),None)
                if entry is None:raise TransferError('media_trash_original_operation_required')
                if action in ('thumbnail','preview'):
                    preview=owner.preview(owner.issue_action(),snapshot,entry.operation,self._current,mode=action)
                    self._current()
                    return dict(ok=True,supported=True,request_id=request['request_id'],action=action,scope=request['scope'],
                        operation=request['operation'],version=request['version'],preview=preview)
                method={'restore':owner.restore,'cancel':owner.cancel_prepared,'purge':owner.purge_manual}[action]
                _,completed=method(owner.issue_action(),snapshot,entry.operation,self._current)
                if action=='restore':restored_name=entry.mapping.relative_path.split('/')[-1]
            self._current()
            # Completion is independent of an unrelated broken history scope.
            # Refresh the overview with a separate read, never misreport a
            # verified restore because another scope could not be listed.
            return dict(ok=True,supported=True,request_id=request['request_id'],action=action,restored_name=restored_name,
                completed=dict(scope=request['scope'],operation=completed.operation,state=completed.state))
        # A recovery view may list these entries merely by opening a fold.
        # Expiry belongs to the independently guarded retention maintenance.
        result=self._list(request.get('cursor',0))
        return dict(result,ok=True,supported=True,request_id=request['request_id'],action=action,restored_name=restored_name)
