#!/usr/bin/env python3
"""Bounded GitLab.com transport for the release storage guard (Refs #698).

This adapter does not decide what may be published or deleted. Its caller owns
the reviewed plan, publication approval and preconditions. Redirects, partial
inventories and unverified downloads are errors; response bodies and credentials
are never included in exceptions.
"""

from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_ORIGIN = "https://gitlab.com/api/v4"
JSON_LIMIT = 8 * 1024 * 1024
BLOCK_BYTES = 64 * 1024
TIMEOUT = 60
PAGE_SIZE = 100
MAX_PAGES = 1000
PACKAGE_STATUSES = (
    "default", "deprecated", "error", "hidden", "processing", "pending_destruction",
)


class GitLabAPIError(RuntimeError):
    """Sanitized transport/response failure, optionally carrying an HTTP status."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Returning None makes urllib raise HTTPError without contacting newurl.
        return None


def _require(condition, message):
    if not condition:
        raise GitLabAPIError(message)


def _text(value):
    _require(isinstance(value, str) and 0 < len(value) <= 4096 and
             not any(ord(char) < 32 or ord(char) == 127 for char in value),
             "Invalid GitLab API input")
    return value


def _segment(value):
    value = _text(value)
    _require(value not in {".", ".."} and "/" not in value and "\\" not in value,
             "Invalid GitLab API path segment")
    return quote(value, safe="")


def _repo_path(value):
    value = _text(value)
    _require("\\" not in value and all(part not in {"", ".", ".."} for part in value.split("/")),
             "Invalid repository file path")
    return quote(value, safe="")


def _positive_id(value):
    _require(type(value) is int and value > 0, "Invalid GitLab object ID")
    return str(value)


def _commit_id(value):
    _require(isinstance(value, str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value),
             "Invalid GitLab commit ID")
    return value


def _object(value, endpoint):
    _require(isinstance(value, dict), "Invalid JSON object from " + endpoint)
    return value


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON field from GitLab API")
        result[key] = value
    return result


def _reject_constant(_):
    raise GitLabAPIError("Non-finite JSON number from GitLab API")


def _length(headers, endpoint):
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    _require(isinstance(raw, str) and re.fullmatch(r"[0-9]{1,20}", raw),
             "Invalid Content-Length from " + endpoint)
    return int(raw)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _UploadStream:
    """Send exactly the opened file size without buffering the complete package."""

    def __init__(self, stream, size):
        self.stream = stream
        self.remaining = size

    def read(self, size=-1):
        if not self.remaining:
            return b""
        amount = min(self.remaining, BLOCK_BYTES, size if size >= 0 else BLOCK_BYTES)
        if not amount:
            return b""
        data = self.stream.read(amount)
        _require(len(data) == amount, "Upload source was truncated")
        self.remaining -= len(data)
        return data


class GitLabAPI:
    def __init__(self, project_path, token=None):
        _require(isinstance(project_path, str) and re.fullmatch(
            r"maik3531/[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", project_path),
            "Invalid configured GitLab project")
        self.project_path = project_path
        self._prefix = API_ORIGIN + "/projects/" + quote(project_path, safe="")
        self._token = os.environ.get("GITLAB_TOKEN", "") if token is None else token
        _require(isinstance(self._token, str) and all(32 < ord(char) < 127 for char in self._token),
                 "Invalid GitLab credential")
        self._opener = build_opener(_RejectRedirects())

    @contextmanager
    def _response(self, method, suffix, endpoint, *, query=None, data=None,
                  content_type=None, content_length=None, expected=200, missing=False,
                  accept="application/json", auth=True):
        url = self._prefix + suffix
        if query:
            url += "?" + urlencode(query)
        headers = {"Accept": accept, "Accept-Encoding": "identity"}
        if auth and self._token:
            headers["PRIVATE-TOKEN"] = self._token
        if content_type:
            headers["Content-Type"] = content_type
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        request = Request(url, data=data, headers=headers, method=method)
        try:
            response = self._opener.open(request, timeout=TIMEOUT)
        except HTTPError as error:
            status_code = error.code
            error.close()
            if missing and status_code == 404:
                yield None
                return
            raise GitLabAPIError("HTTP %s from %s" % (status_code, endpoint), status_code) from None
        except (URLError, OSError, http.client.HTTPException, ValueError):
            raise GitLabAPIError("Transport failed for " + endpoint) from None
        try:
            status_code = response.status
            _require(response.geturl() == url, "Unexpected response URL from " + endpoint)
            if missing and status_code == 404:
                yield None
                return
            if status_code != expected:
                raise GitLabAPIError("HTTP %s from %s" % (status_code, endpoint), status_code)
            _require(response.headers.get("Content-Encoding", "identity").lower() == "identity",
                     "Unexpected content encoding from " + endpoint)
            yield response
        except (URLError, OSError, http.client.HTTPException, ValueError):
            raise GitLabAPIError("Response failed for " + endpoint) from None
        finally:
            response.close()

    @staticmethod
    def _decode(response, endpoint):
        length = _length(response.headers, endpoint)
        _require(length is None or length <= JSON_LIMIT, "Oversized JSON from " + endpoint)
        chunks = []
        count = 0
        while True:
            block = response.read(min(BLOCK_BYTES, JSON_LIMIT + 1 - count))
            if not block:
                break
            count += len(block)
            _require(count <= JSON_LIMIT, "Oversized JSON from " + endpoint)
            chunks.append(block)
        _require(length is None or length == count, "Truncated JSON from " + endpoint)
        try:
            return json.loads(b"".join(chunks).decode("utf-8"), object_pairs_hook=_unique_fields,
                              parse_constant=_reject_constant)
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise GitLabAPIError("Invalid JSON from " + endpoint) from None

    def _json(self, suffix, endpoint, *, query=None, missing=False):
        with self._response("GET", suffix, endpoint, query=query, missing=missing) as response:
            return None if response is None else self._decode(response, endpoint)

    def _pages(self, suffix, endpoint, query):
        result = []
        seen = set()
        totals = {}
        for page in range(1, MAX_PAGES + 1):
            params = dict(query, per_page=PAGE_SIZE, page=page)
            with self._response("GET", suffix, endpoint, query=params) as response:
                values = self._decode(response, endpoint)
                _require(isinstance(values, list) and len(values) <= PAGE_SIZE,
                         "Invalid page from " + endpoint)
                current = response.headers.get("X-Page")
                _require(current is None or current == str(page), "Wrong page from " + endpoint)
                page_size = response.headers.get("X-Per-Page")
                _require(page_size is None or page_size == str(PAGE_SIZE),
                         "Unexpected page size from " + endpoint)
                following = response.headers.get("X-Next-Page")
                _require(following in (None, "", str(page + 1)),
                         "Invalid next page from " + endpoint)
                _require(not following or len(values) == PAGE_SIZE,
                         "Incomplete page from " + endpoint)
                for header in ("X-Total", "X-Total-Pages"):
                    raw = response.headers.get(header)
                    if raw is not None:
                        _require(re.fullmatch(r"[0-9]{1,20}", raw) is not None,
                                 "Invalid pagination total from " + endpoint)
                        value = int(raw)
                        _require(header not in totals or totals[header] == value,
                                 "Pagination total changed for " + endpoint)
                        totals[header] = value
            for item in values:
                item = _object(item, endpoint)
                identifier = _positive_id(item.get("id"))
                _require(identifier not in seen, "Repeated object/page from " + endpoint)
                seen.add(identifier)
                result.append(item)
            # Do not trust missing/empty pagination headers on a full page.
            if len(values) < PAGE_SIZE:
                _require("X-Total" not in totals or totals["X-Total"] == len(result),
                         "Incomplete inventory from " + endpoint)
                pages = (len(result) + PAGE_SIZE - 1) // PAGE_SIZE
                _require("X-Total-Pages" not in totals or totals["X-Total-Pages"] == pages or
                         (not result and totals["X-Total-Pages"] == 1),
                         "Incomplete inventory pages from " + endpoint)
                return result
        raise GitLabAPIError("Pagination limit reached for " + endpoint)

    def project(self):
        result = _object(self._json("", "project statistics", query={"statistics": "true"}),
                         "project statistics")
        _positive_id(result.get("id"))
        _require(result.get("path_with_namespace") == self.project_path,
                 "Project identity changed")
        _object(result.get("statistics"), "project statistics")
        return result

    def head(self, branch):
        result = _object(self._json("/repository/branches/" + quote(_text(branch), safe=""),
                                   "repository branch"), "repository branch")
        return _commit_id(_object(result.get("commit"), "repository branch").get("id"))

    def file(self, path, ref):
        result = self._json("/repository/files/" + _repo_path(path), "repository file",
                            query={"ref": _text(ref)}, missing=True)
        if result is not None:
            result = _object(result, "repository file")
            _require(result.get("file_path") == path, "Repository file identity changed")
        return result

    def packages(self, name):
        _segment(name)
        result = {}
        for status in PACKAGE_STATUSES:
            values = self._pages("/packages", "package inventory", {
                "package_type": "generic", "package_name": name, "status": status,
                "include_versionless": "true", "order_by": "created_at", "sort": "asc",
            })
            for item in values:
                _require(isinstance(item.get("name"), str) and item["name"] and
                         isinstance(item.get("package_type"), str) and item["package_type"],
                         "Incomplete package identity from package inventory")
                if item.get("name") != name or item.get("package_type") != "generic":
                    continue
                identifier = item["id"]
                _require(identifier not in result or result[identifier] == item,
                         "Package changed during inventory")
                result[identifier] = item
        return [result[identifier] for identifier in sorted(result)]

    def package(self, identifier):
        suffix = "/packages/" + _positive_id(identifier)
        result = self._json(suffix, "package detail", missing=True)
        if result is not None:
            result = _object(result, "package detail")
            _require(type(result.get("id")) is int and result["id"] == identifier,
                     "Package identity changed")
        # GitLab's detail endpoint hides non-default/deprecated statuses. A
        # caller must use packages(name) before treating None as deletion proof.
        return result

    def files(self, identifier):
        return self._pages("/packages/" + _positive_id(identifier) + "/package_files",
                           "package files", {"order_by": "id", "sort": "asc"})

    @staticmethod
    def _generic_path(name, version, filename):
        return "/packages/generic/" + "/".join(_segment(value) for value in (name, version, filename))

    def upload(self, name, version, filename, path):
        suffix = self._generic_path(name, version, filename)
        path = Path(path)
        try:
            _require(not path.is_symlink(), "Upload source must be a regular file")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as source:
                before = os.fstat(source.fileno())
                _require(stat.S_ISREG(before.st_mode), "Upload source must be a regular file")
                body = _UploadStream(source, before.st_size)
                with self._response("PUT", suffix, "generic package upload", data=body,
                                    content_type="application/octet-stream", content_length=before.st_size,
                                    expected=201):
                    _require(body.remaining == 0, "Upload source was not fully sent")
                _require(_stamp(before) == _stamp(os.fstat(source.fileno())) == _stamp(path.lstat()),
                         "Upload source changed while sending")
        except OSError:
            raise GitLabAPIError("Upload source could not be read") from None

    def verify_download(self, name, version, filename, expected):
        _require(isinstance(expected, dict) and type(expected.get("bytes")) is int and
                 expected["bytes"] >= 0 and isinstance(expected.get("sha256"), str) and
                 re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]), "Invalid download expectation")
        suffix = self._generic_path(name, version, filename)
        digest = hashlib.sha256()
        count = 0
        # End-user updaters have no publisher credential. A privileged download
        # would hide a private/inaccessible registry and cannot prove availability.
        with self._response("GET", suffix, "generic package download",
                            accept="application/octet-stream", auth=False) as response:
            length = _length(response.headers, "generic package download")
            _require(length is None or length == expected["bytes"], "Download size differs from approved bytes")
            while True:
                block = response.read(min(BLOCK_BYTES, expected["bytes"] + 1 - count))
                if not block:
                    break
                count += len(block)
                _require(count <= expected["bytes"], "Download exceeds approved size")
                digest.update(block)
        _require(count == expected["bytes"] and digest.hexdigest() == expected["sha256"],
                 "Download differs from approved bytes")

    def commit(self, branch, actions, message):
        _text(branch)
        _require(isinstance(actions, list) and actions and all(isinstance(item, dict) for item in actions),
                 "Invalid repository commit actions")
        _require(isinstance(message, str) and message.strip(), "Invalid repository commit message")
        try:
            data = json.dumps({"branch": branch, "actions": actions, "commit_message": message},
                              allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, UnicodeError):
            raise GitLabAPIError("Invalid repository commit input") from None
        _require(len(data) <= JSON_LIMIT, "Repository commit request too large")
        with self._response("POST", "/repository/commits", "repository commit", data=data,
                            content_type="application/json", content_length=len(data), expected=201) as response:
            result = _object(self._decode(response, "repository commit"), "repository commit")
        return _commit_id(result.get("id"))

    def delete_package(self, identifier):
        with self._response("DELETE", "/packages/" + _positive_id(identifier), "package deletion", expected=204):
            pass
