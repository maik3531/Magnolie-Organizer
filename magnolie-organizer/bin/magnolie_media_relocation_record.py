"""Local special-folder journal record and read-only recovery observation.

The codec is not persistence, a filesystem operation or a permission. An
authenticated native journal must bind it to the original action before use.
"""
from dataclasses import dataclass, replace
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import os
import stat

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import _hex
from magnolie_file_transfer import MAX_FILE_BYTES, TransferError, _portable_path
from magnolie_telefon import canonical


_MAX_DIRECTORY_ENTRIES = 10000
_DIRECTORY_FLAGS = os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC


def _require_unique_target_name(parent,name):
    # A separate description ensures a repeat scan starts at the first entry.
    folded=name.casefold();scan_fd=os.open('.',_DIRECTORY_FLAGS,dir_fd=parent)
    try:
        with os.scandir(scan_fd) as entries:
            for index,entry in enumerate(entries):
                if index>=_MAX_DIRECTORY_ENTRIES:
                    raise TransferError('photo_relocation_target_inventory_unproven')
                if entry.name!=name and entry.name.casefold()==folded:
                    raise TransferError('photo_relocation_target_alias_collision')
    finally:os.close(scan_fd)


@dataclass(frozen=True)
class RelocationTargetParentObservation:
    """Existing inode chain and missing relative parents, not a mkdir grant."""
    existing: tuple
    missing: tuple


@dataclass(frozen=True)
class MissingGifTargetDraft:
    """Read-only intent candidate, distinct from any prepared rename record."""
    operation: str
    book_sha256: str
    preferences_sha256: str
    original_mapping_sha256: str
    destination: NativeAcceptedDestination
    source: str
    source_parents: tuple
    target: str
    target_parents: RelocationTargetParentObservation
    file: 'RelocationFileWitness'

    @property
    def grants_write_authority(self):return False


@dataclass(frozen=True)
class GifRelocationFolderPlan:
    """Whole selection including missing parents; never accepted by the journal."""
    members: tuple
    selection_sha256: str

    @property
    def grants_write_authority(self):return False


def bind_gif_relocation_folder_plan(drafts,destination):
    """Commit to the existing inode chains and the exact missing names together."""
    if (type(drafts) is not tuple or not 1<=len(drafts)<=128
            or type(destination) is not NativeAcceptedDestination):
        raise TransferError('photo_relocation_invalid_folder_plan')
    members=[];prefixes={};subject=None;paths=set();inodes=set();mappings=set()
    for draft in drafts:
        if type(draft) is MediaRelocationRecord and draft.phase=='prepared' and draft.selection_sha256=='0'*64:
            draft=MissingGifTargetDraft(draft.operation,draft.book_sha256,draft.preferences_sha256,draft.original_mapping_sha256,
                destination,draft.source,draft.source_parents,draft.target,RelocationTargetParentObservation(draft.target_parents,()),draft.file)
        if (type(draft) is not MissingGifTargetDraft or draft.destination!=destination
                or not _hex(draft.book_sha256) or not _hex(draft.preferences_sha256) or not _hex(draft.original_mapping_sha256)
                or type(draft.operation) is not str or len(draft.operation)!=32 or not _hex(draft.operation*2)
                or type(draft.file) is not RelocationFileWitness or type(draft.target_parents) is not RelocationTargetParentObservation):
            raise TransferError('photo_relocation_invalid_folder_plan')
        current_subject=draft.operation,draft.book_sha256,draft.preferences_sha256
        if subject is None:subject=current_subject
        if current_subject!=subject or draft.file.file_key in inodes or draft.original_mapping_sha256 in mappings:
            raise TransferError('photo_relocation_invalid_folder_plan')
        inodes.add(draft.file.file_key);mappings.add(draft.original_mapping_sha256)
        source=_portable_path(draft.source);target=_portable_path(draft.target)
        if target!='Animationen/'+source:
            raise TransferError('photo_relocation_invalid_folder_plan')
        source_parts=source.split('/');target_parts=target.split('/')
        root=destination.ancestor_keys[0];existing,missing=draft.target_parents.existing,draft.target_parents.missing
        if (type(existing) is not tuple or not 1<=len(existing)<=len(target_parts) or existing[0]!=root
                or type(missing) is not tuple or missing!=tuple(target_parts[len(existing)-1:-1])
                or type(draft.source_parents) is not tuple or len(draft.source_parents)!=len(source_parts)
                or draft.source_parents[0]!=root or any(_native_key(key)[0]!=root[0]
                    for key in (*existing,*draft.source_parents,draft.file.file_key))):
            raise TransferError('photo_relocation_invalid_folder_plan')
        for parts,keys in ((source_parts,draft.source_parents),(target_parts,existing)):
            path='/'.join(parts).casefold()
            if path in paths:raise TransferError('photo_relocation_selection_collision')
            paths.add(path)
            for end in range(1,len(parts)):
                prefix='/'.join(parts[:end]);identity=keys[end] if end<len(keys) else None
                old=prefixes.setdefault(prefix.casefold(),(prefix,identity))
                if old!=(prefix,identity):raise TransferError('photo_relocation_parent_changed')
        members.append(draft)
    if paths.intersection(prefixes):raise TransferError('photo_relocation_selection_collision')
    members=tuple(sorted(members,key=lambda member:member.source))
    bodies=[dict(operation=member.operation,book=member.book_sha256,preferences=member.preferences_sha256,
        mapping=member.original_mapping_sha256,source=member.source,source_parents=[list(key) for key in member.source_parents],
        target=member.target,existing=[list(key) for key in member.target_parents.existing],missing=list(member.target_parents.missing),
        file=dict(file_key=list(member.file.file_key),size=member.file.size,sha256=member.file.sha256)) for member in members]
    digest=sha256(b'magnolie-gif-folder-plan-v1\0'+canonical(dict(destination=destination.wire(),members=bodies))).hexdigest()
    return GifRelocationFolderPlan(members,digest)


def inspect_relocation_target_parents(destination,relative,current):
    """Read the longest safe named prefix and verify the first absent name."""
    from magnolie_photo_destination import require_media_directory
    if type(destination) is not NativeAcceptedDestination or not callable(current):
        raise TransferError('photo_relocation_original_destination_required')
    parts=_portable_path(relative).split('/')[:-1]
    require_media_directory(destination.path+'/'+relative)
    def require_current():
        if current() is not True:raise TransferError('photo_relocation_original_owner_ended')
    def directory(info):
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o022
                or info.st_dev!=destination.ancestor_keys[0][0]):
            raise TransferError('photo_relocation_unsafe_parent')
        return info.st_dev,info.st_ino
    with ExitStack() as close:
        def open_dir(path,*,dir_fd=None):
            fd=os.open(path,_DIRECTORY_FLAGS,dir_fd=dir_fd);close.callback(os.close,fd);return fd
        require_current();destination.verify();root=open_dir(destination.path)
        existing=[directory(os.fstat(root))]
        if existing[0]!=destination.ancestor_keys[0]:raise TransferError('photo_relocation_root_changed')
        names=[];parent=root;missing=()
        for index,name in enumerate(parts):
            require_current();_require_unique_target_name(parent,name)
            try:child=open_dir(name,dir_fd=parent)
            except FileNotFoundError:
                missing=tuple(parts[index:]);break
            identity=directory(os.fstat(child));existing.append(identity)
            names.append((parent,name,child,identity));parent=child
        require_current();destination.verify()
        for ancestor,name,child,identity in names:
            _require_unique_target_name(ancestor,name)
            if (directory(os.stat(name,dir_fd=ancestor,follow_symlinks=False))!=identity
                    or directory(os.fstat(child))!=identity):
                raise TransferError('photo_relocation_parent_changed')
        if missing:
            _require_unique_target_name(parent,missing[0])
            try:os.stat(missing[0],dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:pass
            else:raise TransferError('photo_relocation_parent_changed')
        require_current();return RelocationTargetParentObservation(tuple(existing),missing)


def _native_key(value):
    if (type(value) is not tuple or len(value)!=2 or not value[1]
            or any(type(part) is not int or not 0<=part<2**64 for part in value)):
        raise TransferError('photo_relocation_invalid_identity')
    return value


@dataclass(frozen=True)
class RelocationFileWitness:
    """Observed on a bound local descriptor. Not the historical Saved digest."""
    file_key: tuple
    size: int
    sha256: str

    def __post_init__(self):
        _native_key(self.file_key)
        if type(self.size) is not int or not 1<=self.size<=MAX_FILE_BYTES or not _hex(self.sha256):
            raise TransferError('photo_relocation_invalid_file_witness')


@dataclass(frozen=True)
class MediaRelocationRecord:
    operation: str
    selection_sha256: str
    book_sha256: str
    preferences_sha256: str
    original_mapping_sha256: str
    root_key: tuple
    source_parents: tuple
    target_parents: tuple
    source: str
    target: str
    file: RelocationFileWitness
    phase: str = 'prepared'

    def __post_init__(self):
        if (type(self.operation) is not str or len(self.operation)!=32 or not _hex(self.operation*2)
                or any(not _hex(value) for value in (self.selection_sha256,self.book_sha256,
                    self.preferences_sha256,self.original_mapping_sha256)) or type(self.file) is not RelocationFileWitness
                or type(self.phase) is not str or self.phase not in ('prepared','moved','canceled')):
            raise TransferError('photo_relocation_invalid_record')
        _native_key(self.root_key)
        source_path=_portable_path(self.source);target_path=_portable_path(self.target)
        for path,parents in ((source_path,self.source_parents),(target_path,self.target_parents)):
            if type(parents) is not tuple or len(parents)!=len(path.split('/')) or parents[0]!=self.root_key:
                raise TransferError('photo_relocation_invalid_endpoints')
            for key in parents:_native_key(key)
            if len(set(parents))!=len(parents):raise TransferError('photo_relocation_invalid_endpoints')
        for key in (*self.source_parents,*self.target_parents,self.file.file_key):
            if _native_key(key)[0]!=self.root_key[0]:raise TransferError('photo_relocation_cross_device')
        if (source_path.casefold()==target_path.casefold() or source_path.rsplit('/',1)[-1]!=target_path.rsplit('/',1)[-1]
                or self.source_parents[-1]==self.target_parents[-1]):
            raise TransferError('photo_relocation_invalid_endpoints')

    @property
    def grants_write_authority(self):return False

    @property
    def is_saved_receipt(self):return False

    def wire(self):
        return dict(format=1,operation=self.operation,selection_sha256=self.selection_sha256,book_sha256=self.book_sha256,
            preferences_sha256=self.preferences_sha256,original_mapping_sha256=self.original_mapping_sha256,
            root_key=list(self.root_key),source_parents=[list(key) for key in self.source_parents],
            target_parents=[list(key) for key in self.target_parents],
            source=self.source,target=self.target,file_key=list(self.file.file_key),size=self.file.size,sha256=self.file.sha256,phase=self.phase)

    @classmethod
    def parse(cls,body):
        names=('operation','selection_sha256','book_sha256','preferences_sha256','original_mapping_sha256',
            'source','target','phase')
        keys=('root_key','file_key');chains=('source_parents','target_parents')
        if (type(body) is not dict or set(body)!=set(names+keys+chains+('format','size','sha256'))
                or type(body['format']) is not int or body['format']!=1 or any(type(body[key]) is not list for key in keys+chains)
                or any(not 1<=len(body[key])<=16 or any(type(part) is not list for part in body[key]) for key in chains)):
            raise TransferError('photo_relocation_invalid_record')
        values={key:tuple(body[key]) for key in keys}
        values.update({key:tuple(tuple(part) for part in body[key]) for key in chains})
        witness=RelocationFileWitness(values.pop('file_key'),body['size'],body['sha256'])
        return cls(**{name:body[name] for name in names},**values,file=witness)

    def observe(self, *, root_key, source_parents, target_parents, source, target):
        """Classify observations; None is allowed only for a proved absent name.

        The native caller must fail closed on any unreadable/linked endpoint or
        uncertain stat. Do not turn inability to read into absent (None).
        """
        if (root_key,source_parents,target_parents)!=(self.root_key,self.source_parents,self.target_parents):
            return 'held'
        if type(source) is RelocationFileWitness and source==self.file and target is None:return 'at_source'
        if source is None and type(target) is RelocationFileWitness and target==self.file:return 'at_target'
        return 'held'

    def terminal_candidate(self, phase, **observations):
        """Exact transition candidate, not proof that directories were synced."""
        if type(phase) is not str or phase not in ('canceled','moved') or self.phase!='prepared':
            raise TransferError('photo_relocation_invalid_transition')
        if self.observe(**observations)!=('at_target' if phase=='moved' else 'at_source'):
            raise TransferError('photo_relocation_original_location_unproven')
        return replace(self,phase=phase)

    def observe_native(self, destination, current, *, require_animation=False):
        """Read pinned endpoints. Never create, rename, recover or sync anything."""
        return self._observe_native(destination,current,require_animation=require_animation,durable_phase=None)

    def sync_terminal_evidence(self,destination,current,phase):
        """Flush the same held directories after readback, without moving a file."""
        if self.phase!='prepared' or phase not in ('moved','canceled'):
            raise TransferError('photo_relocation_invalid_transition')
        return self._observe_native(destination,current,require_animation=False,durable_phase=phase)

    def require_moved_location(self,destination,current):
        """Verify the anchored inode's location, not its current content.

        A later edit to that same inode must be evaluated against the immutable
        saved digest by the content reader, not mistaken for a different path.
        """
        if self.phase!='moved':raise TransferError('photo_relocation_outcome_required')
        if self._observe_native(destination,current,require_animation=False,durable_phase=None,location_only=True)!='at_target':
            raise TransferError('photo_relocation_original_location_unproven')

    def _rename_prepared_animation(self,destination,current):
        """Only the native journal calls this after spending the exact attempt."""
        if self.phase!='prepared':raise TransferError('photo_relocation_invalid_transition')
        self._observe_native(destination,current,require_animation=True,durable_phase=None,rename=True)

    def _observe_native(self,destination,current,*,require_animation,durable_phase,location_only=False,rename=False,
            preview_animation=False):
        if (type(destination) is not NativeAcceptedDestination or destination.ancestor_keys[0]!=self.root_key
                or not callable(current) or type(require_animation) is not bool):
            raise TransferError('photo_relocation_original_destination_required')
        if preview_animation and (not require_animation or durable_phase is not None or location_only or rename
                or self.phase!='prepared' or self.selection_sha256!='0'*64):
            raise TransferError('photo_relocation_invalid_preview')
        if require_animation:
            from magnolie_media_mime import ANIMATION_PROOF_BYTES, verified_gif_animation
            if not preview_animation and self.file.size>ANIMATION_PROOF_BYTES:
                raise TransferError('photo_relocation_animation_unproven')
        directory_flags=_DIRECTORY_FLAGS
        def require_current():
            if current() is not True:raise TransferError('photo_relocation_original_owner_ended')
        def key(value):return value.st_dev,value.st_ino
        def directory(value):
            if (not stat.S_ISDIR(value.st_mode) or value.st_uid!=os.geteuid() or value.st_mode&0o022
                    or value.st_dev!=self.root_key[0]):
                raise TransferError('photo_relocation_unsafe_parent')
            return key(value)
        def signature(value):
            return key(value),value.st_size,value.st_mode,value.st_uid,value.st_gid,value.st_nlink,value.st_mtime_ns,value.st_ctime_ns
        def named(parent,name):
            try:return os.stat(name,dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:return None
        with ExitStack() as close:
            def track(fd):close.callback(os.close,fd);return fd
            require_current();destination.verify()
            root=track(os.open(destination.path,directory_flags))
            if directory(os.fstat(root))!=self.root_key:raise TransferError('photo_relocation_root_changed')
            held=[];target_names=[]
            def parent_for(relative,expected,*,target_path=False):
                *parts,leaf=relative.split('/');parent=root
                for part,identity in zip(parts,expected[1:]):
                    if target_path:
                        _require_unique_target_name(parent,part)
                        target_names.append((parent,part))
                    require_current();fd=track(os.open(part,directory_flags,dir_fd=parent))
                    if directory(os.fstat(fd))!=identity:raise TransferError('photo_relocation_parent_changed')
                    held.append((parent,part,fd,identity));parent=fd
                if target_path:
                    _require_unique_target_name(parent,leaf)
                    target_names.append((parent,leaf))
                return parent,leaf
            source=parent_for(self.source,self.source_parents);target=parent_for(self.target,self.target_parents,target_path=True)
            ends=[]
            payloads={}
            def inspect(endpoint):
                require_current();parent,leaf=endpoint;before=named(parent,leaf)
                if before is None:
                    ends.append((endpoint,None));return None
                if preview_animation and endpoint==target:
                    raise TransferError('photo_relocation_original_location_unproven')
                variable_size=preview_animation or location_only
                if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or before.st_nlink!=1
                        or key(before)!=self.file.file_key or not (1<=before.st_size<=MAX_FILE_BYTES if variable_size else before.st_size==self.file.size)):
                    raise TransferError('photo_relocation_original_file_changed')
                if preview_animation and (before.st_size>ANIMATION_PROOF_BYTES or before.st_mode&0o077):
                    raise TransferError('photo_relocation_animation_unproven')
                opened=track(os.open(leaf,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent))
                exact=signature(before)
                if signature(os.fstat(opened))!=exact:raise TransferError('photo_relocation_original_file_changed')
                if location_only:
                    ends.append((endpoint,exact));return True
                # Read the verified descriptor rather than reopening a raced name.
                fd=track(os.open('/proc/self/fd/'+str(opened),os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK))
                if signature(os.fstat(fd))!=exact:raise TransferError('photo_relocation_original_file_changed')
                if rename:payloads[endpoint]=fd
                digest=sha256();remaining=before.st_size; animation=bytearray() if require_animation else None
                while remaining:
                    require_current();raw=os.read(fd,min(remaining,1024*1024))
                    if not raw:raise TransferError('photo_relocation_original_file_changed')
                    digest.update(raw);remaining-=len(raw)
                    if animation is not None:animation.extend(raw)
                if os.read(fd,1) or signature(os.fstat(fd))!=exact:
                    raise TransferError('photo_relocation_original_file_changed')
                observed=RelocationFileWitness(key(before),before.st_size,digest.hexdigest())
                if animation is not None:
                    require_current()
                    if (not preview_animation and observed!=self.file) or not verified_gif_animation(bytes(animation)):
                        raise TransferError('photo_relocation_animation_unproven')
                    require_current()
                ends.append((endpoint,exact));return observed
            observed_source,observed_target=inspect(source),inspect(target)
            def recheck():
                require_current();destination.verify()
                for parent,name in target_names:_require_unique_target_name(parent,name)
                for parent,part,fd,expected in held:
                    value=named(parent,part)
                    if value is None or directory(value)!=expected or directory(os.fstat(fd))!=expected:
                        raise TransferError('photo_relocation_parent_changed')
                for endpoint,expected in ends:
                    value=named(*endpoint)
                    if (signature(value) if value is not None else None)!=expected:
                        raise TransferError('photo_relocation_original_file_changed')
                require_current()
            witnessed=dict(root_key=self.root_key,source_parents=self.source_parents,target_parents=self.target_parents,
                source=observed_source,target=observed_target)
            recheck()
            if preview_animation:
                if type(observed_source) is not RelocationFileWitness or observed_target is not None:
                    raise TransferError('photo_relocation_original_location_unproven')
                return replace(self,file=observed_source)
            if rename:
                from magnolie_media_trash import _move_no_replace
                if self.observe(**witnessed)!='at_source':raise TransferError('photo_relocation_original_location_unproven')
                # No overwrite, cross-volume copy, or compensating removal.
                # A concurrent external namespace edit may leave uncertainty;
                # only the exact same inode at the target can be credited.
                os.fsync(payloads[source])
                recheck()
                _move_no_replace(source[0],source[1],target[1],target_parent=target[0])
                ends.clear()
                observed_source,observed_target=inspect(source),inspect(target)
                recheck()
                if observed_source is not None or observed_target!=self.file:
                    raise TransferError('photo_relocation_original_location_unproven')
                return None
            if location_only:return 'at_target' if observed_source is None and observed_target is True else 'held'
            if durable_phase is None:return self.observe(**witnessed)
            candidate=self.terminal_candidate(durable_phase,**witnessed)
            os.fsync(source[0]);require_current();os.fsync(target[0]);recheck()
            return candidate


def preview_original_gif_relocation(mapping,accepted,history,receipt,*,operation,book_sha256,preferences_sha256,
        current_binding,require_original,_allow_missing_draft=False):
    """Read-only draft for a native caller holding the original protected job.

    Only plain original images and already existing safe destination parents
    qualify here. The current descriptor supplies the GIF bytes and digest;
    a historical classification or an edited inode's old digest is not proof.
    """
    from magnolie_photo_destination import plan_special_folder_path, require_media_directory, special_folder_origin
    from magnolie_photo_target import _require_receipt_context
    origin=special_folder_origin(accepted,history,mapping)
    _require_receipt_context(accepted,receipt,current_binding)
    if ((mapping.source_file_id,mapping.relative_path,mapping.parent_keys,mapping.file_key,mapping.saved_size,
            mapping.saved_sha256,mapping.receipt_sha256)!=(receipt.file_id,receipt.relative_path,receipt.parent_keys,
            receipt.file_key,receipt.size,receipt.sha256,receipt.protected_record_sha256)):
        raise TransferError('photo_relocation_original_receipt_changed')
    if history.media_type!='images' or origin.was_animation or origin.was_capture or not callable(require_original):
        raise TransferError('photo_relocation_original_layout_required')
    def current():
        if require_original() is not True:raise TransferError('photo_relocation_original_owner_ended')
        accepted.verify(current_binding)
        return True
    # This only derives a name to investigate. The descriptor below must prove
    # an actual animation before a draft is returned.
    target=plan_special_folder_path(origin.original_path,origin.mapped_path,was_animation=False,was_capture=False,
        verified_animation=True,verified_capture=False,setting='animation',separate=True)
    destination=accepted.destination;root=Path(destination.path)
    require_media_directory(root/origin.mapped_path);require_media_directory(root/target)
    parents=inspect_relocation_target_parents(destination,target,current)
    if parents.missing:
        if not _allow_missing_draft:raise TransferError('photo_relocation_target_parents_missing')
        from magnolie_media_mime import ANIMATION_PROOF_BYTES, verified_gif_animation
        from magnolie_media_source import NativeMappedMediaSource
        source=inspect_relocation_target_parents(destination,origin.mapped_path,current)
        if source.missing or source.existing!=mapping.parent_keys:
            raise TransferError('photo_relocation_original_location_unproven')
        with NativeMappedMediaSource._file(mapping,current) as (fd,size,signature,unchanged):
            if size>ANIMATION_PROOF_BYTES or signature[2]&0o077:
                raise TransferError('photo_relocation_animation_unproven')
            raw=os.pread(fd,size+1,0)
            if len(raw)!=size or not verified_gif_animation(raw):
                raise TransferError('photo_relocation_animation_unproven')
            if (inspect_relocation_target_parents(destination,target,current)!=parents
                    or inspect_relocation_target_parents(destination,origin.mapped_path,current)!=source):
                raise TransferError('photo_relocation_parent_changed')
            unchanged()
            return MissingGifTargetDraft(operation,book_sha256,preferences_sha256,origin.mapping_sha256,
                destination,origin.mapped_path,source.existing,target,parents,
                RelocationFileWitness(mapping.file_key,size,sha256(raw).hexdigest()))
    draft=MediaRelocationRecord(operation,'0'*64,book_sha256,preferences_sha256,origin.mapping_sha256,
        destination.ancestor_keys[0],mapping.parent_keys,parents.existing,origin.mapped_path,target,
        RelocationFileWitness(mapping.file_key,mapping.saved_size,mapping.saved_sha256))
    return draft._observe_native(destination,current,require_animation=True,durable_phase=None,preview_animation=True)


def bind_relocation_selection(records, *, occupied):
    """Freeze an entire candidate set; ``occupied`` comes from native preflight.

    No chain move frees a name. Even when an entire batch is eligible, the
    later owner must still acquire the exact destination and recheck no-replace.
    """
    if (type(records) is not tuple or not 1<=len(records)<=128 or type(occupied) is not tuple
            or len(occupied)>10000 or any(type(record) is not MediaRelocationRecord or record.phase!='prepared' for record in records)):
        raise TransferError('photo_relocation_invalid_selection')
    first=records[0]
    if any((item.operation,item.book_sha256,item.preferences_sha256,item.root_key)!=
            (first.operation,first.book_sha256,first.preferences_sha256,first.root_key) for item in records):
        raise TransferError('photo_relocation_foreign_selection_member')
    if len({item.original_mapping_sha256 for item in records})!=len(records) or len({item.file.file_key for item in records})!=len(records):
        raise TransferError('photo_relocation_duplicate_original')
    sources={item.source.casefold() for item in records}
    targets={item.target.casefold() for item in records}
    blocked=sources | {_portable_path(path).casefold() for path in occupied}
    if len(sources)!=len(records) or len(targets)!=len(records) or targets & blocked:
        raise TransferError('photo_relocation_selection_collision')
    # A target must also not occupy a directory needed by any other target.
    for target in targets:
        parts=target.split('/')
        if any('/'.join(parts[:end]) in targets or '/'.join(parts[:end]) in blocked for end in range(1,len(parts))):
            raise TransferError('photo_relocation_selection_collision')
    ordered=sorted(records,key=lambda item:item.source)
    bodies=[item.wire() for item in ordered]
    for body in bodies:del body['selection_sha256']
    digest=sha256(b'magnolie-special-folder-selection-v1\0'+canonical(bodies)).hexdigest()
    return tuple(replace(item,selection_sha256=digest) for item in ordered)
