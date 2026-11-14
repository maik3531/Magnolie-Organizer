"""Notes full-return interoperability; no enabled source/transport capability.

The native Notes target hash is NOT a sorted document/renderer hash. Match its
existing KontaktSync projection/normalization before correlating a real pending
desktop request. This module alone cannot grant sources or issue a SaveACK.
"""
import hashlib
import hmac
import json
import unicodedata
from dataclasses import dataclass


def _frame_bytes(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


@dataclass(frozen=True)
class _FsOriginProof:
    peer: tuple
    own: tuple
    body_hash: bytes
    transport_id: str
    current: object


class NativeNotesFsOrigin:
    """Process-local actual FS1 origin, never a JSON source grant or save ACK."""
    def __init__(self, proof):
        self._proof = proof

    def _native(self):
        if type(self._proof) is not _FsOriginProof:
            raise PermissionError('notes_original_authenticated_origin_required')
        return self._proof

    def require_current(self, body, transport_id):
        proof = self._native()
        if (proof.current() is not True or transport_id != proof.transport_id or
                not hmac.compare_digest(hashlib.sha256(_frame_bytes(body)).digest(), proof.body_hash)):
            raise PermissionError('notes_original_authenticated_origin_changed')
        return proof.peer, proof.own


def _issue_notes_fs_origin(peer, own, body, transport_id, current):
    """Native issuer used only immediately after actual FS1 authenticated open.

    No bridge/deserializer calls this factory. The receive service supplies its
    pinned handshake identities and native stop/expiry/current-state callback.
    """
    result = NativeNotesFsOrigin(_FsOriginProof(tuple(peer), tuple(own),
        hashlib.sha256(_frame_bytes(body)).digest(), transport_id, current))
    result.require_current(body, transport_id)
    return result


def _native_text(value):
    if not isinstance(value, str) or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError('notes_original_text_required')
    return value


def _blank_char(char):
    # Kotlin Char.isWhitespace = Java isWhitespace OR isSpaceChar.
    return char in '\t\n\v\f\r\x1c\x1d\x1e\x1f' or unicodedata.category(char) in ('Zs', 'Zl', 'Zp')


def _trim(value):
    start, end = 0, len(value)
    while start < end and _blank_char(value[start]):
        start += 1
    while end > start and _blank_char(value[end - 1]):
        end -= 1
    return value[start:end]


def _distinct(values, key):
    seen, result = set(), []
    for value in values:
        identity = key(value)
        if identity not in seen:
            seen.add(identity)
            result.append(value)
    return result


def _escape_name(text):
    return text.replace('\\', '\\\\').replace('\r\n', '\\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def _root_lower(value):
    # Notes runs Java String ROOT casing, whose final-sigma context uses ROOT
    # word boundaries and its cased categories, not Python's Unicode lower().
    if 'Σ' not in value:
        return value.lower()
    def cased(char):
        number = ord(char)
        return unicodedata.category(char) in ('Ll', 'Lu', 'Lt') or number in (0x345, 0x37A) or any(
            start <= number <= end for start, end in ((0x2B0, 0x2B8), (0x2C0, 0x2C1), (0x2E0, 0x2E4),
                (0x1D2C, 0x1D61), (0x2160, 0x217F), (0x24B6, 0x24E9)))
    def kind(char):
        number = ord(char); category = unicodedata.category(char)
        cjk = number in (0x3005, 0x309D, 0x309E, 0x30FD, 0x30FE) or any(start <= number <= end
            for start, end in ((0x4E00, 0x9FA5), (0xF900, 0xFA2D), (0x3041, 0x3094), (0x30A1, 0x30FC), (0x3099, 0x309C)))
        return 'L' if (category.startswith('L') or category == 'Mc') and not cjk else 'N' if category.startswith('N') else ''
    def middle(char, previous, following):
        return previous == following and (previous == 'L' and (unicodedata.category(char) in ('Pd', 'Pc') or char in '\u00ad\u2027\"\'.') or
            previous == 'N' and char in '\"\',\u066b.')
    positions = [(index, char) for index, char in enumerate(value) if unicodedata.category(char) != 'Cf']
    chars = [char for _, char in positions]
    finals, index = set(), 0
    def unit_end(start):
        end = start + 1
        while end < len(chars) and unicodedata.category(chars[end]) in ('Mn', 'Me'):
            end += 1
        return end
    while index < len(chars):
        previous = kind(chars[index])
        if not previous:
            index += 1; continue
        start, end = index, unit_end(index)
        while end < len(chars):
            following = kind(chars[end])
            if following:
                previous = following; end = unit_end(end)
            elif end + 1 < len(chars) and middle(chars[end], previous, kind(chars[end + 1])):
                previous = kind(chars[end + 1]); end = unit_end(end + 1)
            else:
                break
        remaining = sum(cased(char) for char in chars[start:end]); before = 0
        for offset in range(start, end):
            is_cased = cased(chars[offset]); remaining -= is_cased
            if chars[offset] == 'Σ' and before and not remaining:
                finals.add(positions[offset][0])
            before += is_cased
        index = end
    return ''.join(('ς' if index in finals else 'σ') if char == 'Σ' else char.lower() for index, char in enumerate(value))


def notes_content_hash(content):
    """Hash an actual validated Notes contact projection, not source authority.

    Validation/admission must still reject invalid DTOs and unsupported edits;
    this reproduces the native content fingerprint, including legacy projection.
    """
    scalar = ('vorname', 'nachname', 'firma', 'notiz', 'geburtstag', 'jubilaeum', 'anzeigename', 'foto')
    allowed = set(scalar) | {'vcardName', 'telefone', 'emailEintraege', 'anschriften', 'gruppen'}
    if not isinstance(content, dict) or set(content) - allowed:
        raise ValueError('notes_original_projection_required')
    text = {name: _native_text(content.get(name, '')) for name in scalar}
    def text_list(name):
        values = content.get(name, [])
        if not isinstance(values, list):
            raise ValueError('notes_original_list_required')
        return [_native_text(value) for value in values]
    names = text_list('vcardName')
    def rows(name, fields):
        values = content.get(name, [])
        if not isinstance(values, list):
            raise ValueError('notes_original_list_required')
        if any(not isinstance(value, dict) or set(value) != set(fields) for value in values):
            raise ValueError('notes_original_row_required')
        return [{field: _native_text(value[field]) for field in fields} for value in values]
    phones = rows('telefone', ('art', 'wert'))
    emails = rows('emailEintraege', ('art', 'wert'))
    postal = rows('anschriften', ('art', 'strasse', 'plz', 'ort', 'region', 'land'))
    # Kotlin filters UTF-16 Char values: astral digits/superscripts are not BMP Nd.
    def phone_key(value):
        return ''.join(char for char in value['wert'] if char == '+' or ord(char) <= 0xFFFF and unicodedata.category(char) == 'Nd').lstrip('+')
    phones = _distinct([value for value in phones if _trim(value['wert'])], phone_key)
    emails = _distinct([value for value in emails if _trim(value['wert'])], lambda value: _root_lower(_trim(value['wert'])))
    def postal_key(value):
        return '|'.join(_root_lower(_trim(value[field])) for field in ('strasse', 'plz', 'ort', 'region', 'land'))
    postal = _distinct([value for value in postal if _trim(postal_key(value))], postal_key)
    groups = None
    if content.get('gruppen') is not None:
        groups = _distinct([unicodedata.normalize('NFC', _trim(value)) for value in text_list('gruppen') if _trim(value)], _root_lower)
        groups.sort(key=lambda value: value.encode('utf-16-be'))
    fn = ' '.join(value for value in (text['vorname'], text['nachname']) if value)
    n = 'N:' + _escape_name(text['nachname']) + ';' + _escape_name(text['vorname']) + ';;;'
    legacy = not text['jubilaeum'] and text['anzeigename'] in ('', fn) and all(value in (n, 'FN:' + _escape_name(fn)) for value in names)
    result = {name: text[name] for name in ('vorname', 'nachname', 'firma', 'notiz', 'geburtstag')}
    if groups is not None or not legacy:
        result.update(jubilaeum=text['jubilaeum'], anzeigename=text['anzeigename'], vcardName=names)
    if text['foto']:
        result['foto'] = text['foto']
    if groups is not None:
        result['gruppen'] = groups
    result.update(telefone=phones, emailEintraege=emails, anschriften=postal)
    return hashlib.sha256(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
