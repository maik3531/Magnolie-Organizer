"""Private off-scope native observations, NOT action/transport/data authority.

Deliberately not connected to a controller/capability. A future caller must bind
incoming evidence, typed choices and separate receipt/scope semantics on both
peers before any historical target is admitted. No data membership is returned.
"""
import copy

import magnolie_content_scope as scope
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
from magnolie_personal_actor_producer import prepare_deletion_proposals, _note_wire_id, _attachment_id
from magnolie_personal_actor_store import NativeProducerBookSnapshot


class _NativeTargetBinding:
    """Native closures under caller-held source/writer guard; never IPC receipts."""
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


class NativeOutgoingTargetEvidence(_NativeTargetBinding):
    """Exact current pending removals; NOT data/queue/send/ACK authority.

    Native closures must be operation-live, never retained/cached IPC inputs.
    The native caller must hold its source/writer guard for the whole operation.
    """
    def __init__(self, peer_id, run_id, **observations):
        super().__init__(peer_id, run_id, **observations)
        snapshot = self._checked_snapshot(); book = snapshot.book()
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

    def targets(self):
        self._check_current()
        return copy.deepcopy(sorted(self._targets.values(), key=lambda value: value['proposal_id']))

    def require_exact(self, run_id, target):
        self._check_current()
        if run_id != self._run_id or not isinstance(target, dict) or self._targets.get(target.get('proposal_id')) != target:
            raise PermissionError('actor_target_proof_changed')
        return True


class NativeIncomingLiveTargetObservation(_NativeTargetBinding):
    """Observe a current own live target, NOT permission to act on a proposal.

    Local metadata hash/clock are explicitly not asserted to be a recomputed
    content hash. The exact actual saved book is independently pinned. A future
    controller must still bind typed conflict choices and a fresh saved claim;
    this object cannot admit wire frames, change selection or perform a write.
    """
    def __init__(self, peer_id, run_id, **observations):
        super().__init__(peer_id, run_id, **observations)
        self._observed = {}
        self._identities = {}

    def observe(self, run_id, target):
        return self.observe_many(run_id, [target])[0]

    def observe_many(self, run_id, targets):
        self._check_current()
        if run_id != self._run_id:
            raise PermissionError('actor_target_proof_changed')
        if not isinstance(targets, list) or not 1 <= len(targets) <= 256:
            raise ValueError('actor_target_capacity')
        book = self._checked_snapshot().book()
        previous, identities = self._observed.copy(), self._identities.copy()
        result, seen = [], set()
        try:
            for target in targets:
                observation = self._observe_target(run_id, target, book)
                proposal_id = observation['target']['proposal_id']
                if proposal_id in seen:
                    raise ValueError('actor_target_duplicate_group')
                seen.add(proposal_id); result.append(observation)
            self._check_current()
        except Exception:
            self._observed, self._identities = previous, identities
            raise
        return result

    def _observe_target(self, run_id, target, book):
        if run_id != self._run_id or not isinstance(target, dict) or set(target) != {'proposal_id', 'kind', 'id', 'parent_id', 'prior_hash', 'clock'}:
            raise PermissionError('actor_target_proof_changed')
        personal.validate_body('personal_sync.deletion_proposals', {'format': 1, 'run_id': run_id,
            'proposal_batch_id': run_id, 'sequence': 0, 'last': True, 'proposals': [dict(target, deleted_ms=0, label='')]})
        kind, identifier, parent = target['kind'], target['id'], target['parent_id']
        if kind not in ('note', 'task', 'attachment'):
            raise PermissionError('actor_target_kind_not_supported')
        if (parent if kind == 'attachment' else identifier) in self._before['members']['tasks' if kind == 'task' else 'notes']:
            raise PermissionError('actor_target_already_in_content_scope')
        identity = (kind, parent, identifier)
        old = self._observed.get(target['proposal_id'])
        if old is not None and old['target'] != target or identity in self._identities and self._identities[identity] != target['proposal_id']:
            raise PermissionError('actor_target_proof_changed')
        if old is None and len(self._observed) >= 256:
            raise ValueError('actor_target_capacity')
        state = book.get('personalSync', {})
        key = kind + '\0' + (parent + '\0' if kind == 'attachment' else '') + identifier
        meta = state.get('entities', {}).get(key)
        if state.get('peer_device_id') != self._peer_id or not isinstance(meta, dict) or meta.get('peer_device_id') != self._peer_id or meta.get('state') != 'live':
            raise PermissionError('actor_target_live_native_proof_missing')
        if meta.get('parent_id', '') != parent or meta.get('conflict') is True or not isinstance(meta.get('hash'), str) or len(meta['hash']) != 64 or any(c not in '0123456789abcdef' for c in meta['hash']):
            raise PermissionError('actor_target_live_native_proof_missing')
        local_clock = personal.normalize_clock(meta.get('clock'))
        notes = [value for value in book.get('notizen', []) if _note_wire_id(value['id'], state) == (parent if kind == 'attachment' else identifier)]
        if kind == 'task':
            live = [value for value in book.get('aufgaben', []) if value.get('id') == identifier]
            own = len(live) == 1 and all(live[0].get(field) is None or live[0].get(field) is False or
                isinstance(live[0].get(field), str) and live[0][field] == '' for field in ('vonZweig', 'fremdId', 'delegiertAn', 'herkunft'))
        else:
            own = len(notes) == 1 and (not notes[0].get('baumQuelle') or notes[0].get('persoenlichVerknuepft') is True)
            if own and kind == 'attachment':
                own = sum(_attachment_id(parent, value['id'], state) == identifier for value in notes[0].get('anhaenge', [])) == 1
        if not own:
            raise PermissionError('actor_target_live_native_proof_missing')
        observed = {'target': copy.deepcopy(target), 'local_state': 'live', 'local_hash': meta['hash'],
            'local_clock': copy.deepcopy(local_clock), 'native_saved_book': copy.deepcopy(self._book_binding[0]),
            'metadata_matches': meta['hash'] == target['prior_hash'] and local_clock == target['clock'],
            'requires_conflict_choice': True}
        self._observed[target['proposal_id']] = observed
        self._identities[identity] = target['proposal_id']
        return copy.deepcopy(observed)
