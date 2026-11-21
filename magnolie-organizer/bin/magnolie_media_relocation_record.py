"""Local special-folder journal record and read-only recovery observation.

The codec is not persistence, a filesystem operation or a permission. An
authenticated native journal must bind it to the original action before use.
"""
from dataclasses import dataclass, replace
from contextlib import ExitStack
from hashlib import sha256
import os
import stat

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import _hex
from magnolie_file_transfer import MAX_FILE_BYTES, TransferError, _portable_path
from magnolie_telefon import canonical


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

    def _observe_native(self,destination,current,*,require_animation,durable_phase):
        if (type(destination) is not NativeAcceptedDestination or destination.ancestor_keys[0]!=self.root_key
                or not callable(current) or type(require_animation) is not bool):
            raise TransferError('photo_relocation_original_destination_required')
        if require_animation:
            from magnolie_media_mime import ANIMATION_PROOF_BYTES, verified_gif_animation
            if self.file.size>ANIMATION_PROOF_BYTES:raise TransferError('photo_relocation_animation_unproven')
        directory_flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
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
            held=[]
            def parent_for(relative,expected):
                *parts,leaf=relative.split('/');parent=root
                for part,identity in zip(parts,expected[1:]):
                    require_current();fd=track(os.open(part,directory_flags,dir_fd=parent))
                    if directory(os.fstat(fd))!=identity:raise TransferError('photo_relocation_parent_changed')
                    held.append((parent,part,fd,identity));parent=fd
                return parent,leaf
            source=parent_for(self.source,self.source_parents);target=parent_for(self.target,self.target_parents)
            ends=[]
            def inspect(endpoint):
                require_current();parent,leaf=endpoint;before=named(parent,leaf)
                if before is None:
                    ends.append((endpoint,None));return None
                if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or before.st_nlink!=1
                        or key(before)!=self.file.file_key or before.st_size!=self.file.size):
                    raise TransferError('photo_relocation_original_file_changed')
                opened=track(os.open(leaf,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent))
                exact=signature(before)
                if signature(os.fstat(opened))!=exact:raise TransferError('photo_relocation_original_file_changed')
                # Read the verified descriptor rather than reopening a raced name.
                fd=track(os.open('/proc/self/fd/'+str(opened),os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK))
                if signature(os.fstat(fd))!=exact:raise TransferError('photo_relocation_original_file_changed')
                digest=sha256();remaining=self.file.size; animation=bytearray() if require_animation else None
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
                    if observed!=self.file or not verified_gif_animation(bytes(animation)):
                        raise TransferError('photo_relocation_animation_unproven')
                    require_current()
                ends.append((endpoint,exact));return observed
            observed_source,observed_target=inspect(source),inspect(target)
            def recheck():
                require_current();destination.verify()
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
            if durable_phase is None:return self.observe(**witnessed)
            candidate=self.terminal_candidate(durable_phase,**witnessed)
            os.fsync(source[0]);require_current();os.fsync(target[0]);recheck()
            return candidate


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
