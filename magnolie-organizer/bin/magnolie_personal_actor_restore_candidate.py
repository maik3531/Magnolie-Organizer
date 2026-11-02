"""Independent native exact historical candidate validation, never a save cap.

The controller must additionally bind authenticated origin/choice revision and
retire its data owner before a real writer. This operation retains metadata only;
it cannot import peer content, write a book, open data scope or acknowledge wire.
"""
import copy
from dataclasses import dataclass, field
import hashlib
import json

import magnolie_personal_sync as personal
from magnolie_native_book_json import same_book
from magnolie_personal_actor_producer import _note_wire_id
from magnolie_personal_actor_restore_source import NativeHistoricalRestoreSourceObservation


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('actor_historical_candidate_duplicate_key')
        result[key] = value
    return result


def _live(book):
    state = book['personalSync']
    notes = [_note_wire_id(value['id'], state) for value in book.get('notizen', [])
        if not value.get('baumQuelle') or value.get('persoenlichVerknuepft') is True]
    tasks = [value['id'] for value in book.get('aufgaben', [])
        if not any(value.get(key) for key in ('vonZweig', 'fremdId', 'delegiertAn', 'herkunft'))]
    if len(notes) != len(set(notes)) or len(tasks) != len(set(tasks)):
        raise ValueError('actor_historical_live_identity_ambiguous')
    return {'notes': sorted(notes), 'tasks': sorted(tasks)}


@dataclass(frozen=True)
class NativeHistoricalRestoreCandidateProof:
    """Metadata-only prepared-delta evidence, never wire-supplied authority."""
    source_revision: str = field(repr=False)
    book_source: str = field(repr=False)
    before_sequence: int = field(repr=False)
    before_sha256: str = field(repr=False)
    before_content_sha256: str = field(repr=False)
    after_sha256: str = field(repr=False)
    after_content_sha256: str = field(repr=False)
    before_scope: tuple = field(repr=False)
    before_live: tuple = field(repr=False)
    after_live: tuple = field(repr=False)
    target_revision: str = field(repr=False)
    source_revision_hash: str = field(repr=False)

    @classmethod
    def prepare(cls, peer_id, run_id, wire_format, targets, choices, candidate_text, **observations):
        targets, choices = copy.deepcopy(targets), copy.deepcopy(choices)
        observer = NativeHistoricalRestoreSourceObservation(peer_id, run_id, wire_format, **observations)
        sources = observer.observe_many(run_id, targets)
        snapshot = observer._checked_snapshot()
        before = snapshot.book(); expected = copy.deepcopy(before); state = expected['personalSync']
        if (not isinstance(choices, list) or len(choices) != len(targets) or
                any(not isinstance(choice, dict) or set(choice) != {'proposal_id', 'decision', 'expected_clock', 'confirm_conflict'} for choice in choices)):
            raise ValueError('actor_historical_explicit_restore_required')
        indexed = {choice['proposal_id']: choice for choice in choices}
        if len(indexed) != len(choices) or set(indexed) != {target['proposal_id'] for target in targets}:
            raise ValueError('actor_historical_explicit_restore_required')
        for target in targets:
            choice = indexed[target['proposal_id']]
            if choice['decision'] != 'restore' or choice['confirm_conflict'] is not True or choice['expected_clock'] != target['clock']:
                raise ValueError('actor_historical_explicit_restore_required')
        before_live = _live(before)
        if before_live != observer._before['members']:
            raise PermissionError('actor_historical_live_selection_not_ready')
        counter = state.get('counter')
        if (type(counter) is not int or counter < 0 or counter + len(targets) > 9007199254740991 or
                len(state.get('applied_decisions', [])) + len(targets) > 500):
            raise ValueError('actor_historical_candidate_capacity')
        local_actor = state.get('actor_id', '')
        personal.normalize_clock([{'actor_id': local_actor, 'counter': counter + 1}])
        for target, source in zip(targets, sources):
            kind, identifier = target['kind'], target['id']
            key = kind + '\0' + identifier
            trash_id = source['local_restore_source']['trash_id']
            piece = next(value for value in expected['papierkorb'] if value['id'] == trash_id)
            entry = copy.deepcopy(piece['eintrag'])
            # The first exact native desktop lane supports root tasks only;
            # hierarchy-normalizing changes need their own complete graph proof.
            if kind == 'task' and entry.get('elternUid'):
                raise PermissionError('actor_historical_task_graph_not_ready')
            expected['notizen' if kind == 'note' else 'aufgaben'].append(entry)
            expected['papierkorb'] = [value for value in expected['papierkorb'] if value['id'] != trash_id]
            meta = state['entities'][key]; state['counter'] += 1
            clocks = {item['actor_id']: item['counter'] for item in meta['clock']}
            clocks[local_actor] = max(clocks.get(local_actor, 0), state['counter'])
            fresh_clock = personal.normalize_clock([{'actor_id': actor, 'counter': count} for actor, count in sorted(clocks.items())])
            if not any(item['counter'] > next((old['counter'] for old in target['clock'] if old['actor_id'] == item['actor_id']), 0) for item in fresh_clock):
                raise PermissionError('actor_historical_restore_clock_not_advanced')
            meta.update(clock=fresh_clock, state='live', status='restored', hash='', proposal_id='', acknowledged_by_peer=False)
            requests = state.get('restoration_requests', [])
            state['restoration_requests'] = list(dict.fromkeys(requests + [key]))
            if any(value.get('proposal_id') == target['proposal_id'] for value in state.get('applied_decisions', [])):
                raise PermissionError('actor_historical_candidate_replayed')
            state['applied_decisions'] = state.get('applied_decisions', []) + [{'proposal_id': target['proposal_id'], 'decision': 'restore',
                'expected_clock': copy.deepcopy(target['clock']), 'kind': kind, 'id': identifier, 'parent_id': ''}]
        if not isinstance(candidate_text, str) or len(candidate_text) > 256 * 1024 * 1024:
            raise ValueError('actor_historical_candidate_capacity')
        clear = candidate_text.encode('utf-8')
        if len(clear) > 256 * 1024 * 1024:
            raise ValueError('actor_historical_candidate_capacity')
        candidate = json.loads(candidate_text, object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('actor_historical_candidate_nonfinite')))
        # Exact JSON structure, including every unrelated entity/config/trash
        # field. A caller-selected hash alone cannot satisfy this comparison.
        if not same_book(candidate, expected):
            raise PermissionError('actor_historical_candidate_delta_changed')
        after_live = _live(candidate)
        wanted = {name: sorted(before_live[name] + [target['id'] for target in targets if target['kind'] == kind])
            for name, kind in (('notes', 'note'), ('tasks', 'task'))}
        if after_live != wanted:
            raise PermissionError('actor_historical_live_delta_changed')
        observer._check_current()
        return cls(observer._source_revision, snapshot.book_source, snapshot.sequence, snapshot.saved_sha256, snapshot.content_sha256,
            hashlib.sha256(clear).hexdigest(), hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest(),
            (observer._before['epoch'], observer._before['revision'], observer._before['scope_hash']),
            (tuple(before_live['notes']), tuple(before_live['tasks'])),
            (tuple(after_live['notes']), tuple(after_live['tasks'])),
            personal.projection_hash({'targets': targets, 'choices': choices}), personal.projection_hash({'sources': sources}))
