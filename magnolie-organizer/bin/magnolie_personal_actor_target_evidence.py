"""Private outgoing off-scope tombstone evidence, NOT transport/data authority.

Deliberately not connected to a controller/capability. A future caller must bind
incoming evidence, typed choices and separate receipt/scope semantics on both
peers before any historical target is admitted. No data membership is returned.
"""
import copy

import magnolie_content_scope as scope
import magnolie_personal_actor as actor
from magnolie_personal_actor_producer import prepare_deletion_proposals
from magnolie_personal_actor_store import NativeProducerBookSnapshot


class NativeOutgoingTargetEvidence:
    """Exact current pending removals under fresh native owner/source/book gates.

    Observers are native closures, never IPC arguments or cached caller receipts.
    Reusing a historical acknowledgment without a current tombstone is useless.
    This object cannot read/queue/send data, change selection or create an ACK.
    """
    def __init__(self, peer_id, run_id, *, current_owner, current_source, current_snapshot, current_scope):
        actor.start(peer_id); actor.start(run_id)
        if not all(callable(value) for value in (current_owner, current_source, current_snapshot, current_scope)):
            raise TypeError('Fresh native target observations are required')
        self._owner, self._source = current_owner, current_source
        self._snapshot, self._scope = current_snapshot, current_scope
        self._run_id, self._peer_id = run_id, peer_id
        if current_owner() is not True:
            raise PermissionError('actor_target_owner_changed')
        self._source_revision = current_source()
        if not isinstance(self._source_revision, str) or len(self._source_revision) != 64 or any(c not in '0123456789abcdef' for c in self._source_revision):
            raise PermissionError('actor_target_source_changed')
        snapshot = current_snapshot()
        if not isinstance(snapshot, NativeProducerBookSnapshot):
            raise PermissionError('actor_target_native_book_missing')
        self._book_binding = (snapshot.saved_book, snapshot.content_sha256)
        self._before = copy.deepcopy(current_scope()); scope.validate(self._before)
        book = snapshot.book()
        notes, tasks = set(self._before['members']['notes']), set(self._before['members']['tasks'])
        for key, meta in book.get('personalSync', {}).get('entities', {}).items():
            if not isinstance(meta, dict) or meta.get('state') != 'deleted' or meta.get('status') != 'local_pending':
                continue
            parts = key.split('\0')
            if len(parts) == 2 and parts[0] in ('note', 'task'):
                (notes if parts[0] == 'note' else tasks).add(parts[1])
            elif len(parts) == 3 and parts[0] == 'attachment':
                notes.add(parts[1])
        # A local validation-only index, NEVER an accepted content scope or a
        # controller session. Existing producer validation independently checks
        # actual absence, canonical aliases, peer, parent and proposal identity.
        index = scope.create(sorted(notes), sorted(tasks))
        bodies = prepare_deletion_proposals(snapshot, index, peer_id, run_id,
            current_saved_book=lambda: self._checked_snapshot().saved_book,
            current_source=self._checked_source)
        self._targets = {}
        for body in bodies:
            for proposal in body['proposals']:
                selected = proposal['parent_id'] in self._before['members']['notes'] if proposal['kind'] == 'attachment' else \
                    proposal['id'] in self._before['members']['notes' if proposal['kind'] == 'note' else 'tasks']
                if not selected:
                    target = {key: copy.deepcopy(proposal[key]) for key in ('proposal_id', 'kind', 'id', 'parent_id', 'prior_hash', 'clock')}
                    self._targets[target['proposal_id']] = target
        self._check_current()

    def _checked_source(self):
        if self._owner() is not True:
            raise PermissionError('actor_target_owner_changed')
        if self._source() != self._source_revision:
            raise PermissionError('actor_target_source_changed')
        if self._scope() != self._before:
            raise PermissionError('actor_target_scope_changed')
        return self._source_revision

    def _checked_snapshot(self):
        snapshot = self._snapshot()
        if not isinstance(snapshot, NativeProducerBookSnapshot) or (snapshot.saved_book, snapshot.content_sha256) != self._book_binding:
            raise PermissionError('actor_target_book_changed')
        return snapshot

    def _check_current(self):
        self._checked_source(); self._checked_snapshot(); self._checked_source()

    def targets(self):
        self._check_current()
        return copy.deepcopy(sorted(self._targets.values(), key=lambda value: value['proposal_id']))

    def require_exact(self, run_id, target):
        self._check_current()
        if run_id != self._run_id or not isinstance(target, dict) or self._targets.get(target.get('proposal_id')) != target:
            raise PermissionError('actor_target_proof_changed')
        return True
