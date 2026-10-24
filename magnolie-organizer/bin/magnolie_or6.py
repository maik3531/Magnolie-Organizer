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
        for address, (tag, size) in self.blocks.items():
            if tag != 0xffffffff:
                continue
            if size < 0x48:
                raise _invalid()
            key = self.reference(address + 12)
            if key in self.schemas:
                raise _invalid()
            self.schemas[key] = (self.u32(address + 0x2c), self._schema_fields(address))

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

    def records(self):
        for address, (tag, size) in self.blocks.items():
            # Freed blocks retain old text. Only live application allocations count.
            if not address or tag >= 0x80000000:
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
            yield tag, fields, "or6:%08x:%08x" % (origin, oid)


def _number(fields, fid, default=0):
    value = fields.get(fid)
    return int.from_bytes(value, "little") if value and len(value) <= 4 else default


def _strings(fields, fid):
    value = fields.get(fid, b"")
    return [part.strip() for part in _wide(value).rstrip("\x00").split("\x00")]


def _string(fields, fid):
    return _strings(fields, fid)[0]


def _date(fields, fid):
    value = fields.get(fid)
    if not value or value == b"\x02\x00" + b"\x02" * 6:
        return "", ""
    if len(value) != 8:
        raise _invalid()
    year, month, day, hour, minute, second, unused = struct.unpack("<HBBBBBB", value)
    try:
        when = datetime(year, month, day, hour, minute, second)
    except ValueError as error:
        raise _invalid() from error
    return f"{when.year:04d}-{when.month:02d}-{when.day:02d}", when.strftime("%H:%M")


def _read_or6(raw):
    result = {key: [] for key in ("termine", "aufgaben", "kontakte", "notizen", "jahrestage", "geburtstage")}
    result.update(uebersprungen=0, wiederholend=0)
    for tag, fields, uid in _Document(raw).records():
        if tag in (0x100, 0x300):
            title = _string(fields, 9)
            if not title:
                continue
            if _number(fields, 10):
                result["uebersprungen"] += 1
                # The existing recurrence counter describes retained ICS rules.
                # OR6 series are skipped, not retained as opaque calendar data.
                continue
            begin, time = _date(fields, 7)
            end, end_time = _date(fields, 8)
            common = {"titel": title.splitlines()[0], "notiz": "\n".join(title.splitlines()[1:]),
                      "uid": uid, "geaendert": 0, "vertraulich": bool(_number(fields, 1))}
            body = _string(fields, 16)
            if body:
                common["notiz"] += ("\n" if common["notiz"] else "") + body
            if tag == 0x100:
                if not begin or not end or (end, end_time) < (begin, time):
                    result["uebersprungen"] += 1
                    continue
                result["termine"].append(dict(common, datum=begin, zeit=time,
                    endDatum=end if end != begin else "", endZeit=end_time,
                    vorlaeufig=bool(_number(fields, 18))))
            else:
                completed, completed_time = _date(fields, 19)
                priority = _number(fields, 18, 3)
                result["aufgaben"].append(dict(common, faellig=end, prio=priority+1 if priority < 3 else 2,
                                               erledigt=bool(completed)))
        elif tag == 0x400:
            first, last = _string(fields, 17), _string(fields, 19)
            company = _string(fields, 23)
            if not any((first, last, company, _string(fields, 33), _string(fields, 35))):
                continue  # Blank alphabet-index placeholders are not contacts.
            if _number(fields, 13):
                result["uebersprungen"] += 1
                continue
            phones = [{"wert": value, "typen": ["VOICE"]} for value in _strings(fields, 33) if value]
            emails = list(dict.fromkeys(value for value in _strings(fields, 35) if value))
            columns = [_strings(fields, fid) for fid in (28, 31, 29, 32)]
            addresses = []
            for index in range(max(map(len, columns))):
                address = {key: values[index] if index < len(values) else "" for key, values in
                           zip(("strasse", "plz", "ort", "land"), columns)}
                if any(address.values()):
                    address["typen"] = ["WORK"] if index == 0 else ["HOME"] if index == 1 else []
                    addresses.append(address)
            contact = {"vorname": first, "nachname": last, "firma": company, "uid": uid, "geaendert": 0,
                       "telefon": phones[0]["wert"] if phones else "", "mobil": "", "telefone": phones,
                       "email": emails[0] if emails else "", "emails": emails,
                       "anschriften": addresses, "notiz": _string(fields, 39)}
            if addresses:
                contact.update({key: addresses[0][key] for key in ("strasse", "plz", "ort", "land")})
            birthday, birthday_time = _date(fields, 41)
            if birthday:
                contact["geburtstag"] = birthday
            for fid, label in ((16, "Title"), (18, "Middle name"), (20, "Suffix"),
                               (22, "Position"), (25, "Department"), (27, "Assistant"),
                               (30, "State"), (37, "URL"), (43, "Spouse"), (44, "Children")):
                value = "; ".join(part for part in _strings(fields, fid) if part)
                if value:
                    contact["notiz"] += ("\n" if contact["notiz"] else "") + label + ": " + value
            for fid in range(46, 66):
                value = _string(fields, fid)
                if value:
                    contact["notiz"] += "\nCustom %d: %s" % (fid-45, value)
            result["kontakte"].append(contact)
        elif tag == 0x510:
            title = _string(fields, 7)
            text = _rtf(fields.get(8, b""))
            if title or text:
                result["notizen"].append({"titel": title, "text": text, "uid": uid})
        elif tag in (0x200, 0x600, 0x700, 0x900):
            # Do not turn unsupported planner/call/bookmark data into appointments.
            text_fields = (12, 14, 15) if tag == 0x900 else (9,)
            if any(_string(fields, fid) for fid in text_fields):
                result["uebersprungen"] += 1
    result["bericht"] = _("OR6 import: appointments, tasks, contacts and plain-text notes. Recurrences, groups and other sections are skipped; layout, attachments, categories and alarms are not transferred.")
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
