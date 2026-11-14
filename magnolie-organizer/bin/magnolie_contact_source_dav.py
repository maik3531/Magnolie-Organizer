"""Native session approvals and bound-update DAV factory; not a sync scheduler.

No document deserializer, create/delete/export, persistent consent or local
baseline commit. Callers provide real native book/lifetime/codec/protection gates.
"""
import copy
from dataclasses import dataclass, field
import re
import threading
from types import MappingProxyType
import urllib.parse

from magnolie_nextcloud import NextcloudDav, source_id, validate_server


@dataclass(frozen=True)
class NativeDavSourceApproval:
    source: str
    href: str
    account_revision: str = field(repr=False)
    require_current: object = field(repr=False)


def _account(store):
    settings, present, revision, error = store.read_snapshot(interactive=False)
    if error is not None:
        raise error
    if (not settings or settings.get('davAktiv') is not True or not present or not revision or
            settings.get('kontoArt', 'nextcloud') not in ('nextcloud', 'generic-dav')):
        raise PermissionError('contact_source_account_not_available')
    return settings, revision


def _source_matches(settings, source, href):
    if not isinstance(source, str) or not isinstance(href, str):
        return False
    try:
        configured = urllib.parse.urlsplit(validate_server(settings['server']))
        target = urllib.parse.urlsplit(href)
        origin = lambda value: (value.scheme, value.hostname, value.port or 443)
        return (origin(configured) == origin(target) and target.scheme == 'https' and _safe_path(href) and
                target.username is None and target.password is None and not target.query and not target.fragment and
                source == source_id('addressbook', href, settings.get('kontoArt', 'nextcloud')))
    except (ValueError, TypeError):
        return False


def _safe_path(url):
    path = urllib.parse.urlsplit(url).path
    decoded = urllib.parse.unquote(path)
    return (not any(part in ('.', '..') for part in decoded.split('/')) and '\\' not in decoded and '\0' not in decoded and
            not re.search('%(?:2f|5c)', path, re.I) and not re.search('%[0-9a-f]{2}', decoded, re.I))


class NativeDavApprovalScope:
    """Default-empty, native book/account/session-only explicit decision scope."""
    def __init__(self, current_saved_book, account_store):
        if not callable(current_saved_book):
            raise TypeError('Native saved-book observation required')
        self._current_book, self._store = current_saved_book, account_store
        self._lock = threading.RLock()
        self._generation = 0
        self._grants = {}
        self._owner = self._revision = None

    def revoke(self):
        with self._lock:
            self._grants.clear()
            self._owner = self._revision = None
            self._generation += 1

    def _retain_current(self):
        if not self._grants:
            return
        book = self._current_book()
        if not book or book.get('book_source') != self._owner:
            self.revoke()
            return
        try:
            _, revision = _account(self._store)
        except Exception:
            revision = None
        if self._grants and revision != self._revision:
            self.revoke()

    def configure(self, native_catalog, ask_native_user):
        if not callable(ask_native_user):
            raise TypeError('Explicit native user decision required')
        book = copy.deepcopy(self._current_book())
        if not book:
            raise PermissionError('contact_source_book_not_saved')
        settings, revision = _account(self._store)
        choices = [copy.deepcopy(item) for item in native_catalog if isinstance(item, dict) and
            item.get('art') == 'addressbook' and item.get('canUpdate') is True and not item.get('readOnly') and
            _source_matches(settings, item.get('uid'), item.get('href'))]
        if len({item['uid'] for item in choices}) != len(choices):
            raise ValueError('contact_source_approval_catalog_ambiguous')
        with self._lock:
            self._retain_current()
            generation, selected = self._generation, tuple(self._grants)
        # None is cancel; an explicit empty selection revokes all. The callback
        # must be a native decision UI, never renderer data or "all writable".
        answer = ask_native_user(tuple(MappingProxyType(item) for item in choices), selected)
        with self._lock:
            if self._generation != generation or self._current_book() != book or _account(self._store)[1] != revision:
                raise PermissionError('contact_source_approval_context_changed')
            if answer is None:
                return False
            if not isinstance(answer, (list, tuple)) or any(not isinstance(value, str) for value in answer):
                raise ValueError('contact_source_approval_selection_invalid')
            ids = tuple(answer)
            lookup = {item['uid']: item['href'] for item in choices}
            if len(set(ids)) != len(ids) or any(value not in lookup for value in ids):
                raise ValueError('contact_source_approval_selection_invalid')
            self._grants = {value: lookup[value] for value in ids}
            self._owner, self._revision = book['book_source'], revision
            self._generation += 1
            return True

    def capture(self):
        with self._lock:
            self._retain_current()
            generation = self._generation
            def guard(source, href):
                with self._lock:
                    self._retain_current()
                    if generation != self._generation or self._grants.get(source) != href:
                        raise PermissionError('contact_source_explicit_approval_withdrawn')
            return tuple(NativeDavSourceApproval(source, href, self._revision,
                lambda source=source, href=href: guard(source, href)) for source, href in self._grants.items())


@dataclass(frozen=True)
class BoundDavContact:
    href: str
    etag: str
    wire: str = field(repr=False)
    native_uid: str = field(repr=False)
    content_sha256: str = field(repr=False)


class NativeBoundDavFactory:
    """One dedicated native connection; existing admitted bindings only."""
    def __init__(self, store, approval, bound_hrefs, require_book_current,
                 protect_before_mutation, observe_card, cancelled=None, transport=None):
        if (cancelled is not None and not callable(cancelled)) or type(approval) is not NativeDavSourceApproval or not all(callable(value) for value in
                (approval.require_current, require_book_current, protect_before_mutation, observe_card)):
            raise TypeError('Native approval/book/protection/codec callbacks required')
        self._store, self._approval = store, approval
        self._book, self._protect, self._observe = require_book_current, protect_before_mutation, observe_card
        self._cancelled = cancelled or (lambda: False)
        self._closed, self._observed, self._writing = False, {}, {}
        bound = tuple(bound_hrefs)
        if not bound or any(not isinstance(value, str) for value in bound) or len(set(bound)) != len(bound):
            raise ValueError('contact_source_original_binding_required')
        self._bound = frozenset(bound)
        if any(not _safe_path(value) or not value.startswith(approval.href.rstrip('/') + '/') for value in self._bound):
            raise ValueError('contact_source_original_binding_required')
        self._basic()
        self._client = store.checked_client(approval.account_revision, purpose='dav', transport=transport, interactive=False)
        try:
            if any(self._client.same_origin_url(value) != value for value in self._bound):
                raise ValueError('contact_source_original_binding_required')
            self._client.before_request = self._before_request
            self._dav = NextcloudDav(self._client)
            self.require_current()
        except BaseException:
            self.close()
            raise

    def _basic(self):
        if self._closed:
            raise PermissionError('contact_source_factory_closed')
        self._book()
        if self._cancelled():
            raise InterruptedError('contact_source_cancelled')
        self._approval.require_current()
        settings, revision = _account(self._store)
        if revision != self._approval.account_revision or not _source_matches(settings, self._approval.source, self._approval.href):
            raise PermissionError('contact_source_account_or_approval_changed')
        self._book()
        if self._cancelled():
            raise InterruptedError('contact_source_cancelled')
        if self._closed:
            raise PermissionError('contact_source_factory_closed')

    def _before_request(self, method, url, headers):
        self._basic()
        if not (method == 'PROPFIND' or method == 'REPORT' and url == self._approval.href or
                method == 'GET' and url in self._bound or method == 'PUT' and url in self._writing and
                headers.get('If-Match') == self._writing[url] and 'If-None-Match' not in headers):
            raise PermissionError('contact_source_update_only_route_required')

    def require_current(self):
        self._basic()
        sources = self._dav.collections('addressbook')
        self._basic()
        matches = [item for item in sources if item['uid'] == self._approval.source]
        if len(matches) != 1 or matches[0]['href'] != self._approval.href or matches[0].get('canUpdate') is not True:
            raise PermissionError('contact_source_update_not_currently_allowed')

    def _card(self, href, etag, wire):
        uid, digest = self._observe(wire)
        if (not isinstance(uid, str) or not uid or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or
                not isinstance(etag, str) or re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag) is None):
            raise ValueError('contact_source_original_identity_or_revision_missing')
        return BoundDavContact(href, etag, wire, uid, digest)

    def read_bound(self):
        self._observed.clear()  # A failed fresh read must not leave old writable receipts.
        self.require_current()
        rows = self._dav.report(self._approval.href, 'addressbook')
        self.require_current()
        selected = [item for item in rows if item['href'] in self._bound]
        if len(selected) != len(self._bound) or len({item['href'] for item in selected}) != len(self._bound):
            raise ValueError('contact_source_original_record_missing_or_ambiguous')
        observed = {item['href']: self._card(item['href'], item['etag'], item['data']) for item in selected}
        self._observed = observed
        return tuple(observed.values())

    def update_existing(self, original, wire):
        self._basic()
        if type(original) is not BoundDavContact or self._observed.get(original.href) != original:
            raise PermissionError('contact_source_fresh_original_required')
        desired = self._card(original.href, original.etag, wire)
        if desired.native_uid != original.native_uid:
            raise PermissionError('contact_source_original_uid_required')
        self.require_current()
        self._protect()
        self.require_current()
        self._observed.pop(original.href, None)  # No blind reuse after an uncertain attempt.
        self._writing[original.href] = original.etag
        try:
            receipt = self._dav.put(original.href, wire, etag=original.etag, create=False)
            actual = {item.href: item for item in self.read_bound()}[original.href]
            if (not receipt or receipt.strip() == '*' or actual.etag != receipt or
                    actual.native_uid != original.native_uid or actual.content_sha256 != desired.content_sha256):
                raise ValueError('contact_source_write_readback_changed')
            return actual  # Verified native source state, never a local-save ACK/baseline commit.
        except BaseException:
            self._observed.pop(original.href, None)
            raise
        finally:
            self._writing.pop(original.href, None)

    def close(self):
        self._closed = True
        self._observed.clear()
        self._writing.clear()
        self._client.password = ''
