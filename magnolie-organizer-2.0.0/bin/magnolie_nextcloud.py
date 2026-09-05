#!/usr/bin/env python3
"""Sicherer direkter Nextcloud-DAV-Zugang fuer Magnolie Organizer."""

import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import ssl
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET


TIMEOUT = 12.0
XML_LIMIT = 2 * 1024 * 1024
ITEM_LIMIT = 42 * 1024 * 1024
LIST_LIMIT = 10000
MESSAGE_DOMAIN = b"magnolie-baum-1-webdav-message-v1\0"
RECEIPT_DOMAIN = b"magnolie-baum-1-webdav-receipt-v1\0"
DAV = "{DAV:}"
CALDAV = "{urn:ietf:params:xml:ns:caldav}"
CARDDAV = "{urn:ietf:params:xml:ns:carddav}"


class NextcloudError(RuntimeError):
    def __init__(self, message, code="nextcloud_error"):
        super().__init__(message)
        self.code = code


class HttpStatusError(NextcloudError):
    def __init__(self, status, message="Der Nextcloud-WebDAV-Aufruf ist fehlgeschlagen."):
        super().__init__("%s (HTTP %d)" % (message, status), "http_%d" % status)
        self.status = status


def _reject_local_ics_attachments(text):
    unfolded = []
    for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    for line in unfolded:
        if not re.match(r"(?i)^ATTACH(?:;|:)", line):
            continue
        quoted = False
        separator = -1
        for index, character in enumerate(line):
            if character == '"':
                quoted = not quoted
            elif character == ":" and not quoted:
                separator = index
                break
        if separator < 0:
            continue
        value = line[separator + 1:].strip()
        if (value.lower().startswith("file:") or
                re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", value) or
                value.startswith(("~/", "~\\"))):
            raise NextcloudError(
                "CalDAV-Synchronisierung gesperrt: Ein ICS-Anhang verweist auf einen lokalen Dateipfad. Die lokalen Rohdaten bleiben erhalten.",
                "local_attachment")


def error_code(error):
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ValueError):
        return "invalid_input"
    return getattr(error, "code", "nextcloud_error")


def validate_account_type(value):
    value = str(value or "nextcloud").strip().lower()
    if value not in ("nextcloud", "generic-dav"):
        raise ValueError("Die DAV-Kontoart ist ungueltig.")
    return value


def validate_server(value):
    value = str(value or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("Die Nextcloud-Serverbasis muss eine absolute HTTPS-Adresse ohne Zugangsdaten, Query oder Fragment sein.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Die Nextcloud-Serverbasis ist ungueltig.") from error
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    authority = host if port in (None, 443) else "%s:%d" % (host, port)
    path = "/" + parsed.path.strip("/") if parsed.path.strip("/") else ""
    return "https://%s%s" % (authority, path)


def validate_user(value):
    value = str(value or "").strip()
    if not 1 <= len(value) <= 256 or ":" in value or any(ord(char) < 32 for char in value):
        raise ValueError("Der Nextcloud-Benutzer ist ungueltig.")
    return value


def _atomic_json(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".nextcloud-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            fd = -1
            json.dump(value, output, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        parent = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)


class SecretServiceStore:
    """App-Kennwort ausschliesslich im angemeldeten Secret Service."""

    SCHEMA_NAME = "io.gitlab.maik3531.MagnolieOrganizer.Nextcloud"

    def __init__(self, backend=None):
        self.backend = backend

    def _secret(self):
        if self.backend is not None:
            return self.backend
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
            schema = Secret.Schema.new(self.SCHEMA_NAME, Secret.SchemaFlags.NONE,
                                       {"account": Secret.SchemaAttributeType.STRING})
            return Secret, schema
        except Exception as error:
            raise NextcloudError(
                "Der Linux Secret Service ist nicht verfuegbar; das App-Kennwort wurde nicht gespeichert.",
                "secret_service_unavailable") from error

    def store(self, account, password):
        if not isinstance(password, str) or not 1 <= len(password) <= 4096:
            raise ValueError("Das Nextcloud-App-Kennwort fehlt oder ist zu lang.")
        backend = self._secret()
        if hasattr(backend, "store"):
            try:
                stored = backend.store(account, password)
            except Exception as error:
                raise NextcloudError(
                    "Der Linux Secret Service hat das App-Kennwort nicht gespeichert.",
                    "secret_store_failed") from error
            if stored is False:
                raise NextcloudError("Der Linux Secret Service hat das App-Kennwort nicht gespeichert.",
                                     "secret_store_failed")
            return
        Secret, schema = backend
        if not Secret.password_store_sync(schema, {"account": account},
                                          Secret.COLLECTION_DEFAULT,
                                          "Magnolie Organizer Nextcloud", password, None):
            raise NextcloudError("Der Linux Secret Service hat das App-Kennwort nicht gespeichert.",
                                 "secret_store_failed")

    def lookup(self, account):
        backend = self._secret()
        if hasattr(backend, "lookup"):
            try:
                return backend.lookup(account)
            except Exception as error:
                raise NextcloudError("Der Linux Secret Service ist nicht verfuegbar.",
                                     "secret_service_unavailable") from error
        Secret, schema = backend
        return Secret.password_lookup_sync(schema, {"account": account}, None)

    def clear(self, account):
        backend = self._secret()
        if hasattr(backend, "clear"):
            try:
                return backend.clear(account)
            except Exception as error:
                raise NextcloudError("Der Linux Secret Service ist nicht verfuegbar.",
                                     "secret_service_unavailable") from error
        Secret, schema = backend
        return Secret.password_clear_sync(schema, {"account": account}, None)


class NextcloudSettingsStore:
    def __init__(self, path, secrets=None):
        self.path = path
        self.secrets = secrets or SecretServiceStore()

    @staticmethod
    def account(server, user, account_type="nextcloud"):
        account_type = validate_account_type(account_type)
        discriminator = "" if account_type == "nextcloud" else account_type + "\0"
        return hashlib.sha256((discriminator + validate_server(server) + "\0" +
                               validate_user(user)).encode("utf-8")).hexdigest()

    def load(self):
        try:
            if os.path.getsize(self.path) > 16384:
                raise ValueError
            with open(self.path, "r", encoding="utf-8") as source:
                value = json.load(source)
            keys = set(value)
            if keys not in ({"aktiv", "server", "benutzer"},
                            {"davAktiv", "briefkastenAktiv", "server", "benutzer"},
                            {"kontoArt", "davAktiv", "briefkastenAktiv", "server", "benutzer"}):
                raise ValueError
            account_type = validate_account_type(value.get("kontoArt", "nextcloud"))
            old_active = value.get("aktiv")
            dav_active = value.get("davAktiv", old_active)
            mailbox_active = value.get("briefkastenAktiv", old_active)
            if not isinstance(dav_active, bool) or not isinstance(mailbox_active, bool):
                raise ValueError
            if account_type == "generic-dav" and mailbox_active:
                raise ValueError
            return {"kontoArt": account_type, "davAktiv": dav_active,
                    "briefkastenAktiv": mailbox_active,
                    "server": validate_server(value["server"]),
                    "benutzer": validate_user(value["benutzer"])}
        except FileNotFoundError:
            return None
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise NextcloudError("Die Nextcloud-Einstellungen sind ungueltig.",
                                 "invalid_config") from error

    def has_password(self, settings=None):
        settings = settings or self.load()
        if not settings:
            return False
        return bool(self.secrets.lookup(self.account(settings["server"], settings["benutzer"],
                                                     settings.get("kontoArt"))))

    def password(self, settings=None):
        settings = settings or self.load()
        if not settings:
            raise NextcloudError("Nextcloud ist nicht eingerichtet.", "not_configured")
        password = self.secrets.lookup(self.account(settings["server"], settings["benutzer"],
                                                    settings.get("kontoArt")))
        if not password:
            raise NextcloudError("Das Nextcloud-App-Kennwort fehlt.", "app_password_missing")
        return password

    def save(self, dav_active, mailbox_active, server, user, password="",
              delete_password=False, account_type="nextcloud"):
        account_type = validate_account_type(account_type)
        if account_type == "generic-dav" and mailbox_active:
            raise ValueError("Der Magnolienbaum-Briefkasten benoetigt ein Nextcloud-Konto.")
        server, user = validate_server(server), validate_user(user)
        previous = self.load()
        old_account = self.account(previous["server"], previous["benutzer"],
                                   previous.get("kontoArt")) if previous else ""
        account = self.account(server, user, account_type)
        if delete_password and password:
            raise ValueError("Das Kennwort kann nicht gleichzeitig geloescht und ersetzt werden.")
        if (dav_active or mailbox_active) and delete_password:
            raise NextcloudError("Das Nextcloud-App-Kennwort fehlt.", "app_password_missing")
        if (dav_active or mailbox_active) and not password and (account != old_account or not self.has_password(previous)):
            raise NextcloudError("Das Nextcloud-App-Kennwort fehlt.", "app_password_missing")
        previous_secret = self.secrets.lookup(account) if account == old_account else None
        changed_secret = bool(password or delete_password)
        config_written = False
        try:
            if password:
                self.secrets.store(account, password)
            elif delete_password:
                self.secrets.clear(account)
            # Erst nach erfolgreicher Secret-Service-Aktion wird die Config sichtbar.
            _atomic_json(self.path, {"kontoArt": account_type,
                                    "davAktiv": bool(dav_active),
                                    "briefkastenAktiv": bool(mailbox_active),
                                    "server": server, "benutzer": user})
            config_written = True
            if old_account and old_account != account:
                self.secrets.clear(old_account)
        except Exception:
            if changed_secret:
                if previous_secret:
                    self.secrets.store(account, previous_secret)
                else:
                    self.secrets.clear(account)
            if config_written and previous:
                _atomic_json(self.path, previous)
            raise
        return self.load()


class DavHttpClient:
    def __init__(self, server, user, password, transport=None, timeout=TIMEOUT,
                 ssl_context=None):
        self.server = validate_server(server)
        self.user = validate_user(user)
        self.password = password
        self.transport = transport
        self.timeout = min(float(timeout), TIMEOUT)
        self.ssl_context = ssl_context or ssl.create_default_context()
        parsed = urllib.parse.urlsplit(self.server)
        self.origin = (parsed.scheme, parsed.hostname.lower(), parsed.port or 443)

    def same_origin_url(self, value, base=None):
        url = urllib.parse.urljoin(base or self.server + "/", str(value or ""))
        parsed = urllib.parse.urlsplit(url)
        try:
            origin = (parsed.scheme, (parsed.hostname or "").lower(), parsed.port or 443)
        except ValueError as error:
            raise NextcloudError("Die DAV-Antwort enthaelt eine ungueltige Adresse.") from error
        if (origin != self.origin or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment):
            raise NextcloudError("Die DAV-Antwort verweist auf einen anderen Origin.")
        configured = urllib.parse.urlsplit(self.server)
        return urllib.parse.urlunsplit(("https", configured.netloc, parsed.path, "", ""))

    def request(self, method, url, body=b"", headers=None, limit=XML_LIMIT,
                expected=None, redirects=1):
        url = self.same_origin_url(url)
        headers = dict(headers or {})
        token = base64.b64encode((self.user + ":" + self.password).encode("utf-8")).decode("ascii")
        headers["Authorization"] = "Basic " + token
        headers.setdefault("User-Agent", "Magnolie-Organizer-Linux/2.0.17")
        if body:
            headers.setdefault("Content-Length", str(len(body)))
        started = time.monotonic()
        if self.transport is not None:
            status, response_headers, data = self.transport(method, url, headers, body,
                                                             self.timeout, limit)
        else:
            parsed = urllib.parse.urlsplit(url)
            connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443,
                                                      timeout=self.timeout,
                                                      context=self.ssl_context)
            try:
                target = urllib.parse.urlunsplit(("", "", parsed.path or "/",
                                                  parsed.query, ""))
                connection.request(method, target, body=body or None, headers=headers)
                response = connection.getresponse()
                status = response.status
                response_headers = dict(response.getheaders())
                length = response.getheader("Content-Length")
                if length is not None and int(length) > limit:
                    raise NextcloudError("Die WebDAV-Antwort ist zu gross.")
                expected_length = int(length) if length is not None else None
                chunks, size = [], 0
                while True:
                    remaining = self.timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise TimeoutError("Der Nextcloud-Aufruf hat die 12-Sekunden-Frist ueberschritten.")
                    if connection.sock is not None:
                        connection.sock.settimeout(remaining)
                    chunk = response.read(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise NextcloudError("Die WebDAV-Antwort ist zu gross.")
                    chunks.append(chunk)
                data = b"".join(chunks)
                if expected_length is not None and len(data) != expected_length:
                    raise NextcloudError(
                        "Die WebDAV-Antwort wurde unvollstaendig uebertragen.",
                        "incomplete_response")
            finally:
                connection.close()
        if time.monotonic() - started > self.timeout:
            raise TimeoutError("Der Nextcloud-Aufruf hat die 12-Sekunden-Frist ueberschritten.")
        if len(data) > limit:
            raise NextcloudError("Die WebDAV-Antwort ist zu gross.")
        if 300 <= status < 400:
            location = {str(k).lower(): str(v) for k, v in response_headers.items()}.get("location")
            if not location or redirects <= 0:
                raise HttpStatusError(status, "Die DAV-Weiterleitung wurde nicht verfolgt.")
            redirected = self.same_origin_url(location, url)
            return self.request(method, redirected, body, headers, limit, expected,
                                redirects - 1)
        if expected is not None and status not in expected:
            raise HttpStatusError(status)
        self.last_response_url = url
        return status, {str(k).lower(): str(v) for k, v in response_headers.items()}, data


def parse_xml(data, limit=XML_LIMIT):
    if not isinstance(data, bytes) or len(data) > limit:
        raise NextcloudError("Die WebDAV-XML-Antwort ist zu gross.")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise NextcloudError("DTD und Entities sind in DAV-Antworten nicht erlaubt.")
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise NextcloudError("Die WebDAV-XML-Antwort ist ungueltig.") from error


def _propfind(properties):
    body = ET.Element(DAV + "propfind")
    prop = ET.SubElement(body, DAV + "prop")
    for name in properties:
        ET.SubElement(prop, name)
    return ET.tostring(body, encoding="utf-8", xml_declaration=True)


def _responses(data, limit=XML_LIMIT, strict=False):
    root = parse_xml(data, limit)
    result = []
    for response in root.findall(".//" + DAV + "response")[:LIST_LIMIT + 1]:
        href = response.findtext(DAV + "href") or ""
        properties = {}
        propstats = response.findall(DAV + "propstat")
        response_status = response.findtext(DAV + "status") or ""
        if strict and (not href or not response_status and not propstats):
            raise NextcloudError("Die DAV-Multistatus-Antwort ist unvollstaendig.",
                                 "partial_multistatus")
        if strict and response_status and " 200 " not in response_status:
            raise NextcloudError("Die DAV-Multistatus-Antwort ist unvollstaendig.",
                                 "partial_multistatus")
        for propstat in propstats:
            status = propstat.findtext(DAV + "status") or ""
            if " 200 " not in status:
                if strict:
                    raise NextcloudError(
                        "Die DAV-Multistatus-Antwort ist unvollstaendig.",
                        "partial_multistatus")
                continue
            prop = propstat.find(DAV + "prop")
            if prop is not None:
                for child in prop:
                    properties[child.tag] = child
        result.append((href, properties))
    if len(result) > LIST_LIMIT:
        raise NextcloudError("Die DAV-Sammlung enthaelt zu viele Eintraege.")
    return result


def source_id(kind, href, account_type="nextcloud"):
    provider = "generic-dav" if validate_account_type(account_type) == "generic-dav" else "nextcloud"
    prefix = provider + ("-calendar:" if kind == "calendar" else "-addressbook:")
    return prefix + hashlib.sha256(href.encode("utf-8")).hexdigest()


class NextcloudDav:
    def __init__(self, client):
        self.client = client

    def propfind(self, url, properties, depth="0"):
        body = _propfind(properties)
        _status, _headers, data = self.client.request(
            "PROPFIND", url, body, {"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
            XML_LIMIT, {207})
        return _responses(data)

    def _home(self, kind):
        namespace = CALDAV if kind == "calendar" else CARDDAV
        home_name = namespace + ("calendar-home-set" if kind == "calendar" else "addressbook-home-set")
        parsed = urllib.parse.urlsplit(self.client.server)
        origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        well_known = origin + ("/.well-known/caldav" if kind == "calendar" else "/.well-known/carddav")
        account_type = getattr(self.client, "account_type", "nextcloud")
        principal_paths = [well_known]
        if account_type == "generic-dav":
            configured_base = self.client.server + "/"
            if configured_base not in principal_paths:
                principal_paths.append(configured_base)
        else:
            principal_paths.append(self.client.server + "/remote.php/dav/principals/users/" +
                                   urllib.parse.quote(self.client.user, safe="") + "/")
        for target in principal_paths:
            try:
                rows = self.propfind(target, [DAV + "current-user-principal", home_name])
                if rows:
                    response_base = getattr(self.client, "last_response_url", target)
                    properties = rows[0][1]
                    home = properties.get(home_name)
                    href = home.findtext(DAV + "href") if home is not None else ""
                    if href:
                        return self.client.same_origin_url(href, response_base)
                    principal = properties.get(DAV + "current-user-principal")
                    principal_href = principal.findtext(DAV + "href") if principal is not None else ""
                    if principal_href:
                        principal_url = self.client.same_origin_url(principal_href, response_base)
                        second = self.propfind(principal_url, [home_name])
                        node = second[0][1].get(home_name) if second else None
                        href = node.findtext(DAV + "href") if node is not None else ""
                        if href:
                            return self.client.same_origin_url(href, principal_url)
            except HttpStatusError as error:
                if error.status not in (301, 302, 303, 307, 308, 404, 405):
                    raise
        if account_type == "nextcloud":
            suffix = "/remote.php/dav/calendars/" if kind == "calendar" else "/remote.php/dav/addressbooks/users/"
            return self.client.server + suffix + urllib.parse.quote(self.client.user, safe="") + "/"
        raise NextcloudError("Der DAV-Server hat kein Home-Set bekannt gegeben.",
                             "dav_home_missing")

    def collections(self, kind):
        home = self._home(kind)
        properties = [DAV + "displayname", DAV + "resourcetype", DAV + "sync-token"]
        if kind == "calendar":
            properties.append(CALDAV + "supported-calendar-component-set")
        rows = self.propfind(home, properties, "1")
        marker = CALDAV + "calendar" if kind == "calendar" else CARDDAV + "addressbook"
        result = []
        for href, props in rows:
            resource = props.get(DAV + "resourcetype")
            if resource is None or resource.find(marker) is None:
                continue
            absolute = self.client.same_origin_url(href, home)
            display = props.get(DAV + "displayname")
            components = props.get(CALDAV + "supported-calendar-component-set")
            supports_vtodo = components is None or any(
                child.attrib.get("name", "").upper() == "VTODO" for child in components)
            result.append({"uid": source_id(kind, absolute,
                                             getattr(self.client, "account_type", "nextcloud")), "name":
                           ((display.text or "").strip() if display is not None else "") or
                           urllib.parse.unquote(urllib.parse.urlsplit(absolute).path.rstrip("/").rsplit("/", 1)[-1]),
                           "href": absolute, "art": kind,
                           **({"supportsVtodo": supports_vtodo} if kind == "calendar" else {})})
        return sorted(result, key=lambda item: (item["name"].casefold(), item["uid"]))

    def report(self, collection, kind):
        namespace = CALDAV if kind == "calendar" else CARDDAV
        root = ET.Element(namespace + ("calendar-query" if kind == "calendar" else "addressbook-query"))
        prop = ET.SubElement(root, DAV + "prop")
        ET.SubElement(prop, DAV + "getetag")
        ET.SubElement(prop, namespace + ("calendar-data" if kind == "calendar" else "address-data"))
        if kind == "calendar":
            filt = ET.SubElement(root, CALDAV + "filter")
            ET.SubElement(filt, CALDAV + "comp-filter", {"name": "VCALENDAR"})
        body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        _status, _headers, data = self.client.request(
            "REPORT", collection, body, {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            ITEM_LIMIT, {207})
        data_tag = namespace + ("calendar-data" if kind == "calendar" else "address-data")
        result = []
        for href, props in _responses(data, ITEM_LIMIT, strict=True):
            node, etag = props.get(data_tag), props.get(DAV + "getetag")
            if node is None or not (node.text or "").strip():
                raise NextcloudError("Die DAV-REPORT-Antwort enthaelt keine lesbaren Objektdaten.",
                                     "incomplete_report")
            raw = (node.text or "").encode("utf-8")
            if len(raw) > ITEM_LIMIT:
                raise NextcloudError("Ein DAV-Eintrag ist zu gross.")
            result.append({"href": self.client.same_origin_url(href, collection),
                           "etag": (etag.text or "") if etag is not None else "",
                           "data": node.text or ""})
        return result

    def put(self, href, data, etag=None, create=False):
        if not create and not str(etag or "").strip():
            raise NextcloudError(
                "Der DAV-Eintrag hat keinen ETag und wird nicht ungeschuetzt ueberschrieben.",
                "missing_etag")
        headers = {"Content-Type": "text/calendar; charset=utf-8" if data.lstrip().upper().startswith("BEGIN:VCALENDAR")
                   else "text/vcard; charset=utf-8"}
        if headers["Content-Type"].startswith("text/calendar"):
            _reject_local_ics_attachments(data)
        headers["If-None-Match" if create else "If-Match"] = "*" if create else etag
        status, response_headers, _data = self.client.request(
            "PUT", href, data.encode("utf-8"), headers, XML_LIMIT, {200, 201, 204, 412})
        if status == 412:
            get_status, get_headers, current = self.client.request(
                "GET", href, limit=ITEM_LIMIT, expected={200, 404})
            if get_status != 200 or current != data.encode("utf-8"):
                raise HttpStatusError(412, "Der DAV-Eintrag wurde gleichzeitig geaendert.")
            return get_headers.get("etag", etag or "")
        return response_headers.get("etag", "")

    def delete(self, href, etag):
        status, _headers, _data = self.client.request(
            "DELETE", href, b"", {"If-Match": etag}, XML_LIMIT,
            {200, 204, 404, 412})
        if status == 412:
            raise HttpStatusError(412, "Der DAV-Eintrag wurde gleichzeitig geaendert.")
        return status != 404


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _id(value):
    value = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("Die Magnolienbaum-Kennung ist ungueltig.")
    return value


def _transport_id(value):
    if isinstance(value, str):
        value = base64.b64decode(value, validate=True)
    if not isinstance(value, bytes) or len(value) != 16:
        raise ValueError("Die Transport-ID muss 16 Byte lang sein.")
    return value


def b64url(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def create_mailbox_message(transport_id, sender, recipient, payload, key):
    transport_id = _transport_id(transport_id)
    if len(key) < 32:
        raise ValueError("Der Authentisierungsschluessel ist zu kurz.")
    core = {"format": "baum-1-webdav", "art": "nachricht", "von": _id(sender),
            "an": _id(recipient), "transportId": b64url(transport_id), "inhalt": payload}
    core["mac"] = b64url(hmac.new(key, MESSAGE_DOMAIN + canonical(core), hashlib.sha256).digest())
    return canonical(core)


def create_mailbox_receipt(transport_id, sender, recipient, key):
    transport_id = _transport_id(transport_id)
    if len(key) < 32:
        raise ValueError("Der Authentisierungsschluessel ist zu kurz.")
    core = {"format": "baum-1-webdav", "art": "quittung", "von": _id(sender),
            "an": _id(recipient), "transportId": b64url(transport_id)}
    core["mac"] = b64url(hmac.new(key, RECEIPT_DOMAIN + canonical(core), hashlib.sha256).digest())
    return canonical(core)


def read_mailbox_document(document, transport_id, sender, recipient, key, receipt=False):
    if not isinstance(document, bytes) or not 1 <= len(document) <= ITEM_LIMIT:
        raise NextcloudError("Das WebDAV-Dokument ist zu gross oder leer.")
    try:
        value = json.loads(document.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise NextcloudError("Das WebDAV-Dokument ist ungueltig.") from error
    kind, count, domain = ("quittung", 6, RECEIPT_DOMAIN) if receipt else ("nachricht", 7, MESSAGE_DOMAIN)
    expected = b64url(_transport_id(transport_id))
    if (not isinstance(value, dict) or len(value) != count or
            value.get("format") != "baum-1-webdav" or value.get("art") != kind or
            value.get("von") != _id(sender) or value.get("an") != _id(recipient) or
            value.get("transportId") != expected or not isinstance(value.get("mac"), str)):
        raise NextcloudError("Die WebDAV-Nachricht ist nicht authentisch.")
    try:
        actual = base64.b64decode(value["mac"] + "=" * (-len(value["mac"]) % 4),
                                  altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise NextcloudError("Die WebDAV-Nachricht ist nicht authentisch.") from error
    core = dict(value)
    core.pop("mac")
    expected_mac = hmac.new(key, domain + canonical(core), hashlib.sha256).digest()
    if len(actual) != 32 or not hmac.compare_digest(actual, expected_mac):
        raise NextcloudError("Die WebDAV-Nachricht ist nicht authentisch.")
    return None if receipt else value["inhalt"]


def mailbox_sender(document, transport_id, recipient):
    if not isinstance(document, bytes) or not 1 <= len(document) <= ITEM_LIMIT:
        raise NextcloudError("Das WebDAV-Dokument ist zu gross oder leer.")
    try:
        value = json.loads(document.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise NextcloudError("Das WebDAV-Dokument ist ungueltig.") from error
    if (not isinstance(value, dict) or value.get("format") != "baum-1-webdav" or
            value.get("art") != "nachricht" or value.get("an") != _id(recipient) or
            value.get("transportId") != b64url(_transport_id(transport_id))):
        raise NextcloudError("Die WebDAV-Nachricht ist falsch adressiert.")
    return _id(value.get("von"))


class NextcloudMailbox:
    def __init__(self, client):
        self.client = client

    def _root(self, relative):
        user = urllib.parse.quote(self.client.user, safe="")
        return self.client.server + "/remote.php/dav/files/%s/%s" % (user, relative)

    def ensure(self, own_id):
        _id(own_id)
        for relative in ("Magnolie/", "Magnolie/baum-1/", "Magnolie/baum-1/nachrichten/",
                         "Magnolie/baum-1/nachrichten/%s/" % own_id,
                         "Magnolie/baum-1/quittungen/",
                         "Magnolie/baum-1/quittungen/%s/" % own_id):
            self.client.request("MKCOL", self._root(relative), expected={201, 405})

    def _uri(self, kind, recipient, transport_id):
        return self._root("Magnolie/baum-1/%s/%s/%s.json" %
                          (kind, _id(recipient), _transport_id(transport_id).hex()))

    def put_new(self, uri, document):
        status, _headers, _data = self.client.request(
            "PUT", uri, document, {"If-None-Match": "*", "Content-Type": "application/json; charset=utf-8"},
            XML_LIMIT, {200, 201, 204, 412})
        return status != 412

    def upload(self, transport_id, sender, recipient, payload, key):
        return self.put_new(self._uri("nachrichten", recipient, transport_id),
                            create_mailbox_message(transport_id, sender, recipient, payload, key))

    def receipt_exists(self, transport_id, sender, recipient, key):
        status, _headers, data = self.client.request(
            "GET", self._uri("quittungen", recipient, transport_id),
            limit=ITEM_LIMIT, expected={200, 404})
        if status == 404:
            return False
        read_mailbox_document(data, transport_id, sender, recipient, key, True)
        return True

    def write_receipt(self, transport_id, sender, recipient, key):
        return self.put_new(self._uri("quittungen", recipient, transport_id),
                            create_mailbox_receipt(transport_id, sender, recipient, key))

    def delete(self, kind, recipient, transport_id):
        self.client.request("DELETE", self._uri(kind, recipient, transport_id),
                            expected={200, 204, 404})

    def list_incoming(self, own_id):
        body = _propfind([DAV + "resourcetype"])
        _status, _headers, data = self.client.request(
            "PROPFIND", self._root("Magnolie/baum-1/nachrichten/%s/" % _id(own_id)),
            body, {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            XML_LIMIT, {207})
        result = {}
        for href, _props in _responses(data):
            name = urllib.parse.unquote(urllib.parse.urlsplit(href).path.rsplit("/", 1)[-1])
            if re.fullmatch(r"[0-9a-f]{32}\.json", name):
                result[name] = bytes.fromhex(name[:32])
        return [result[name] for name in sorted(result)]

    def test_access(self, own_id):
        self.ensure(own_id)
        probe = os.urandom(16)
        uri = self._uri("quittungen", own_id, probe)
        try:
            status, _headers, _data = self.client.request(
                "PUT", uri, b'{"format":"magnolie-write-test"}',
                {"If-None-Match": "*", "Content-Type": "application/json"},
                XML_LIMIT, {200, 201, 204})
            if status not in (200, 201, 204):
                raise NextcloudError("Der Nextcloud-Briefkasten ist nicht beschreibbar.",
                                     "mailbox_not_writable")
        finally:
            self.client.request("DELETE", uri, expected={200, 204, 404})

    def get_incoming(self, own_id, transport_id):
        _status, _headers, data = self.client.request(
            "GET", self._uri("nachrichten", own_id, transport_id),
            limit=ITEM_LIMIT, expected={200})
        return data


def configured_client(store, transport=None, purpose="dav"):
    settings = store.load()
    active_key = "briefkastenAktiv" if purpose == "briefkasten" else "davAktiv"
    if not settings or not settings[active_key]:
        raise NextcloudError("Nextcloud ist nicht aktiviert.", "not_active")
    client = DavHttpClient(settings["server"], settings["benutzer"],
                           store.password(settings), transport=transport)
    client.account_type = settings.get("kontoArt", "nextcloud")
    return client
