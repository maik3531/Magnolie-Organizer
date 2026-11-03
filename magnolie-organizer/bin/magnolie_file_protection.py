"""Read existing native telephone storage key without constructing PhoneStore.

No directory/key/settings/identity creation, migration or cleanup. The caller
supplies an already existing native private telephone directory, never a peer
path. Transfer cache encryption is separately domain-framed. Key/root changes
invalidate this instance; they are not silently adopted or repaired.
"""
from hashlib import sha256
import os
from pathlib import Path
import stat
import struct
import threading

from magnolie_file_transfer import TransferError


class ExistingFileTransferProtection:
    MAX_PLAIN_BYTES = 4 * 1024 * 1024
    MAX_DOMAIN_BYTES = 4096
    AAD_PREFIX = b"magnolie-file-transfer-protection-v1\0"

    def __init__(self, telephone_directory):
        self._gate = threading.RLock()
        self._root = Path(telephone_directory)
        if not self._root.is_absolute() or self._root.resolve(strict=True) != self._root:
            raise TransferError("transfer_protection_canonical_root_required")
        self._ancestors = [(path, self._key(os.lstat(path))) for path in (self._root, *self._root.parents)]
        self._root_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self._closed = False
        self._invalid = False
        self._original = None
        try:
            self._read_key()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _key(value):
        return value.st_dev, value.st_ino

    @staticmethod
    def _signature(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_uid,
            value.st_gid, value.st_nlink, value.st_mtime_ns, value.st_ctime_ns)

    def _directories(self):
        if self._closed:
            raise TransferError("transfer_protection_closed")
        for path, key in self._ancestors:
            value = os.lstat(path)
            if not stat.S_ISDIR(value.st_mode) or self._key(value) != key:
                raise TransferError("transfer_protection_root_changed")
        value = os.fstat(self._root_fd)
        if (self._key(value) != self._ancestors[0][1] or not stat.S_ISDIR(value.st_mode)
                or value.st_uid != os.geteuid() or value.st_mode & 0o077):
            raise TransferError("transfer_protection_unsafe_root")

    def _read_key(self):
        if self._invalid:
            raise TransferError("transfer_protection_native_reopen_required")
        try:
            return self._read_existing_key()
        except (OSError, TransferError):
            self._invalid = True
            raise

    def _read_existing_key(self):
        self._directories()
        fd = os.open("storage.key", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._root_fd)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_mode & 0o077
                    or before.st_nlink != 1 or before.st_size != 32):
                raise TransferError("transfer_protection_unsafe_or_corrupt_existing_key")
            raw = source.read(33)
            after = os.fstat(source.fileno())
            named = os.stat("storage.key", dir_fd=self._root_fd, follow_symlinks=False)
            if (len(raw) != 32 or self._signature(before) != self._signature(after)
                    or self._signature(named) != self._signature(after)):
                raise TransferError("transfer_protection_existing_key_changed")
        witness = self._key(before), sha256(raw).digest()
        if self._original is not None and self._original != witness:
            raise TransferError("transfer_protection_existing_key_changed")
        self._directories()
        self._original = witness
        return raw

    def _aad(self, domain):
        if type(domain) is not str:
            raise TransferError("transfer_protection_invalid_domain")
        raw = domain.encode("utf-8", errors="strict")
        if not 1 <= len(raw) <= self.MAX_DOMAIN_BYTES or "\0" in domain:
            raise TransferError("transfer_protection_invalid_domain")
        return self.AAD_PREFIX + struct.pack(">I", len(raw)) + raw

    def _crypt(self, data, domain, *, decrypt):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with self._gate:
            aad = self._aad(domain)
            if type(data) is not bytes or not (28 if decrypt else 0) <= len(data) <= self.MAX_PLAIN_BYTES + (28 if decrypt else 0):
                raise TransferError("transfer_protection_invalid_data_size")
            raw = self._read_key()
            cipher = AESGCM(raw)
            if decrypt:
                result = cipher.decrypt(data[:12], data[12:], aad)
            else:
                nonce = os.urandom(12)  # Per-record AEAD nonce, never a replacement storage key.
                result = nonce + cipher.encrypt(nonce, data, aad)
            # A native key removal/rotation during crypto cannot return usable
            # plaintext or permit a new protected record under stale authority.
            if self._read_key() != raw:
                raise TransferError("transfer_protection_existing_key_changed")
            return result

    def seal(self, plain, domain):
        return self._crypt(plain, domain, decrypt=False)

    def unseal(self, blob, domain):
        return self._crypt(blob, domain, decrypt=True)

    def read_native_peers_blob(self):
        """Fixed existing native peer metadata only; never identity.key/DB I/O.
        This intentionally does not invoke PhoneStore or its migrating loader.
        The different native AAD is fixed here, not selectable by a wire caller.
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with self._gate:
            raw=self._read_key()
            fd=os.open('peers.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._root_fd)
            with os.fdopen(fd,'rb') as source:
                before=os.fstat(source.fileno())
                if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or before.st_mode&0o077
                        or before.st_nlink!=1 or not 29<=before.st_size<=self.MAX_PLAIN_BYTES+28):
                    raise TransferError('file_authority_unsafe_native_peers')
                blob=source.read(self.MAX_PLAIN_BYTES+29)
                after=os.fstat(source.fileno())
                named=os.stat('peers.json',dir_fd=self._root_fd,follow_symlinks=False)
                if len(blob)!=before.st_size or self._signature(before)!=self._signature(after) or self._signature(named)!=self._signature(after):
                    raise TransferError('file_authority_native_peers_changed')
            result=AESGCM(raw).decrypt(blob[:12],blob[12:],b'magnolie-phone-storage-v1\0peersall')
            if self._read_key()!=raw:raise TransferError('transfer_protection_existing_key_changed')
            if self._signature(os.stat('peers.json',dir_fd=self._root_fd,follow_symlinks=False))!=self._signature(after):
                raise TransferError('file_authority_native_peers_changed')
            self._directories()
            return result

    def initialize_native_file_pairing(self, expected_peer, permitted, published):
        """Explicit native activation only, serialized by the owning service.

        Patch one CLOSED relationship field using the existing key and exact
        original ciphertext. Never use PhoneStore's migrating/full-list writer.
        A lost postcommit reply preserves this metadata, not a file grant.
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from magnolie_telefon import PhoneStore, canonical, strict_json
        from magnolie_file_control import DISCOVERY_VERSION, _hex
        import secrets
        if not callable(permitted) or not callable(published):
            raise TransferError('file_pairing_native_activation_required')
        with self._gate:
            def record():
                self._directories()
                fd=os.open('peers.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._root_fd)
                with os.fdopen(fd,'rb') as source:
                    before=os.fstat(source.fileno())
                    if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or before.st_mode&0o077
                            or before.st_nlink!=1 or not 29<=before.st_size<=self.MAX_PLAIN_BYTES+28):
                        raise TransferError('file_authority_unsafe_native_peers')
                    blob=source.read(self.MAX_PLAIN_BYTES+29)
                    after=os.fstat(source.fileno())
                    named=os.stat('peers.json',dir_fd=self._root_fd,follow_symlinks=False)
                    if len(blob)!=before.st_size or self._signature(before)!=self._signature(after) or self._signature(named)!=self._signature(after):
                        raise TransferError('file_pairing_native_peer_changed')
                    return blob,self._signature(after)
            key=self._read_key(); original=record()
            plain=AESGCM(key).decrypt(original[0][:12],original[0][12:],b'magnolie-phone-storage-v1\0peersall')
            value=strict_json(plain)
            if (type(value) is not dict or set(value)!={'storage_version','items'} or type(value['storage_version']) is not int
                    or value['storage_version']!=1 or type(value['items']) is not list or len(value['items'])!=1
                    or value['items'][0]!=expected_peer):
                raise TransferError('file_pairing_native_peer_changed')
            peer=value['items'][0]; PhoneStore._validate_peer(peer)
            personal=peer.get('personal_sync',{}); status=peer.get('capabilities',{}).get('items',{}).get('device_status',{})
            if (peer.get('state')!='paired' or personal.get('own_device') is not True or personal.get('remote_own_device') is not True
                    or status.get('available') is not True or DISCOVERY_VERSION not in status.get('versions',[])):
                raise TransferError('file_pairing_native_activation_required')
            def fresh(wanted):
                if not permitted() or self._read_key()!=key or record()!=wanted:
                    raise TransferError('file_pairing_native_activation_changed')
            fresh(original)
            if 'file_pairing_epoch' in peer:
                if not _hex(peer['file_pairing_epoch']):raise TransferError('file_pairing_invalid_epoch')
                return dict(peer)
            updated=dict(peer,file_pairing_epoch=secrets.token_hex(32))
            wanted=canonical(dict(value,items=[updated])); nonce=os.urandom(12)
            cipher=nonce+AESGCM(key).encrypt(nonce,wanted,b'magnolie-phone-storage-v1\0peersall')
            with os.scandir(self._root_fd) as entries:
                held=0
                for entry in entries:
                    if entry.name.startswith('peers.json.file-') and entry.name.endswith('.new'):
                        held+=1; attributes=entry.stat(follow_symlinks=False)
                        if held>=4 or not stat.S_ISREG(attributes.st_mode) or attributes.st_size>self.MAX_PLAIN_BYTES+28:
                            raise TransferError('file_pairing_native_staging_held')
            name='peers.json.file-'+secrets.token_hex(16)+'.new'
            fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self._root_fd)
            with os.fdopen(fd,'wb') as output:
                output.write(cipher);output.flush();os.fsync(output.fileno())
                staged=self._signature(os.fstat(output.fileno()))
                fresh(original)
                if (self._signature(os.fstat(output.fileno()))!=staged
                        or self._signature(os.stat(name,dir_fd=self._root_fd,follow_symlinks=False))!=staged):
                    raise TransferError('file_pairing_native_staging_changed')
                os.replace(name,'peers.json',src_dir_fd=self._root_fd,dst_dir_fd=self._root_fd)
                # Preserve metadata even if later durability/readback fails;
                # this callback creates no receive/data policy or read authority.
                published(dict(updated))
                os.fsync(self._root_fd)
            saved=record()
            if saved[0]!=cipher or self.read_native_peers_blob()!=wanted:
                raise TransferError('file_pairing_native_readback_failed')
            fresh(saved)
            return updated

    @property
    def native_directory(self):
        return str(self._root) # Existing canonical native root, never a wire path.

    @property
    def native_directory_identity(self):
        return self._ancestors[0][1] # Captured native inode witness, not authority.

    def close(self):
        with self._gate:
            if not self._closed:
                self._closed = True
                os.close(self._root_fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
