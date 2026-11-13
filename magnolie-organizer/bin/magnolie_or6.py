"""Bounded, read-only Lotus Organizer 6 ccSTR import (#212).

Walk allocated blocks, never carve strings out of freed storage. Schema object
references bind every record to its collection; field offsets remain inside
their owning allocation. No Lotus binaries or native code are executed.
"""
from array import array
from datetime import datetime
import gettext
import re
import struct
import sys

# Library defaults are English; the application's selected catalog is injected.
_ = gettext.NullTranslations().gettext
MAGIC = b"\x30\x4b\x04\xb3"
MAX_BYTES = 32 * 1024 * 1024
MAX_BLOCKS = 250000
MAX_FIELDS = 512
REPEAT_TAG = 0xfefffff2
# Independently selected original-program KeyID0..14 and actual saved event fills.
PLANNER_COLORS = ("#ff0000", "#00c200", "#0000ff", "#ffff00", "#ff00ff", "#00ffff",
                  "#800000", "#008000", "#000080", "#808000", "#800080", "#008080",
                  "#808080", "#c0c0c0", "#000000")
_RTF_CONTROL = re.compile(r"([a-zA-Z]+)(-?\d{1,10})? ?")


def _invalid():
    return ValueError(_("The content is unreadable."))


def _wide(value):
    if len(value) % 2:
        raise _invalid()
    try:
        return value.decode("utf-16le", errors="strict")
    except UnicodeError as error:
        raise _invalid() from error


def _rtf(value):
    """Extract bounded plain text; skip RTF objects, pictures and destinations."""
    start = value.find(b"{\\rtf")
    if start < 0:
        if value.strip(b"\x00\xff\x02"):
            raise _invalid()
        return ""
    raw = value[start:].rstrip(b"\x00")
    if len(raw) > 1024 * 1024:
        raise _invalid()
    source = raw.decode("cp1252", errors="replace")
    stack, output = [], []
    skip, fallback, pending = False, 1, 0
    pos = 0
    destinations = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object",
                    "objdata", "filetbl", "header", "footer", "fldinst", "datastore"}
    while pos < len(source):
        char = source[pos]
        pos += 1
        if char == "{":
            if len(stack) >= 64:
                raise _invalid()
            stack.append((skip, fallback))
        elif char == "}":
            if not stack:
                raise _invalid()
            skip, fallback = stack.pop()
            if not stack:
                if source[pos:].strip("\r\n\x00"):
                    raise _invalid()
                break
        elif char == "\\":
            if pos >= len(source):
                raise _invalid()
            symbol = source[pos]
            if symbol in "\\{}":
                pos += 1
                if pending:
                    pending -= 1
                elif not skip:
                    output.append(symbol)
            elif symbol == "'":
                if not re.fullmatch(r"[0-9a-fA-F]{2}", source[pos+1:pos+3]):
                    raise _invalid()
                decoded = bytes([int(source[pos+1:pos+3], 16)]).decode("cp1252", errors="replace")
                pos += 3
                if pending:
                    pending -= 1
                elif not skip:
                    output.append(decoded)
            elif symbol == "*":
                skip = True
                pos += 1
            elif not symbol.isalpha():
                pos += 1
                if not skip and symbol in ("~", "_"):
                    output.append(" " if symbol == "~" else "-")
            else:
                match = _RTF_CONTROL.match(source, pos)
                if not match:
                    raise _invalid()
                word, number = match.groups()
                pos += len(match[0])
                if word in destinations:
                    skip = True
                elif word == "bin":
                    count = int(number or "-1")
                    if count < 0 or count > len(source)-pos:
                        raise _invalid()
                    pos += count
                elif word == "ansicpg" and number != "1252":
                    raise _invalid()
                elif word == "uc":
                    fallback = int(number or "1")
                    if not 0 <= fallback <= 16:
                        raise _invalid()
                elif word == "u" and not skip:
                    code = int(number or "0")
                    if not -32768 <= code <= 65535:
                        raise _invalid()
                    output.append(chr(code & 65535))
                    pending = fallback
                elif not skip and word in ("par", "line", "tab", "emdash", "endash", "bullet"):
                    output.append({"par": "\n", "line": "\n", "tab": "\t",
                                   "emdash": "—", "endash": "–", "bullet": "•"}[word])
        elif char not in "\r\n":
            if pending:
                pending -= 1
            elif not skip:
                output.append(char)
    if stack:
        raise _invalid()
    # RTF Unicode escapes represent UTF-16 code units, including surrogate pairs.
    try:
        return "".join(output).encode("utf-16le", "surrogatepass").decode("utf-16le").rstrip("\n")
    except UnicodeError as error:
        raise _invalid() from error


class _Document:
    def __init__(self, raw):
        if not isinstance(raw, (bytes, bytearray)) or len(raw) < 1024 or len(raw) > MAX_BYTES or len(raw) % 4 or raw[:4] != MAGIC:
            raise _invalid()
        words = array("H", raw)
        if sys.byteorder != "little":
            words.byteswap()
        decoded = array("H", (((word << 1) | (word >> 15)) & 65535 for word in words))
        if sys.byteorder != "little":
            decoded.byteswap()
        self.data = decoded.tobytes()
        self.blocks = {}
        offset = 0
        while offset < len(self.data):
            if offset + 12 > len(self.data) or len(self.blocks) >= MAX_BLOCKS:
                raise _invalid()
            tag, address, size = struct.unpack_from("<III", self.data, offset)
            if address != offset or size < 12 or size % 4 or size > len(self.data)-offset:
                raise _invalid()
            self.blocks[offset] = (tag, size)
            offset += size
        if self.blocks.get(0) != (0x66099660, 1024):
            raise _invalid()
        self.schemas = {}
        self.schema_names = {}
        for address, (tag, size) in self.blocks.items():
            if tag != 0xffffffff:
                continue
            if size < 0x48:
                raise _invalid()
            key = self.reference(address + 12)
            if key in self.schemas:
                raise _invalid()
            self.schemas[key] = (self.u32(address + 0x2c), self._schema_fields(address))
            if self.schemas[key][0] == 0x200 and size >= 0xc8:
                try:
                    self.schema_names[key] = _wide(self.data[address+0x48:address+0xc8]).split("\0")[0]
                except ValueError:
                    pass  # Unreadable optional metadata is not a guessed label.

    def u32(self, offset):
        return struct.unpack_from("<I", self.data, offset)[0]

    def reference(self, offset):
        return struct.unpack_from("<II", self.data, offset)

    def _schema_fields(self, owner):
        offset = self.u32(owner + 0x28)
        seen, fields = set(), {}
        while offset:
            if offset in seen or len(seen) >= MAX_FIELDS or self.blocks.get(offset, (0, 0))[0] != 0xfffffffd:
                raise _invalid()
            seen.add(offset)
            if self.blocks[offset][1] < 0x32 or self.reference(offset + 0x18) != self.reference(owner + 12):
                raise _invalid()
            fid, kind = struct.unpack_from("<HH", self.data, offset + 0x24)
            if fid in fields:
                raise _invalid()
            fields[fid] = kind
            offset = self.u32(offset + 0x20)
        return fields

    def entries(self, repeats=False, planner_sections=False):
        for address, (tag, size) in self.blocks.items():
            # Freed blocks retain old text. Only live application allocations count.
            if planner_sections:
                if tag != 0xfeffffff or size < 0x34:
                    continue
                count = self.u32(address + 0x28)
                if count > MAX_FIELDS or 0x34 + count * 8 > size:
                    continue
                # Inspect only the inline section-kind enum before reading any
                # section name: unrelated/notebook roots are not reconstructed.
                if not any(struct.unpack_from("<HHI", self.data, address+0x34+i*8) == (5, 4, 0x200)
                           for i in range(count)):
                    continue
            elif not address or tag >= 0x80000000 and not (repeats and tag == REPEAT_TAG):
                continue
            if size < 0x34:
                raise _invalid()
            schema = self.schemas.get(self.reference(address + 0x18))
            if not schema or schema[0] != tag:
                raise _invalid()
            count = self.u32(address + 0x28)
            minimum = 0x34 + count * 8
            if count > MAX_FIELDS or minimum > size:
                raise _invalid()
            fields = {}
            for index in range(count):
                entry = address + 0x34 + index * 8
                fid, length, value = struct.unpack_from("<HHI", self.data, entry)
                if fid not in schema[1] or fid in fields:
                    raise _invalid()
                if length <= 4:
                    blob = self.data[entry+4:entry+4+length]
                else:
                    if value < minimum or length > size or value > size-length:
                        raise _invalid()
                    blob = self.data[address+value:address+value+length]
                fields[fid] = blob
            oid, origin = self.reference(address+12)
            yield tag, fields, "or6:%08x:%08x" % (origin, oid), (oid, origin), self.reference(address+0x18)

    def planner_keys(self, entries):
        """Unique native root/name/namespace binding, never OID arithmetic.

        Configs can share one options schema across different sections. Their
        explicit Section ID, not that shared schema, owns the names. Actual
        root names remain aligned with event-schema names after tab renames.
        """
        roots = list(self.entries(planner_sections=True))
        root_counts, schema_index = {}, {}
        for root in roots:
            root_counts[root[3]] = root_counts.get(root[3], 0) + 1
        for key, name in self.schema_names.items():
            if name:
                schema_index.setdefault((key[1], name), []).append(key)
        bindings = {}
        for _, fields, _, reference, _ in roots:
            if root_counts[reference] != 1:
                continue
            name = _string(fields, 3)
            candidates = schema_index.get((reference[1], name), [])
            if len(candidates) == 1:
                bindings.setdefault(candidates[0], []).append(reference)
        configs = {}
        for tag, fields, _, _, _ in entries:
            if tag != 0x201 or len(fields.get(3, b"")) != 8 or 10 not in fields:
                continue
            try:
                names = _wide(fields[10]).split("\0")
            except ValueError:
                continue
            if len(names) < 15 or any(names[15:]):
                continue
            configs.setdefault(struct.unpack("<II", fields[3]), []).append(names[:15])
        return {schema: configs[references[0]][0] for schema, references in bindings.items()
                if len(references) == 1 and len(configs.get(references[0], [])) == 1}

    def records(self):
        for tag, fields, uid, reference, schema in self.entries():
            yield tag, fields, uid

    def repeat_groups(self, entries):
        """Resolve actual live ccSTR links, never group equal-looking appointments."""
        by_key = {}
        for entry in entries:
            key = entry[3] + entry[4]
            if key in by_key:
                raise _invalid()
            by_key[key] = entry
        groups, assigned = {}, {}
        for address, (tag, size) in self.blocks.items():
            if tag != 0xfffffffb or size < 0x58:
                continue
            source = by_key.get(self.reference(address+0x20) + self.reference(address+0x28))
            target = by_key.get(self.reference(address+0x30) + self.reference(address+0x38))
            if source is None or target is None or source[0] not in (0x100, 0x300) or target[0] != REPEAT_TAG:
                continue
            if source[2] in assigned and assigned[source[2]] != target[2]:
                raise _invalid()
            assigned[source[2]] = target[2]
            group = groups.setdefault(target[2], (target, {}))
            group[1][source[2]] = source
        result = {}
        for target, members in groups.values():
            shared = (target, list(members.values()))
            for member in members:
                result[member] = shared
        return result

    def contact_groups(self, entries):
        by_key = {entry[3] + entry[4]:entry for entry in entries}
        memberships, represented = {}, set()
        for address, (tag, size) in self.blocks.items():
            if tag != 0xfffffffb or size < 0x58 or self.u32(address+0x50) != 0x40000:
                continue
            source = by_key.get(self.reference(address+0x20) + self.reference(address+0x28))
            target = by_key.get(self.reference(address+0x30) + self.reference(address+0x38))
            if (source is None or target is None or source[0] != 0x400 or target[0] != 0x400 or
                    _number(source[1], 13) != 1 or _number(target[1], 13) != 0):
                continue
            name = _string(source[1], 19)
            if name:
                memberships.setdefault(target[2], set()).add(name)
                represented.add(source[2])
        return memberships, represented


def _number(fields, fid, default=0):
    value = fields.get(fid)
    return int.from_bytes(value, "little") if value and len(value) <= 4 else default


def _strings(fields, fid):
    value = fields.get(fid, b"")
    return [part.strip() for part in _wide(value).rstrip("\x00").split("\x00")]


def _string(fields, fid):
    return _strings(fields, fid)[0]


def _stamp(value):
    if not value or value == b"\x02\x00" + b"\x02" * 6:
        return None
    if len(value) != 8:
        raise _invalid()
    year, month, day, hour, minute, second, unused = struct.unpack("<HBBBBBB", value)
    try:
        when = datetime(year, month, day, hour, minute, second)
    except ValueError as error:
        raise _invalid() from error
    return when


def _date(fields, fid):
    when = _stamp(fields.get(fid))
    return (f"{when.year:04d}-{when.month:02d}-{when.day:02d}", when.strftime("%H:%M")) if when else ("", "")


def _planner_source_clock(fields):
    """Original UI shows inclusive dates for these verified legacy clocks.

    Keep the exact local timestamp parts as source properties, not a guessed
    timezone or scheduling rule. Other clock shapes remain unsupported.
    """
    raw = [fields.get(fid, b"") for fid in (7, 8)]
    if any(len(value) != 8 or value[7] != 0 for value in raw):
        return None
    begin, end = map(_stamp, raw)
    if not begin or not end or end < begin:
        return None
    midnights = all((value.hour, value.minute, value.second) == (0, 0, 0) for value in (begin, end))
    same_day_hours = begin.date() == end.date() and all(value.minute == value.second == 0 for value in (begin, end))
    if not (midnights or same_day_hours):
        return None
    compact = lambda value: (f"{value.year:04d}{value.month:02d}{value.day:02d}T"
                             f"{value.hour:02d}{value.minute:02d}{value.second:02d}")
    return ["X-MAGNOLIE-OR6-PLANNER-LOCAL-START:" + compact(begin),
            "X-MAGNOLIE-OR6-PLANNER-LOCAL-END:" + compact(end)]


def _common(fields, uid):
    title = _string(fields, 9)
    result = {"titel": title.splitlines()[0], "notiz": "\n".join(title.splitlines()[1:]),
              "uid": uid, "geaendert": 0, "vertraulich": bool(_number(fields, 1))}
    body = _string(fields, 16)
    if body:
        result["notiz"] += ("\n" if result["notiz"] else "") + body
    return result


def _finite_series(group, orphaned=(), task_states=False):
    definition, members = group
    if not members or len({member[0] for member in members}) != 1:
        return None  # A native definition cannot mix tasks and appointments.
    metadata = definition[1]
    arrays = []
    for fid in (12, 13):
        raw = metadata.get(fid, b"")
        if not raw or len(raw) % 8:
            return None
        dates = [_stamp(raw[index:index+8]) for index in range(0, len(raw), 8)]
        if any(value is None for value in dates):
            return None
        arrays.append(dates)
    starts, ends = arrays
    if len(starts) != len(ends) or len(starts) < len(members) or starts != sorted(set(starts)):
        return None
    ordered = sorted(members, key=lambda member: _number(member[1], 14))
    base = ordered[0][1]
    ignored = {7, 8, 14} | ({3, 19, 20} if task_states else set())
    comparable = {fid:value for fid,value in base.items() if fid not in ignored}
    indices = [_number(member[1], 14) for member in ordered]
    if len(set(indices)) != len(indices) or any(index >= len(starts) for index in indices):
        return None
    missing = set(range(len(starts))) - set(indices)
    if any((ordered[0][4], index, starts[index]) in orphaned for index in missing):
        return None  # An active, unlinked occurrence is not a deleted exception.
    for index, member in zip(indices, ordered):
        fields = member[1]
        if (_number(fields, 10) != 1 or
                {fid:value for fid,value in fields.items() if fid not in ignored} != comparable or
                _stamp(fields.get(7)) != starts[index] or _stamp(fields.get(8)) != ends[index] or
                ends[index] < starts[index]):
            return None
    duration = ends[0] - starts[0]
    if any(start.time() != starts[0].time() or end-start != duration for start,end in zip(starts, ends)):
        return None  # Per-occurrence time/content overrides require explicit handling.
    if not _string(base, 9):
        return None
    result = _common(base, definition[2])
    if not task_states:
        categories = _categories(base)
        if categories:
            result["kategorien"] = categories
    first, end = starts[0], ends[0]
    result.update(datum=first.strftime("%Y-%m-%d"), zeit=first.strftime("%H:%M"),
        endDatum=end.strftime("%Y-%m-%d") if end.date() != first.date() else "", endZeit=end.strftime("%H:%M"),
        vorlaeufig=bool(_number(base, 18)))
    compact = lambda value: value.strftime("%Y%m%dT%H%M%S")
    raw = ["DTSTART:" + compact(first), "DTEND:" + compact(end)]
    dates = [value.strftime("%Y-%m-%d") for index,value in enumerate(starts) if index not in missing]
    recurrence = {"art":"custom", "bis":"", "intervall":1, "ordinal":0, "wochentag":"", "rruleForm":"", "daten":dates}
    # This native rule layout is accepted only when its entire finite expansion
    # equals the independently stored dates; otherwise retain the exact RDATE set.
    selected = metadata.get(5, b"")
    until = _stamp(metadata.get(7))
    interval = _number(metadata, 4) + 1
    if (_number(metadata, 3) == 1 and _number(metadata, 8) == 0 and _number(metadata, 11) == 0 and
            selected and len(selected) % 2 == 0 and len(selected) <= 14 and until is not None and
            1 <= interval <= 3660):
        weekdays = list(struct.unpack("<" + "H"*(len(selected)//2), selected))
        if len(set(weekdays)) == len(weekdays) and all(day <= 6 for day in weekdays):
            anchor = first.date().toordinal() - (first.weekday()+1) % 7
            expected, week = [], anchor
            limit = until.date().toordinal()
            while week <= limit and len(expected) <= len(starts):
                for weekday in sorted(weekdays):
                    day = week + weekday
                    if first.date().toordinal() <= day <= limit:
                        expected.append(day)
                week += 7*interval
            if expected == [value.date().toordinal() for value in starts]:
                tokens = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
                rule = "FREQ=WEEKLY;INTERVAL=%s;BYDAY=%s;WKST=SU;UNTIL=%sT235959" % (
                    interval, ",".join(tokens[day] for day in sorted(weekdays)), until.strftime("%Y%m%d"))
                raw.append("RRULE:" + rule)
                # A single start weekday has the existing editable weekly model.
                if weekdays == [(first.weekday()+1) % 7]:
                    recurrence = {"art":"weekly", "bis":until.strftime("%Y-%m-%d"), "intervall":interval,
                                  "ordinal":0, "wochentag":"", "rruleForm":""}
                else:
                    result["icsKomplex"] = True
                    result["icsSerienUid"] = definition[2]
    if len(raw) == 2:
        raw.append("RDATE:" + ",".join(compact(value) for value in starts))
    if missing:
        raw.append("EXDATE:" + ",".join(compact(starts[index]) for index in sorted(missing)))
        result.update(icsKomplex=True, icsSerienUid=definition[2],
            icsAusnahmeTermine=[{"datum":starts[index].strftime("%Y-%m-%d"), "zeit":starts[index].strftime("%H:%M")}
                               for index in sorted(missing)])
    result.update(wiederholung=recurrence, icsRoundtrip=raw)
    return result


def _finite_calendar_series(group, orphaned, schemas):
    """Verified original slot identity, not task index/date recovery (#614)."""
    ordinary = _finite_series(group, orphaned)
    if ordinary is not None:
        return [ordinary]
    definition, members = group
    if not members or any(member[0] != 0x100 for member in members):
        return None
    arrays = []
    for fid in (12, 13):
        raw = definition[1].get(fid, b"")
        if not raw or len(raw) % 8:
            return None
        values = [_stamp(raw[i:i+8]) for i in range(0, len(raw), 8)]
        if any(value is None for value in values):
            return None
        arrays.append(values)
    starts, ends = arrays
    if len(starts) != len(ends):
        return None
    # The absent first index means zero only for the independently observed
    # native computed uint32 declaration; _number alone accepts other widths.
    if any(schemas[member[4]][1].get(14) != 0x2003 or
           14 in member[1] and len(member[1][14]) != 4 for member in members):
        return None
    ordered = sorted(members, key=lambda member: _number(member[1], 14))
    indices = [_number(member[1], 14) for member in ordered]
    if len(set(indices)) != len(indices) or any(index >= len(starts) for index in indices):
        return None
    base = ordered[0][1]
    known = {3, 7, 8, 9, 14}
    comparable = {fid: value for fid, value in base.items() if fid not in known}
    projected = []
    for index, member in zip(indices, ordered):
        fields = member[1]
        begin, end = _stamp(fields.get(7)), _stamp(fields.get(8))
        if (not begin or not end or end < begin or not _string(fields, 9) or
                {fid: value for fid, value in fields.items() if fid not in known} != comparable):
            return None  # Includes Busy/meeting differences: never ignored.
        if _categories(base) and not _categories(fields):
            return None  # Explicit empty-category export/inheritance unverified.
        canonical = dict(base)
        canonical.update({7: definition[1][12][index*8:index*8+8],
                          8: definition[1][13][index*8:index*8+8],
                          14: struct.pack('<I', index)})
        projected.append((member[0], canonical, *member[2:]))
    # Reuse strict original-link/array/rule/missing-slot/orphan checks, but only
    # on an in-memory uniform view of the original slots, never moved clocks.
    master = _finite_series((definition, projected), orphaned)
    if master is None:
        return None
    converted = [master]
    compact = lambda value: value.strftime("%Y%m%dT%H%M%S")
    for index, member in zip(indices, ordered):
        fields = member[1]
        begin, end = _stamp(fields[7]), _stamp(fields[8])
        if (begin == starts[index] and end == ends[index] and
                fields.get(9) == base.get(9) and _categories(fields) == _categories(base)):
            continue
        master["icsRoundtrip"].append("EXDATE:" + compact(starts[index]))
        master.update(icsKomplex=True, icsSerienUid=definition[2])
        child = _common(fields, member[2])
        child.update(datum=begin.strftime("%Y-%m-%d"), zeit=begin.strftime("%H:%M"),
                     endDatum=end.strftime("%Y-%m-%d") if end.date() != begin.date() else "",
                     endZeit=end.strftime("%H:%M"), kategorien=_categories(fields),
                     vorlaeufig=bool(_number(fields, 18)), icsSerienUid=definition[2],
                     icsRoundtrip=["RECURRENCE-ID:" + compact(starts[index]),
                                   "DTSTART:" + compact(begin), "DTEND:" + compact(end),
                                   "X-MAGNOLIE-OR6-OBJECT-UID:" + member[2]])
        converted.append(child)
    return converted


def _task_segment_members(group, orphaned):
    """Retain linked history preceding the current native date-array segment.

    Later scoped edits restart indices; original bulk edits can also copy zero
    to the whole set while leaving old template dates behind. Only complete,
    uniquely dated, explicitly linked sets can recover that verified form.
    Projection is in memory, never a source edit or guessed historical dates.
    """
    definition, members = group
    arrays = []
    for fid in (12, 13):
        raw = definition[1].get(fid, b"")
        if not raw or len(raw) % 8:
            return None
        values = [_stamp(raw[i:i+8]) for i in range(0, len(raw), 8)]
        if any(value is None for value in values):
            return None
        arrays.append(values)
    starts, ends = arrays
    if (len(starts) != len(ends) or starts != sorted(set(starts)) or
            any(end < start for start, end in zip(starts, ends))):
        return None
    history, current, seen = [], [], set()
    for member in members:
        start, end = _stamp(member[1].get(7)), _stamp(member[1].get(8))
        if not start or not end or start in seen or end < start:
            return None
        seen.add(start)
        if start < starts[0]:
            anchor = _stamp(definition[1].get(6))
            if not anchor or start.date() < anchor.date():
                return None
            history.append(member)
        else:
            index = _number(member[1], 14)
            if index >= len(starts):
                return None
            current.append(member)
    if not current or len({member[4] for member in members}) != 1:
        return None
    indices = {_number(member[1], 14) for member in current}
    recovered = any(_stamp(member[1][7]) != starts[_number(member[1], 14)] or
                    _stamp(member[1][8]) != ends[_number(member[1], 14)] for member in current)
    if recovered:
        if len(current) != len(starts) or indices not in ({0}, set(range(len(starts)))):
            return None  # No partial/ambiguous rebinding or unknown index default.
        actual_starts = {_stamp(member[1][7]) for member in current}
        candidate_starts = set(starts) | actual_starts
        if any(schema == current[0][4] and start in candidate_starts for schema, _, start in orphaned):
            return None  # A known active unlinked task is never guessed deleted.
        current.sort(key=lambda member: _stamp(member[1][7]))
    if not history and not recovered:
        return group
    if any((current[0][4], index, starts[index]) in orphaned for index in set(range(len(starts))) - indices):
        return None
    history.sort(key=lambda member: _stamp(member[1][7]))
    # For the verified complete-set edit form, visible linked clocks take
    # precedence over stale templates. Rule validation below still has to match
    # every actual date; otherwise this is an exact finite RDATE set, not a rule.
    start_bytes = b"".join(member[1][7] for member in history) + (b"".join(member[1][7] for member in current) if recovered else definition[1][12])
    end_bytes = b"".join(member[1][8] for member in history) + (b"".join(member[1][8] for member in current) if recovered else definition[1][13])
    metadata = dict(definition[1])
    metadata.update({12: start_bytes, 13: end_bytes})
    projected = []
    for index, member in enumerate(history):
        fields = dict(member[1]); fields[14] = struct.pack('<I', index)
        projected.append((member[0], fields, *member[2:]))
    for index, member in enumerate(current):
        fields = dict(member[1]); fields[14] = struct.pack('<I', len(history) + (index if recovered else _number(fields, 14)))
        projected.append((member[0], fields, *member[2:]))
    return ((definition[0], metadata, *definition[2:]), projected)


def _categories(fields):
    return ", ".join(dict.fromkeys(value for value in _strings(fields, 3) if value))


def _finite_task_series(group, orphaned=()):
    # Reuse the native link/index/array and exact finite-expansion validation,
    # not the appointment destination model. Task data remains one VTODO set.
    if any(_number(member[1], 20) not in (1, 2, 4) for member in group[1]):
        return None  # Unknown per-occurrence states must not become open tasks.
    for member in group[1]:
        _date(member[1], 19)  # Retain strict native stamp validation.
    templates = {fid: group[0][1].get(fid, b"") for fid in (12, 13)}
    group = _task_segment_members(group, orphaned)
    if group is None:
        return None
    series = _finite_series(group, orphaned, task_states=True)
    if series is None:
        return None
    fields = group[1][0][1]
    priority = _number(fields, 18, 3)
    all_done = all(_number(member[1], 20) == 4 for member in group[1])
    result = _common(fields, group[0][2])
    categories = _categories(fields)
    if categories:
        result["kategorien"] = categories
    result.update(startDatum=series["datum"], startZeit=series["zeit"],
                  faellig=series["endDatum"] or series["datum"], faelligZeit=series["endZeit"],
                  prio=priority+1 if priority < 3 else 2,
                  erledigt=all_done,
                  icsSerienUid=group[0][2],
                  icsRoundtrip=["DUE:" + line[6:] if line.startswith("DTEND:") else line
                                for line in series["icsRoundtrip"]])
    for fid, name in ((12, "STARTS"), (13, "DUES")):
        if templates[fid] != group[0][1][fid]:
            result["icsRoundtrip"].append("X-MAGNOLIE-OR6-TASK-TEMPLATE-" + name + ":" + ",".join(
                _stamp(templates[fid][i:i+8]).strftime("%Y%m%dT%H%M%S") for i in range(0, len(templates[fid]), 8)))
    converted = [result]
    for member in sorted(group[1], key=lambda value: _number(value[1], 14)):
        completed = _number(member[1], 20) == 4
        member_categories = _categories(member[1])
        if completed == all_done and member_categories == categories:
            continue
        start, due = _stamp(member[1].get(7)), _stamp(member[1].get(8))
        compact = lambda value: value.strftime("%Y%m%dT%H%M%S")
        result["icsRoundtrip"].append("EXDATE:" + compact(start))
        done = _common(member[1], member[2])
        done.update(startDatum=start.strftime("%Y-%m-%d"), startZeit=start.strftime("%H:%M"),
                    faellig=due.strftime("%Y-%m-%d"), faelligZeit=due.strftime("%H:%M"),
                    prio=result["prio"], erledigt=completed, kategorien=member_categories, icsSerienUid=group[0][2],
                    icsRoundtrip=["RECURRENCE-ID:" + compact(start), "DTSTART:" + compact(start),
                                  "DUE:" + compact(due), "STATUS:" + ("COMPLETED" if completed else "NEEDS-ACTION"),
                                  "PERCENT-COMPLETE:" + ("100" if completed else "0")])
        converted.append(done)
    return converted


def _read_or6(raw):
    result = {key: [] for key in ("termine", "aufgaben", "kontakte", "notizen", "jahrestage", "geburtstage")}
    result.update(uebersprungen=0, wiederholend=0)
    document = _Document(raw)
    entries = list(document.entries(repeats=True))
    planner_keys = document.planner_keys(entries)
    groups = document.repeat_groups(entries)
    memberships, represented_groups = document.contact_groups(entries)
    orphaned = {(entry[4], _number(entry[1], 14), _stamp(entry[1].get(7))) for entry in entries
                if entry[0] in (0x100, 0x300) and _number(entry[1], 10) and entry[2] not in groups}
    consumed = set()
    evaluated = {}
    for tag, fields, uid, reference, schema in entries:
        if uid in consumed:
            continue
        if tag in (0x100, 0x300):
            title = _string(fields, 9)
            if not title:
                continue
            if _number(fields, 10):
                group = groups.get(uid)
                if group and group[0][2] not in evaluated:
                    evaluated[group[0][2]] = (_finite_task_series(group, orphaned) if tag == 0x300 else
                                              _finite_calendar_series(group, orphaned, document.schemas))
                series = evaluated.get(group[0][2]) if group else None
                if series is not None:
                    if tag == 0x300:
                        result["aufgaben"].extend(series)
                    else:
                        result["termine"].extend(series)
                    # The shared counter warns about unresolved source rules;
                    # this fully verified recurrence set is already expandable.
                    consumed.update(member[2] for member in group[1])
                    continue
                result["uebersprungen"] += 1
                # Unsupported native sets are omitted, not retained as opaque
                # source-calendar rules or flattened into unrelated entries.
                continue
            begin, time = _date(fields, 7)
            end, end_time = _date(fields, 8)
            common = _common(fields, uid)
            if tag == 0x100:
                if not begin or not end or (end, end_time) < (begin, time):
                    result["uebersprungen"] += 1
                    continue
                categories = _categories(fields)
                if categories:
                    common["kategorien"] = categories
                result["termine"].append(dict(common, datum=begin, zeit=time,
                    endDatum=end if end != begin else "", endZeit=end_time,
                    vorlaeufig=bool(_number(fields, 18))))
            else:
                completed, completed_time = _date(fields, 19)
                priority = _number(fields, 18, 3)
                # Original-program open/completed/reopened controls verify
                # Status 1/2 as open and 4 as complete. A Lotus reexport may
                # leave a completion stamp even on an explicitly open task.
                status = _number(fields, 20)
                done = status == 4 if status in (1, 2, 4) else bool(completed)
                result["aufgaben"].append(dict(common, startDatum=begin, startZeit=time,
                                               faellig=end, faelligZeit=end_time, prio=priority+1 if priority < 3 else 2,
                                               erledigt=done))
        elif tag == 0x400:
            first, last = _string(fields, 17), _string(fields, 19)
            company = _string(fields, 23)
            if not any((first, last, company, _string(fields, 33), _string(fields, 35))):
                continue  # Blank alphabet-index placeholders are not contacts.
            if _number(fields, 13):
                if uid not in represented_groups:
                    result["uebersprungen"] += 1
                continue
            # Keep original slot positions: verified Work/Home/Fax contexts must
            # not shift when preceding native phone slots are empty.
            phone_types = {0: ["WORK", "VOICE"], 3: ["HOME", "VOICE"], 6: ["WORK", "FAX"]}
            phones = [{"wert": value, "typen": phone_types.get(index, ["VOICE"])}
                      for index, value in enumerate(_strings(fields, 33)) if value]
            emails = list(dict.fromkeys(value for value in _strings(fields, 35) if value))
            columns = [_strings(fields, fid) for fid in (28, 31, 29, 32, 30)]
            addresses = []
            for index in range(max(map(len, columns))):
                address = {key: values[index] if index < len(values) else "" for key, values in
                           zip(("strasse", "plz", "ort", "land", "region"), columns)}
                if not address["region"]:
                    del address["region"]
                if any(address.values()):
                    address["typen"] = ["WORK"] if index == 0 else ["HOME"] if index == 1 else []
                    addresses.append(address)
            contact = {"vorname": first, "nachname": last, "firma": company, "uid": uid, "geaendert": 0,
                       "telefon": phones[0]["wert"] if phones else "", "mobil": "", "telefone": phones,
                       "email": emails[0] if emails else "", "emails": emails,
                       "anschriften": addresses, "notiz": _string(fields, 39)}
            categories = list(dict.fromkeys([value for value in _strings(fields, 3) if value] +
                                           sorted(memberships.get(uid, ()), key=lambda value: value.encode("utf-16-be"))))
            if categories:
                escape = lambda value: value.replace("\r\n", "\n").replace("\r", "\n").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
                contact["vcardRoundtrip"] = ["CATEGORIES:" + ",".join(escape(value) for value in categories)]
            if addresses:
                contact.update({key: addresses[0][key] for key in ("strasse", "plz", "ort", "land")})
            birthday, birthday_time = _date(fields, 41)
            if birthday:
                contact["geburtstag"] = birthday
            for fid, label in ((16, "Title"), (18, "Middle name"), (20, "Suffix"),
                               (22, "Position"), (25, "Department"), (27, "Assistant"),
                                (30, "State"), (37, "URL"), (40, "Mail merge name"), (43, "Spouse"), (44, "Children")):
                value = "; ".join(part for part in _strings(fields, fid) if part)
                if value:
                    contact["notiz"] += ("\n" if contact["notiz"] else "") + label + ": " + value
            # Preserve opaque source slots without guessing their relationship
            # to phone numbers, labels or dialable extensions.
            for index, value in enumerate(_strings(fields, 34), 1):
                if value:
                    contact["notiz"] += ("\n" if contact["notiz"] else "") + "Lotus Extn slot %d: %s" % (index, value)
            for fid in range(46, 66):
                value = _string(fields, fid)
                if value:
                    contact["notiz"] += "\nCustom %d: %s" % (fid-45, value)
            result["kontakte"].append(contact)
        elif tag == 0x510:
            title = _string(fields, 7)
            body = fields.get(8, b"")
            # An opaque unsupported note is not a corrupt allocation chain.
            # Do not guess a plaintext encoding or silently import its title as
            # complete content. Omit/count this entry in the existing preview;
            # recognized-but-malformed RTF still fails through the strict parser.
            if len(body) <= 1024 * 1024 and b"{\\rtf" not in body and body.strip(b"\x00\xff\x02"):
                result["uebersprungen"] += 1
                continue
            text = _rtf(body)
            if title or text:
                result["notizen"].append({"titel": title, "text": text, "uid": uid})
        elif tag in (0x200, 0x600):
            if not _string(fields, 9):
                continue
            begin, time = _date(fields, 7)
            end, end_time = _date(fields, 8)
            # Planner UI has independently verified inclusive date presentation
            # for the bounded legacy clock forms below; anniversaries do not
            # acquire these semantics. Repeat/confidential guards stay intact.
            if (not begin or not end or end < begin or _number(fields, 10) or _number(fields, 1)):
                result["uebersprungen"] += 1
                continue
            source_clock = None
            if time != "00:00" or end_time != "23:59":
                source_clock = _planner_source_clock(fields) if tag == 0x200 else None
                if source_clock is None:
                    result["uebersprungen"] += 1
                    continue
            common = _common(fields, uid)
            if source_clock is not None:
                common["icsRoundtrip"] = source_clock
            if tag == 0x600 and _number(fields, 19) == 1 and not _number(fields, 18) & 0x10000 and begin == end:
                result["jahrestage"].append({"name": common["titel"], "datum": begin,
                    "typ": "anniversary", "notiz": common["notiz"], "uid": uid, "geaendert": 0})
            elif tag == 0x200 or (_number(fields, 19) == 0 and _number(fields, 18) & 0x10000 and begin == end):
                if tag == 0x200:
                    # The original UI's explicitly selected first slot is
                    # serialized without field19. This semantic zero default
                    # is limited to a declared native uint16 KeyID; absence is
                    # still not printed as an observed source field below.
                    key_id = (_number(fields, 19) if document.schemas[schema][1].get(19) == 2 and
                              (19 not in fields or len(fields[19]) == 2) else -1)
                    if schema in planner_keys and 0 <= key_id < len(PLANNER_COLORS):
                        common["kategorien"] = planner_keys[schema][key_id]
                        common["akzentFarbe"] = PLANNER_COLORS[key_id]
                    # Independently named native schema fields: Row != KeyID.
                    # Neither number proves a category name or palette color.
                    for fid, label in ((18, "Row"), (19, "KeyID")):
                        if fid in fields:
                            common["notiz"] += ("\n" if common["notiz"] else "") + "Lotus planner " + label + ": " + str(_number(fields, fid))
                result["termine"].append(dict(common, datum=begin, zeit="", endDatum=end if end != begin else "", endZeit="", vorlaeufig=False))
            else:
                result["uebersprungen"] += 1
        elif tag in (0x700, 0x900):
            title = _string(fields, 12 if tag == 0x900 else 9)
            if not any(_string(fields, fid) for fid in ((12, 14, 15) if tag == 0x900 else (9, 18, 19, 20, 21))):
                continue
            # There is no call-log/bookmark collection in the target book. Keep
            # basic source fields explicitly as text, never dial or open a URL.
            if _number(fields, 1) or (tag == 0x700 and _number(fields, 10)):
                result["uebersprungen"] += 1
                continue
            if tag == 0x900:
                text = "Lotus Organizer: Web\nURL: " + _string(fields, 14) + "\n" + _string(fields, 15)
            else:
                begin, time = _date(fields, 7)
                end, end_time = _date(fields, 8)
                if not begin or not end or (end, end_time) < (begin, time):
                    result["uebersprungen"] += 1
                    continue
                text = "\n".join(("Lotus Organizer: Calls", "Start: " + begin + " " + time,
                    "End: " + end + " " + end_time, "Contact: " + " ".join(filter(None, (_string(fields, 19), _string(fields, 20)))),
                    "Company: " + _string(fields, 21), "Phone: " + _string(fields, 18),
                    "Status: " + _string(fields, 22), "Completed: " + ("true" if _number(fields, 24) else "false"), title))
            result["notizen"].append({"titel": title.splitlines()[0] if title else "Lotus Organizer", "text": text, "uid": uid})
    result["bericht"] = _("OR6 import: appointments, tasks, contacts and plain-text notes. Verified finite appointment series, contact group memberships and known phone contexts are retained. Basic planner spans and annual anniversaries are retained; one-off anniversaries become all-day appointments, call and web records become text notes. Unsupported entries, layout, attachments and alarms are not transferred.")
    return result


def read_or6(raw, translate=None):
    try:
        result = _read_or6(raw)
    except ValueError as error:
        if translate is not None:
            raise ValueError(translate(str(error))) from error
        raise
    if translate is not None:
        result["bericht"] = translate(result["bericht"])
    return result
