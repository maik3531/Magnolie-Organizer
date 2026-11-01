"""Native metadata-only owner established BEFORE sending the ordinary report.

This closes the race in which Notes acknowledges ordinary data and immediately
publishes the legitimate resulting deletion scope before a GUI roundtrip can
retire the old data source. The owner can persist only exact correlated controls
and send only the original immutable ordinary report. It cannot write/adopt a
book, acknowledge deletion success or re-enter the original data capability.
"""
import copy

import magnolie_personal_actor as actor
from magnolie_personal_actor_completion import HEX, DecisionAckCompletion
from magnolie_personal_actor_decision_review import PostDataDecisionReview


class PostDataReportOwner:
    def __init__(self, run_id, native_targets, before_scope, report_frame, data_saved_book, *, current_authority, persisted_controls, producer_frames=None,
                 native_fixed_targets=None, fixed_decision_frames=None):
        actor.start(run_id)
        if not callable(current_authority) or not callable(persisted_controls):
            raise TypeError('Native report owner observations are required')
        if not isinstance(native_targets, list) or not 1 <= len(native_targets) <= 256:
            raise ValueError('invalid_actor_review_targets')
        self.run_id = run_id
        self.targets = copy.deepcopy(native_targets)
        self.before = copy.deepcopy(before_scope)
        actor.completion_members(run_id, self.before, self.targets, [
            {'proposal_id': value['proposal_id'], 'decision': 'restore', 'expected_clock': value['clock']} for value in self.targets])
        self.expected = {value['proposal_id']: value for value in self.targets}
        if not isinstance(report_frame, dict) or report_frame.get('kind') != actor.DATA_KIND:
            raise ValueError('actor_ordinary_report_required')
        actor.start(report_frame.get('message_id'))
        kind, body = actor.unwrap(report_frame.get('body'))
        if (kind != 'personal_sync.report' or body['run_id'] != run_id or
                body['state'] != 'complete' or body['error'] != 'none'):
            raise ValueError('actor_ordinary_report_required')
        self.report = copy.deepcopy(report_frame)
        self.data_saved_book = DecisionAckCompletion._checked_saved_book(data_saved_book)
        if producer_frames is not None and (not isinstance(producer_frames, list) or not 1 <= len(producer_frames) <= 8):
            raise ValueError('invalid_actor_producer_frames')
        self.producer_ids = set()
        witnessed = set()
        for wire in producer_frames or []:
            actor.start(wire.get('message_id'))
            if wire.get('kind') != actor.DATA_KIND:
                raise ValueError('actor_producer_frame_changed')
            kind, proposals = actor.unwrap(wire.get('body'))
            if kind != 'personal_sync.deletion_proposals' or proposals['run_id'] != run_id or wire['message_id'] in self.producer_ids:
                raise ValueError('actor_producer_frame_changed')
            self.producer_ids.add(wire['message_id'])
            for value in proposals['proposals']:
                target = {key: value[key] for key in ('proposal_id', 'kind', 'id', 'parent_id', 'prior_hash', 'clock')}
                if target != self.expected.get(value['proposal_id']) or value['proposal_id'] in witnessed:
                    raise ValueError('actor_producer_frame_changed')
                witnessed.add(value['proposal_id'])
        if producer_frames and witnessed != set(self.expected):
            raise ValueError('actor_producer_frames_incomplete')
        self.fixed_targets, self.fixed_frames, self.fixed_decisions = PostDataDecisionReview.checked_fixed_evidence(
            run_id, self.before, self.targets, native_fixed_targets, fixed_decision_frames)
        if set(self.fixed_frames) & (self.producer_ids | {self.report['message_id']}):
            raise ValueError('actor_fixed_frame_direction_collision')
        self.fixed_sent = set()
        self.current_authority = current_authority
        self.persisted_controls = persisted_controls
        self.authority = current_authority()
        if not isinstance(self.authority, str) or HEX.fullmatch(self.authority) is None:
            raise PermissionError('actor_report_owner_not_ready')
        self.review = None
        self.validator = self.validate

    def _control(self, wire):
        if not isinstance(wire, dict):
            raise ValueError('unexpected_actor_report_control')
        if wire.get('kind') == actor.ACK_KIND:
            body = wire.get('body'); actor.validate_ack(body)
            if body['run_id'] != self.run_id or body['message_id'] not in self.producer_ids | set(self.fixed_frames) | {self.report['message_id']}:
                raise ValueError('unexpected_actor_report_control')
            return ('report_ack' if body['message_id'] == self.report['message_id'] else
                'fixed_decision_ack' if body['message_id'] in self.fixed_frames else 'producer_ack')
        if wire.get('kind') != actor.DATA_KIND:
            raise ValueError('unexpected_actor_report_control')
        kind, body = actor.unwrap(wire.get('body'))
        if kind != 'personal_sync.deletion_decision' or body['run_id'] != self.run_id:
            raise ValueError('unexpected_actor_report_control')
        for decision in body['decisions']:
            expected = self.expected.get(decision['proposal_id'])
            if expected is None or decision['expected_clock'] != expected['clock']:
                raise ValueError('actor_review_decision_changed')
        return 'decision'

    def validate(self, operation, wire):
        if operation not in ('begin', 'put', 'read', 'maintain', 'handoff', 'send_report', 'send_fixed_decision'):
            raise ValueError('actor_report_owner_metadata_only')
        current = self.current_authority()
        if current is None:
            return None
        if current != self.authority:
            return False
        if operation == 'send_report':
            if wire != self.report:
                raise ValueError('actor_ordinary_report_changed')
            # Notes may close its data owner as soon as this report arrives.
            # All initial decisions must actually have been sent first. Peer
            # success ACKs cannot be awaited here: Notes needs the report to save.
            return True if self.fixed_sent == set(self.fixed_frames) else None
        if operation == 'send_fixed_decision':
            if not isinstance(wire, dict) or self.fixed_frames.get(wire.get('message_id')) != wire:
                raise ValueError('actor_fixed_decision_frame_changed')
            return True  # Original ordinary-saved choice only, not a general send.
        if wire is not None:
            if operation != 'put':
                raise ValueError('unexpected_actor_report_control')
            kind = self._control(wire)
            if kind in ('report_ack', 'producer_ack', 'fixed_decision_ack'):
                return True  # Persistence only, not a deletion/book receipt.
        if self.review is not None:
            return self.review.validator(operation, wire)
        return None if operation == 'handoff' else True

    def record_successful_fixed_decision_send(self, wire):
        """Native post-I/O marker; caller must repeat registry/connection gates.

        Enqueue, MarkAttempt or an incoming peer ACK is not an actual send. This
        is deliberately not an IPC action or a caller-supplied saved Boolean.
        """
        if self.validate('send_fixed_decision', wire) is not True:
            raise PermissionError('actor_fixed_decision_send_not_ready')
        self.fixed_sent.add(wire['message_id'])

    def begin_review(self, *, current_scope, current_saved_book):
        """Call under a fresh native GUI writer proof, outside registry SQL.

        Only the actual protected ordinary-report ACK unlocks the separate review
        claim. This operation itself does not write the book or send a receipt.
        """
        if self.validate('read', None) is not True:
            raise PermissionError('actor_report_owner_not_ready')
        controls = self.persisted_controls()
        if not isinstance(controls, list):
            raise ValueError('invalid_actor_report_controls')
        acknowledgments = [wire for wire in controls if self._control(wire) == 'report_ack' and
            wire['body']['status'] in ('accepted', 'duplicate')]
        if not acknowledgments:
            raise PermissionError('actor_data_report_ack_required')
        if self.review is not None:
            return self.review
        if DecisionAckCompletion._checked_saved_book(current_saved_book()) != self.data_saved_book:
            raise PermissionError('actor_ordinary_saved_book_changed')
        def decisions():
            return [wire for wire in self.persisted_controls() if self._control(wire) == 'decision']
        review = PostDataDecisionReview(self.run_id, self.targets, self.before, self.report['message_id'], acknowledgments[0],
            current_authority=self.current_authority, current_scope=current_scope, current_saved_book=current_saved_book,
            persisted_controls=decisions, native_fixed_targets=self.fixed_targets, fixed_decision_frames=list(self.fixed_frames.values()))
        if self.current_authority() != self.authority:
            raise PermissionError('actor_report_owner_changed')
        if current_saved_book() != self.data_saved_book:
            raise PermissionError('actor_ordinary_saved_book_changed')
        self.review = review
        return review
