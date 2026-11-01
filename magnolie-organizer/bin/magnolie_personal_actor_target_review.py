"""Private explicit historical-target choice drafts, NOT action/save/ACK rights.

Native callers supply protected original incoming frames and fresh operation-live
observations under their source/book guards. Neither a caller's observation JSON
nor this draft may replace incoming admission, a typed native save claim, exact
post-save result checks or the independent receipt union. No controller route or
wire readiness is enabled here.
"""
import copy
import hashlib

import magnolie_content_scope as scope
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
from magnolie_personal_actor_completion import DecisionAckCompletion, HEX


class NativeIncomingTargetChoiceReview:
    def __init__(self, run_id, *, current_frames, current_observations,
            current_authority, current_scope, current_saved_book):
        actor.start(run_id)
        if not all(callable(value) for value in (current_frames, current_observations,
                current_authority, current_scope, current_saved_book)):
            raise TypeError('Native protected target-review observations are required')
        self.run_id = run_id
        self._frames, self._observe = current_frames, current_observations
        self._authority, self._scope, self._saved = current_authority, current_scope, current_saved_book
        self.authority = current_authority()
        if not isinstance(self.authority, str) or HEX.fullmatch(self.authority) is None:
            raise PermissionError('actor_target_review_source_changed')
        self.before = copy.deepcopy(current_scope()); scope.validate(self.before)
        self.saved = DecisionAckCompletion._checked_saved_book(current_saved_book())
        self.targets, self.frame_hashes = self._original_frames()
        self._current()

    def _current(self):
        if self._authority() != self.authority:
            raise PermissionError('actor_target_review_source_changed')
        if self._scope() != self.before:
            raise PermissionError('actor_target_review_scope_changed')
        if DecisionAckCompletion._checked_saved_book(self._saved()) != self.saved:
            raise PermissionError('actor_target_review_book_changed')
        targets, hashes = self._original_frames()
        if targets != self.targets or hashes != self.frame_hashes:
            raise PermissionError('actor_target_review_frame_changed')

    def _original_frames(self):
        frames = self._frames()
        if not isinstance(frames, list) or not 1 <= len(frames) <= 256:
            raise ValueError('invalid_actor_target_review_frames')
        hashes, sequences, batch = {}, {}, None
        targets, identities, proposal_ids = [], set(), set()
        for wire in frames:
            if not isinstance(wire, dict) or wire.get('kind') != actor.DATA_KIND:
                raise ValueError('invalid_actor_target_review_frame')
            actor.start(wire.get('message_id'))
            kind, body = actor.unwrap(wire.get('body'))
            if kind != 'personal_sync.deletion_proposals' or body['run_id'] != self.run_id:
                raise ValueError('invalid_actor_target_review_frame')
            digest = hashlib.sha256(personal.canonical(wire)).hexdigest()
            if wire['message_id'] in hashes:
                if hashes[wire['message_id']] != digest:
                    raise ValueError('actor_target_review_frame_changed')
                continue
            if body['sequence'] in sequences or batch is not None and batch != body['proposal_batch_id']:
                raise ValueError('invalid_actor_target_review_group')
            hashes[wire['message_id']] = digest
            sequences[body['sequence']] = body['last']; batch = body['proposal_batch_id']
            for proposal in body['proposals']:
                target = {key: copy.deepcopy(proposal[key]) for key in ('proposal_id', 'kind', 'id', 'parent_id', 'prior_hash', 'clock')}
                identity = (target['kind'], target['parent_id'], target['id'])
                if target['kind'] not in ('note', 'task', 'attachment') or target['proposal_id'] in proposal_ids or identity in identities:
                    raise ValueError('ambiguous_actor_target_review_target')
                member = target['parent_id'] if target['kind'] == 'attachment' else target['id']
                if member in self.before['members']['tasks' if target['kind'] == 'task' else 'notes']:
                    raise PermissionError('actor_target_review_content_target')
                proposal_ids.add(target['proposal_id']); identities.add(identity); targets.append(target)
        if (not 1 <= len(targets) <= 256 or sorted(sequences) != list(range(len(sequences))) or
                any(last != (index == len(sequences) - 1) for index, last in sequences.items())):
            raise ValueError('invalid_actor_target_review_group')
        return sorted(targets, key=lambda value: value['proposal_id']), hashes

    def review(self):
        self._current()
        targets = copy.deepcopy(self.targets)
        # This callback must create a NEW native observation operation, not retain
        # an earlier observer with captured plaintext book/provider closures.
        observations = self._observe(copy.deepcopy(targets))
        expected = {target['proposal_id']: target for target in targets}
        checked = {}
        if not isinstance(observations, list) or len(observations) != len(targets):
            raise ValueError('invalid_actor_target_review_observations')
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) != {'target', 'local_state', 'local_hash', 'local_clock',
                    'native_saved_book', 'metadata_matches', 'requires_conflict_choice'}:
                raise ValueError('invalid_actor_target_review_observation')
            target = observation['target']
            if (not isinstance(target, dict) or not isinstance(target.get('proposal_id'), str) or
                    expected.get(target.get('proposal_id')) != target or target['proposal_id'] in checked or
                    observation['local_state'] != 'live' or observation['requires_conflict_choice'] is not True or
                    not isinstance(observation['local_hash'], str) or HEX.fullmatch(observation['local_hash']) is None or
                    type(observation['metadata_matches']) is not bool or observation['native_saved_book'] != self.saved):
                raise ValueError('invalid_actor_target_review_observation')
            clock = personal.normalize_clock(observation['local_clock'])
            if observation['metadata_matches'] != (observation['local_hash'] == target['prior_hash'] and clock == target['clock']):
                raise ValueError('invalid_actor_target_review_metadata')
            checked[target['proposal_id']] = copy.deepcopy(observation)
        binding = {'run_id': self.run_id, 'source': self.authority, 'saved_book': self.saved, 'content_scope': self.before,
            'frame_hashes': sorted(self.frame_hashes.items()), 'targets': targets,
            'observations': [checked[target['proposal_id']] for target in targets]}
        self._current()
        revision = hashlib.sha256(personal.canonical(binding)).hexdigest()
        return {'revision': revision, 'targets': copy.deepcopy(targets), 'observations': binding['observations'],
            'content_scope': copy.deepcopy(self.before), 'action_authorized': False}

    def draft_choices(self, expected_revision, choices):
        review = self.review()
        if expected_revision != review['revision']:
            raise PermissionError('actor_target_review_revision_changed')
        expected = {target['proposal_id']: target for target in self.targets}
        if not isinstance(choices, list) or len(choices) != len(expected):
            raise ValueError('actor_target_review_explicit_choices_required')
        decisions, seen = [], set()
        for choice in choices:
            if (not isinstance(choice, dict) or set(choice) != {'proposal_id', 'decision', 'expected_clock', 'confirm_conflict'} or
                    choice['confirm_conflict'] is not True or not isinstance(choice['proposal_id'], str) or
                    choice['proposal_id'] not in expected or choice['proposal_id'] in seen or
                    choice['expected_clock'] != expected[choice['proposal_id']]['clock']):
                raise ValueError('actor_target_review_explicit_choices_required')
            decision = {key: copy.deepcopy(choice[key]) for key in ('proposal_id', 'decision', 'expected_clock')}
            personal.validate_body('personal_sync.deletion_decision', {'format': 1, 'run_id': self.run_id,
                'decision_id': self.run_id, 'decisions': [decision]})
            seen.add(choice['proposal_id']); decisions.append(decision)
        decisions.sort(key=lambda value: value['proposal_id'])
        deleted_parents = {expected[value['proposal_id']]['id'] for value in decisions
            if value['decision'] == 'delete' and expected[value['proposal_id']]['kind'] == 'note'}
        if any(value['decision'] == 'restore' and expected[value['proposal_id']]['kind'] == 'attachment' and
                expected[value['proposal_id']]['parent_id'] in deleted_parents for value in decisions):
            raise ValueError('actor_target_review_parent_unavailable')
        self._current()
        # A local draft, deliberately not a native save token or an ACK receipt.
        binding = {'review_revision': expected_revision, 'decisions': decisions, 'conflicts_explicitly_confirmed': True,
            'content_scope': copy.deepcopy(self.before), 'action_authorized': False}
        return dict(binding, choice_revision=hashlib.sha256(personal.canonical(binding)).hexdigest())
