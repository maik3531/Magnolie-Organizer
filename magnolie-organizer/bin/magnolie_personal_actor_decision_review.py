"""Native post-data decision review/save claim; no document writes or wire ACKs.

Only a native controller may supply the protected original producer targets,
ordinary report receipt and fresh source/scope/writer observations. Neither this
object nor received metadata creates target authority. Registry ownership and
both TTLs remain separate mandatory gates in every caller.
"""
import copy
import hashlib
import secrets

import magnolie_personal_actor as actor
import magnolie_content_scope as scope
import magnolie_personal_sync as personal
from magnolie_personal_actor_completion import DecisionAckCompletion, NativeBookProofPending, HEX


class PostDataDecisionReview:
    def __init__(self, run_id, native_targets, before_scope, report_id, report_ack, *,
                 current_authority, current_scope, current_saved_book, persisted_controls,
                 native_fixed_targets=None, fixed_decision_frames=None):
        actor.start(run_id); actor.start(report_id)
        if not all(callable(value) for value in (current_authority, current_scope, current_saved_book, persisted_controls)):
            raise TypeError('Native post-data observations are required')
        if not isinstance(native_targets, list) or not 1 <= len(native_targets) <= 256:
            raise ValueError('invalid_actor_review_targets')
        self.run_id = run_id
        self.targets = copy.deepcopy(native_targets)
        # Validate exact target/parent/clock identities independently of choices.
        dummy = [{'proposal_id': value['proposal_id'], 'decision': 'restore', 'expected_clock': value['clock']} for value in self.targets]
        actor.completion_members(run_id, before_scope, self.targets, dummy)
        self.expected = {value['proposal_id']: value for value in self.targets}
        self.before = copy.deepcopy(before_scope)
        # Native-only initial choices already adopted by the ordinary SaveACK.
        # They participate in result-scope/receipt binding, NEVER in the late
        # mutation list. Controllers must supply protected original frames and
        # their exact native target proofs, not frontend-authored choices.
        self.fixed_targets = copy.deepcopy([] if native_fixed_targets is None else native_fixed_targets)
        self.fixed_frames = {}
        self.fixed_decisions = []
        if (not isinstance(self.fixed_targets, list) or
                fixed_decision_frames is not None and not isinstance(fixed_decision_frames, list) or
                len(self.targets) + len(self.fixed_targets) > 256):
            raise ValueError('invalid_actor_fixed_review_targets')
        for wire in fixed_decision_frames or []:
            if not isinstance(wire, dict) or wire.get('kind') != actor.DATA_KIND:
                raise ValueError('invalid_actor_fixed_review_frame')
            actor.start(wire.get('message_id'))
            kind, fixed_body = actor.unwrap(wire.get('body'))
            if (kind != 'personal_sync.deletion_decision' or fixed_body['run_id'] != run_id or
                    wire['message_id'] in self.fixed_frames):
                raise ValueError('invalid_actor_fixed_review_frame')
            self.fixed_frames[wire['message_id']] = copy.deepcopy(wire)
            self.fixed_decisions.extend(copy.deepcopy(fixed_body['decisions']))
        if len(self.fixed_frames) > 256:
            raise ValueError('invalid_actor_fixed_review_frame')
        actor.completion_members(run_id, self.before, self.fixed_targets, self.fixed_decisions)
        # Reject overlapping proposals/entity identities and incompatible parent
        # directions even before the actual late decisions have all arrived.
        actor.completion_members(run_id, self.before, self.targets + self.fixed_targets, dummy + self.fixed_decisions)
        if not isinstance(report_ack, dict) or report_ack.get('kind') != actor.ACK_KIND:
            raise PermissionError('actor_data_report_ack_required')
        body = report_ack.get('body'); actor.validate_ack(body)
        if body['run_id'] != run_id or body['message_id'] != report_id or body['status'] not in ('accepted', 'duplicate'):
            raise PermissionError('actor_data_report_ack_required')
        self.report_ack = copy.deepcopy(report_ack)
        self.current_authority = current_authority
        self.current_scope = current_scope
        self.current_saved_book = current_saved_book
        self.persisted_controls = persisted_controls
        self.authority = current_authority()
        if not isinstance(self.authority, str) or HEX.fullmatch(self.authority) is None:
            raise PermissionError('actor_decision_review_not_ready')
        self.before_saved = DecisionAckCompletion._checked_saved_book(current_saved_book())
        self.claim = None
        self.saved = None
        self.saved_scope = None
        self.saved_frames = None
        self.validator = self.validate  # Stable native callback identity.

    def _decision(self, wire):
        if not isinstance(wire, dict) or wire.get('kind') != actor.DATA_KIND:
            raise ValueError('unexpected_actor_review_control')
        actor.start(wire.get('message_id'))
        kind, body = actor.unwrap(wire.get('body'))
        if kind != 'personal_sync.deletion_decision' or body['run_id'] != self.run_id:
            raise ValueError('unexpected_actor_review_control')
        for decision in body['decisions']:
            expected = self.expected.get(decision['proposal_id'])
            if expected is None or decision['expected_clock'] != expected['clock']:
                raise ValueError('actor_review_decision_changed')
        return body

    def _authority(self):
        authority = self.current_authority()
        if authority is None:
            return None
        return authority == self.authority

    def validate(self, operation, wire):
        if operation not in ('begin', 'put', 'read', 'maintain', 'handoff'):
            raise ValueError('actor_decision_review_metadata_only')
        if wire is not None:
            if operation != 'put':
                raise ValueError('unexpected_actor_review_control')
            self._decision(wire)
            if self.saved_frames is not None and self.saved_frames.get(wire['message_id']) != hashlib.sha256(personal.canonical(wire)).hexdigest():
                raise ValueError('actor_review_frame_changed_after_save')
        authority = self._authority()
        if authority is not True:
            return authority
        try:
            observed = DecisionAckCompletion._checked_saved_book(self.current_saved_book())
        except NativeBookProofPending:
            return None
        except PermissionError:
            return False
        if operation == 'handoff':
            if self.saved is None:
                return None
            if observed != self.saved:
                return False
            # Registry validators run inside an immediate transaction. Never
            # recursively read persisted_controls here. confirm_saved has frozen
            # its exact protected frame set; put now permits only exact replay.
            try:
                actual = self.current_scope()
                scope.validate(actual)
            except (PermissionError, NativeBookProofPending):
                return None
            except (ValueError, TypeError):
                return False
            return actual == self.saved_scope
        if observed == (self.saved or self.before_saved):
            return True
        # A matching in-flight reviewed save may be awaiting its explicit native
        # confirmation. Maintenance waits; it must not claim success or retire a
        # legitimate write just because confirmation and observation are split.
        if self.saved is None and self.claim is not None and self._matches_claim(observed):
            # Reading the protected decision set is necessary to verify the
            # claim after SaveACK; this is metadata access, never save success.
            return True if operation == 'read' else None
        return False

    def review(self, *, require_saved=True):
        if require_saved and self.validate('read', None) is not True:
            raise PermissionError('actor_decision_review_not_ready')
        frames = self.persisted_controls()
        if not isinstance(frames, list) or len(frames) > 256:
            raise ValueError('invalid_actor_review_controls')
        decisions, identities, wires = [], set(), {}
        for wire in frames:
            body = self._decision(wire)
            identifier = wire['message_id']
            if identifier in self.fixed_frames:
                raise ValueError('actor_review_frame_direction_collision')
            if identifier in wires:
                if wire != wires[identifier]:
                    raise ValueError('actor_review_frame_changed')
                continue
            wires[identifier] = copy.deepcopy(wire)
            for decision in body['decisions']:
                if decision['proposal_id'] in identities:
                    raise ValueError('actor_review_decision_duplicate')
                identities.add(decision['proposal_id']); decisions.append(copy.deepcopy(decision))
        if identities != set(self.expected):
            raise PermissionError('actor_producer_decisions_incomplete')
        actual = self.current_scope()
        actor.require_completion_scope(self.run_id, self.before, self.targets + self.fixed_targets,
            decisions + self.fixed_decisions, actual)
        decisions.sort(key=lambda value: value['proposal_id'])
        binding = {'run_id': self.run_id, 'targets': self.targets, 'decisions': decisions, 'scope': actual,
            'report_ack': self.report_ack, 'saved_before': self.before_saved,
            'frames': sorted((key, hashlib.sha256(personal.canonical(value)).hexdigest()) for key, value in wires.items())}
        if self.fixed_targets:
            binding['fixed_targets'] = self.fixed_targets
            binding['fixed_decisions'] = self.fixed_decisions
            binding['fixed_frames'] = sorted((key, hashlib.sha256(personal.canonical(value)).hexdigest()) for key, value in self.fixed_frames.items())
        revision = hashlib.sha256(personal.canonical(binding)).hexdigest()
        if self._authority() is not True or require_saved and self.validate('read', None) is not True:
            raise PermissionError('actor_decision_review_not_ready')
        result = {'revision': revision, 'decisions': decisions, 'scope': copy.deepcopy(actual),
            'frame_hashes': dict(binding['frames']), 'book_persisted': self.saved is not None}
        if self.fixed_targets:
            result.update(fixed_targets=copy.deepcopy(self.fixed_targets), fixed_decisions=copy.deepcopy(self.fixed_decisions),
                fixed_frame_hashes=dict(binding['fixed_frames']))
        return result

    def prepare_save(self, expected_revision, after_sha256):
        if not isinstance(after_sha256, str) or HEX.fullmatch(after_sha256) is None:
            raise ValueError('invalid_actor_review_save_hash')
        review = self.review()
        if review['revision'] != expected_revision:
            raise PermissionError('actor_review_revision_changed')
        if self.claim is None:
            self.claim = {'claim_token': secrets.token_hex(32), 'revision': review['revision'], 'after_sha256': after_sha256,
                'book_source': self.before_saved['book_source'], 'before_sequence': self.before_saved['sequence']}
        elif self.claim['revision'] != expected_revision or self.claim['after_sha256'] != after_sha256:
            raise PermissionError('actor_review_save_claim_changed')
        return dict(copy.deepcopy(self.claim), book_persisted=self.saved is not None)

    def _matches_claim(self, observed):
        return (observed['book_source'] == self.claim['book_source'] and observed['sequence'] > self.claim['before_sequence'] and
            observed['sha256'] == self.claim['after_sha256'])

    def confirm_saved(self, claim_token):
        if self.claim is None or not isinstance(claim_token, str) or not secrets.compare_digest(claim_token, self.claim['claim_token']):
            raise PermissionError('actor_review_save_claim_unavailable')
        if self._authority() is not True:
            raise PermissionError('actor_decision_review_not_ready')
        review = self.review(require_saved=False)
        if review['revision'] != self.claim['revision']:
            raise PermissionError('actor_review_revision_changed')
        observed = DecisionAckCompletion._checked_saved_book(self.current_saved_book())
        if not self._matches_claim(observed) or self.saved is not None and self.saved != observed:
            raise PermissionError('actor_review_save_proof_missing')
        if self._authority() is not True or self.current_saved_book() != observed:
            raise PermissionError('actor_review_save_outcome_unknown')
        self.saved = copy.deepcopy(observed)
        self.saved_scope = copy.deepcopy(review['scope'])
        self.saved_frames = copy.deepcopy(review['frame_hashes'])
        return {'book_persisted': True, 'save_sequence': observed['sequence'], 'book_sha256': observed['sha256'], 'phone_persisted': False}
