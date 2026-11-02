"""Private current local restore-source observation, never save/data authority.

The native caller owns the source/writer guard for the complete bounded operation.
Source bytes stay operation-local; only their bound hash/opaque trash identity
are returned. No accepted batch or peer attachment lookup is available here.
"""
import copy

import magnolie_personal_sync as personal
from magnolie_native_book_json import book_hash
from magnolie_personal_actor_producer import _note_wire_id, _attachment_id
from magnolie_personal_actor_target_evidence import NativeIncomingLiveTargetObservation


def _text(value, default=''):
    if value is None or value == '':
        return default
    if not isinstance(value, str):
        raise ValueError('invalid_native_restore_source')
    return value


def _number(value, default=0):
    if value is None or value == '' or value == 0:
        return default
    if type(value) is not int or not -9007199254740991 <= value <= 9007199254740991:
        raise ValueError('invalid_native_restore_source')
    return value


def _projection(book, kind, identifier, entry, meta, wire_format):
    state = book['personalSync']
    value = {'title': _text(entry.get('titel')), 'created_ms': _number(entry.get('angelegt')),
        'modified_ms': _number(meta.get('modified_ms'))}
    if kind == 'note':
        notebook = _text(entry.get('notizbuchId'), 'notizbuch-lose-notizen')
        notebook = _note_wire_id(notebook, {'note_ids': state.get('notebook_ids', {}), 'note_aliases': state.get('notebook_aliases', {})})
        value.update(text=_text(entry.get('text')), html=_text(entry.get('html')), notebook_id=notebook,
            symbol=_text(entry.get('symbol'), 'notiz'))
        attachments = entry.get('anhaenge', [])
        if not isinstance(attachments, list) or len(attachments) > 64:
            raise ValueError('invalid_native_restore_source')
        descriptors = []
        for attachment in attachments:
            descriptor, raw = personal.attachment_descriptor(attachment)
            descriptor['attachment_id'] = _attachment_id(identifier, descriptor['attachment_id'], state)
            descriptors.append(descriptor)
            del raw
        value['attachments'] = descriptors
    else:
        for field in ('erledigt', 'erinnern'):
            if entry.get(field) is not None and type(entry[field]) is not bool:
                raise ValueError('invalid_native_restore_source')
        value.update(note=_text(entry.get('notiz')), due=_text(entry.get('faellig')), priority=_number(entry.get('prio'), 2),
            completed=entry.get('erledigt') is True, remind=entry.get('erinnern') is True,
            lead_days=_number(entry.get('individuelleErinnerungTage') or entry.get('vorlaufTage')),
            reminder_minute=_number(entry.get('erinnerungsMinute'), 480) if entry.get('erinnerungsMinute') != 0 else 0,
            uid=_text(entry.get('uid')), parent_uid=_text(entry.get('elternUid')), order=max(0, _number(entry.get('reihenfolge'))))
    if wire_format == 14:
        origin = entry.get('ursprungApp', '')
        value['origin_app'] = origin if origin in ('notes', 'organizer') else ''
    return value


class NativeHistoricalRestoreSourceObservation(NativeIncomingLiveTargetObservation):
    """One fresh native book/group capture; no retained source content or writer.

    The wire format must come from the protected native run, not a peer claim.
    This deliberately supports only matching pending note/task local restores.
    """
    def __init__(self, peer_id, run_id, wire_format, **observations):
        if type(wire_format) is not int or wire_format not in (3, 14):
            raise ValueError('actor_historical_restore_format')
        self._wire_format = wire_format
        super().__init__(peer_id, run_id, **observations)

    def _observe_target(self, run_id, target, book):
        observation = super()._observe_target(run_id, target, book)
        kind, identifier = target['kind'], target['id']
        if kind not in ('note', 'task') or observation['local_state'] != 'deleted' or not observation['metadata_matches']:
            raise PermissionError('actor_historical_restore_target_not_ready')
        state = book['personalSync']; meta = state['entities'][kind + '\0' + identifier]
        pieces = [piece for piece in book.get('papierkorb', []) if piece.get('art') == kind and
            isinstance(piece.get('eintrag'), dict) and (piece['eintrag'].get('id') == identifier if kind == 'task' else
                _note_wire_id(piece['eintrag'].get('id'), state) == identifier)]
        if len(pieces) != 1:
            raise PermissionError('restore_unavailable')
        piece = pieces[0]; entry = piece['eintrag']
        if (not isinstance(piece.get('id'), str) or not piece['id'] or
                sum(value.get('id') == piece['id'] for value in book.get('papierkorb', [])) != 1 or
                (bool(entry.get('baumQuelle')) and entry.get('persoenlichVerknuepft') is not True if kind == 'note' else
                 any(entry.get(field) for field in ('vonZweig', 'fremdId', 'delegiertAn', 'herkunft')))):
            raise PermissionError('restore_unavailable')
        if kind == 'note' and any(key.startswith('attachment\0' + identifier + '\0') and value.get('state') == 'deleted'
                for key, value in state['entities'].items()):
            raise PermissionError('actor_historical_child_review_required')
        if personal.projection_hash(_projection(book, kind, identifier, entry, meta, self._wire_format)) != meta['prior_hash']:
            raise PermissionError('restore_unavailable')
        result = copy.deepcopy(observation)
        result.update(local_restore_source={'trash_id': piece['id'], 'sha256': book_hash(piece)}, action_authorized=False)
        return result
