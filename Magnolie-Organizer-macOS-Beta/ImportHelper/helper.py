#!/usr/bin/env python3
"""One bounded header+binary request -> one bounded result; protocol #785 v1."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys


MAX_HEADER_BYTES = 8192
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 96 * 1024 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
FORMATS = frozenset({"ics", "lotus", "vcf", "claws", "ldif", "muell"})
HEADER_FIELDS = frozenset({"schema", "format", "name", "language", "timeZone", "homeCountry", "byteLength", "sha256"})


class RequestError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property.")
        result[key] = value
    return result


def read_json(data):
    def invalid_constant(_value):
        raise ValueError("Non-finite JSON number.")
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bundle_file(bundle, name):
    if (not isinstance(name, str) or not name or Path(name).is_absolute()
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError("Invalid helper manifest path.")
    path = bundle / name
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise ValueError("Symlinked helper input.")
    return path


def verify_bundle(bundle):
    raw = bundle_file(bundle, "manifest.json").read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Helper manifest is too large.")
    manifest = read_json(raw)
    if (manifest.get("schema") != 1 or manifest.get("protocol") != 1
            or manifest.get("kind") != "magnolie-macos-import-helper"
            or manifest.get("maximumInputBytes") != MAX_INPUT_BYTES
            or manifest.get("maximumOutputBytes") != MAX_OUTPUT_BYTES
            or set(manifest.get("formats", [])) != FORMATS):
        raise ValueError("Helper manifest contract differs.")
    generated = manifest["generated"]
    actual = {str(path.relative_to(bundle)) for path in bundle.rglob("*") if path.is_file()}
    if actual != set(generated) | {"manifest.json"}:
        raise ValueError("Helper file set differs.")
    for name, proof in generated.items():
        data = bundle_file(bundle, name).read_bytes()
        if len(data) != proof["bytes"] or digest(data) != proof["sha256"]:
            raise ValueError("Helper input identity differs.")
    return manifest, digest(raw)


def read_request(stream):
    line = stream.readline(MAX_HEADER_BYTES + 1)
    if len(line) > MAX_HEADER_BYTES or not line.endswith(b"\n"):
        raise RequestError("invalid_header", "The import header is invalid or too large.")
    try:
        header = read_json(line)
    except (ValueError, UnicodeError) as error:
        raise RequestError("invalid_header", "The import header is invalid.") from error
    if not isinstance(header, dict) or set(header) != HEADER_FIELDS:
        raise RequestError("invalid_header", "The import header fields differ.")
    if type(header["schema"]) is not int or header["schema"] != 1:
        raise RequestError("invalid_header", "The import protocol is unsupported.")
    if not isinstance(header["format"], str) or header["format"] not in FORMATS:
        raise RequestError("unsupported_format", "The file has an unsupported format.")
    for key, limit in (("name", 1024), ("language", 64), ("timeZone", 128)):
        value = header[key]
        if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > limit
                or any(ord(character) < 32 or ord(character) == 127 for character in value)):
            raise RequestError("invalid_header", "The import header contains invalid text.")
    if "/" in header["name"] or "\\" in header["name"] or header["name"] in {".", ".."}:
        raise RequestError("invalid_header", "The import requires a display filename, not a path.")
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*", header["language"]):
        raise RequestError("invalid_header", "The import language is invalid.")
    if not isinstance(header["homeCountry"], str) or not re.fullmatch(r"[A-Z]{2}", header["homeCountry"]):
        raise RequestError("invalid_header", "The import home country is invalid.")
    count = header["byteLength"]
    if type(count) is not int or not 0 <= count <= MAX_INPUT_BYTES:
        raise RequestError("input_too_large", "The import file is larger than 32 megabytes.")
    if not isinstance(header["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", header["sha256"]):
        raise RequestError("invalid_header", "The import source identity is invalid.")
    data = stream.read(count + 1)
    if len(data) != count:
        raise RequestError("input_length", "The import byte count differs or trailing input remains.")
    if digest(data) != header["sha256"]:
        raise RequestError("input_identity", "The import source identity differs.")
    return header, data


def restrict_io(bundle):
    # This is a narrow runtime guard, not a claim of an operating-system sandbox.
    # The isolated interpreter and this verified bundle are the only read roots.
    roots = (bundle.resolve(), Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve())

    def audit(event, args):
        if event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                if path not in (0, 1, 2):
                    raise PermissionError("External file descriptor refused.")
                return
            if (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                raise PermissionError("Import writes are refused.")
            candidate = Path(os.fsdecode(path)).resolve()
            if not any(candidate == root or root in candidate.parents for root in roots):
                raise PermissionError("External import file access refused.")
        elif event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event in {"os.system", "os.fork", "os.forkpty"}:
            raise PermissionError("Import process or network access refused.")
    sys.addaudithook(audit)


def encode_response(response, limit=MAX_OUTPUT_BYTES):
    buffer = io.BytesIO()
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for part in encoder.iterencode(response):
        raw = part.encode("utf-8")
        if buffer.tell() + len(raw) + 1 > limit:
            raise RequestError("output_too_large", "The import result exceeds the supported limits.")
        buffer.write(raw)
    buffer.write(b"\n")
    return buffer.getvalue()


def main():
    manifest_digest = None
    source_digest = None
    translate = lambda message: message
    try:
        bundle = Path(__file__).resolve().parent
        try:
            manifest, manifest_digest = verify_bundle(bundle)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RequestError("bundle_invalid", "The bundled import helper could not be verified.") from error
        header, data = read_request(sys.stdin.buffer)
        source_digest = header["sha256"]
        # -I -S -B intentionally omits the script directory, cwd and user site.
        # Add only this verified bundle, never a caller-provided search path.
        sys.path.insert(0, str(bundle / "vendor"))
        sys.path.insert(0, str(bundle))
        restrict_io(bundle)
        import import_context
        if header["homeCountry"] not in manifest["homeCountries"]:
            raise RequestError("invalid_header", "The import home country is invalid.")
        try:
            import_context.configure(bundle, header, read_json((bundle / "catalogs.json").read_bytes()), manifest["timezones"])
        except (KeyError, ValueError) as error:
            raise RequestError("invalid_timezone", "The calendar timezone is unavailable.") from error
        translate = import_context.translate
        import desktop_imports
        art = "claws" if header["format"] == "ldif" else header["format"]
        result = (desktop_imports.muell_import_lesen(data, header["name"]) if art == "muell"
                  else desktop_imports.import_rohdaten_lesen(art, data, header["name"]))
        if art == "ics":
            from calendar_evidence import with_calendar_evidence
            result = with_calendar_evidence(result, data, source_digest, desktop_imports)
        response = {"schema": 1, "ok": True, "format": header["format"], "name": header["name"],
                    "sourceSHA256": source_digest, "parserManifestSHA256": manifest_digest, "result": result}
        encoded = encode_response(response)
    except Exception as error:
        code = error.code if isinstance(error, RequestError) else "parse_failed"
        message = str(error) if isinstance(error, (RequestError, ValueError)) else "The content is unreadable."
        response = {"schema": 1, "ok": False, "sourceSHA256": source_digest,
                    "parserManifestSHA256": manifest_digest,
                    "error": {"code": code, "message": translate(message)[:512]}}
        encoded = encode_response(response)
    try:
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return 0
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
