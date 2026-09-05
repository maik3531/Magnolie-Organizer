import base64
import datetime
import html
import http.client
import http.server
import ipaddress
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import socket
import ssl
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "pruefungen" / "fixtures"
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_nextcloud as nc

loader = importlib.machinery.SourceFileLoader(
    "magnolie_nextcloud_backend_test", str(ROOT / "bin" / "magnolie-organizer"))
spec = importlib.util.spec_from_loader("magnolie_nextcloud_backend_test", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


class SecretBackend:
    def __init__(self, fail=False):
        self.values = {}
        self.fail = fail

    def store(self, account, password):
        if self.fail:
            raise RuntimeError("secret service unavailable")
        self.values[account] = password
        return True

    def lookup(self, account):
        if self.fail:
            raise RuntimeError("secret service unavailable")
        return self.values.get(account)

    def clear(self, account):
        self.values.pop(account, None)
        return True


class HostileHttpsServer:
    def __init__(self, callback, tls_context):
        self.callback = callback
        self.records = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                owner.records.append({"method": self.command, "path": self.path,
                                      "headers": dict(self.headers), "body": body})
                result = owner.callback(self.command, self.path, self.headers, body)
                if result == "abort":
                    self.connection.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\nshort")
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                status, headers, response = result
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            do_GET = do_PUT = do_DELETE = do_PROPFIND = do_REPORT = do_MKCOL = _handle

            def log_message(self, _format, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.socket = tls_context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "https://localhost:%d" % self.server.server_port

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@pytest.fixture
def tls_contexts():
    with tempfile.TemporaryDirectory(prefix="magnolie-nextcloud-tls-") as directory:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]), critical=False)
            .sign(private_key, hashes.SHA256())
        )
        key_path = pathlib.Path(directory) / "tls-private.pem"
        cert_path = pathlib.Path(directory) / "tls-certificate.pem"
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert_path, key_path)
        client_context = ssl.create_default_context(cafile=str(cert_path))
        assert key_path.stat().st_mode & 0o777 == 0o600
        yield server_context, client_context


def dav_response(href, properties):
    values = []
    for name, value in properties:
        values.append("<%s>%s</%s>" % (name, value, name))
    return ("<d:response><d:href>%s</d:href><d:propstat><d:prop>%s</d:prop>"
            "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" %
            (html.escape(href), "".join(values)))


def multistatus(*responses, namespaces=""):
    return ("<?xml version=\"1.0\"?><d:multistatus xmlns:d=\"DAV:\" %s>%s"
            "</d:multistatus>" % (namespaces, "".join(responses))).encode()


@pytest.mark.parametrize("invalid", [
    "http://cloud.example", "//cloud.example", "https://user@cloud.example",
    "https://cloud.example?q=1", "https://cloud.example/#fragment",
])
def test_https_only_and_no_credentials_in_server_url(invalid):
    with pytest.raises(ValueError):
        nc.validate_server(invalid)


def test_secret_service_only_and_atomic_private_config(tmp_path, monkeypatch):
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(str(tmp_path / "nextcloud.json"),
                                      nc.SecretServiceStore(backend))
    store.save(True, True, "https://cloud.example/nc/", "user", "app-secret")
    raw = (tmp_path / "nextcloud.json").read_text()
    assert "app-secret" not in raw and "kennwort" not in raw
    assert '"davAktiv":true' in raw and '"briefkastenAktiv":true' in raw
    assert (os.stat(tmp_path / "nextcloud.json").st_mode & 0o777) == 0o600
    assert store.password() == "app-secret"

    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text('{"aktiv":true,"server":"https://cloud.example","benutzer":"user"}')
    legacy = nc.NextcloudSettingsStore(str(legacy_path), nc.SecretServiceStore(backend)).load()
    assert legacy["davAktiv"] is True and legacy["briefkastenAktiv"] is True

    failing = nc.NextcloudSettingsStore(str(tmp_path / "failed.json"),
                                        nc.SecretServiceStore(SecretBackend(True)))
    with pytest.raises(RuntimeError):
        failing.save(True, True, "https://cloud.example", "user", "never-clear")
    assert not (tmp_path / "failed.json").exists()

    original = nc._atomic_json
    monkeypatch.setattr(nc, "_atomic_json", lambda *_args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        store.save(True, True, "https://cloud.example/nc", "user", "replacement")
    assert store.password() == "app-secret"
    monkeypatch.setattr(nc, "_atomic_json", original)

    old_account = store.account("https://cloud.example/nc", "user")
    store.save(False, False, "https://other.example", "other")
    assert backend.lookup(old_account) is None

    store.save(False, False, "https://third.example", "third", "third-secret")
    third_account = store.account("https://third.example", "third")
    original = nc._atomic_json
    monkeypatch.setattr(nc, "_atomic_json", lambda *_args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        store.save(False, False, "https://fourth.example", "fourth", "new-secret")
    monkeypatch.setattr(nc, "_atomic_json", original)
    assert store.load()["server"] == "https://third.example"
    assert backend.lookup(third_account) == "third-secret"
    assert backend.lookup(store.account("https://fourth.example", "fourth")) is None

    generic = nc.NextcloudSettingsStore(str(tmp_path / "generic.json"),
                                        nc.SecretServiceStore(backend))
    generic.save(True, False, "https://dav.example/dav.php/", "user",
                 "generic-password", account_type="generic-dav")
    assert generic.load()["kontoArt"] == "generic-dav"
    assert generic.password() == "generic-password"
    assert "generic-password" not in (tmp_path / "generic.json").read_text()
    with pytest.raises(ValueError):
        generic.save(True, True, "https://dav.example", "user",
                     account_type="generic-dav")


@pytest.mark.parametrize("status", [401, 403, 404, 405, 507])
def test_hostile_https_statuses_are_reported_once_without_redirect(status, tls_contexts):
    server_context, client_context = tls_contexts
    server = HostileHttpsServer(lambda *_args: (status, {}, b"denied"), server_context)
    try:
        client = nc.DavHttpClient(server.url, "user", "application-password",
                                  ssl_context=client_context)
        with pytest.raises(nc.HttpStatusError) as raised:
            client.request("PROPFIND", server.url + "/dav", expected={207})
        assert raised.value.status == status and len(server.records) == 1
        record = server.records[0]
        assert record["headers"]["Authorization"] == "Basic " + base64.b64encode(
            b"user:application-password").decode()
        assert "application-password" not in record["path"]
    finally:
        server.close()


def test_cross_origin_redirect_is_never_followed(tls_contexts):
    server_context, client_context = tls_contexts
    server = HostileHttpsServer(
        lambda *_args: (302, {"Location": "https://evil.example/steal"}, b""),
        server_context)
    try:
        client = nc.DavHttpClient(server.url, "user", "secret", ssl_context=client_context)
        with pytest.raises(nc.NextcloudError) as raised:
            client.request("GET", server.url + "/redirect")
        assert len(server.records) == 1
        with pytest.raises(nc.NextcloudError):
            client.request("GET", "https://evil.example/steal")
        assert len(server.records) == 1
    finally:
        server.close()


def test_timeout_abort_and_large_response_fail_closed(tls_contexts):
    def callback(_method, path, _headers, _body):
        if path == "/timeout":
            time.sleep(0.2)
            return 200, {}, b"late"
        if path == "/abort":
            return "abort"
        return 200, {}, b"x" * 1025

    server_context, client_context = tls_contexts
    server = HostileHttpsServer(callback, server_context)
    try:
        timeout_client = nc.DavHttpClient(server.url, "user", "secret", timeout=0.05,
                                          ssl_context=client_context)
        with pytest.raises((TimeoutError, OSError)):
            timeout_client.request("GET", server.url + "/timeout", limit=10)
        client = nc.DavHttpClient(server.url, "user", "secret", ssl_context=client_context)
        with pytest.raises((OSError, nc.NextcloudError, http.client.IncompleteRead)):
            client.request("GET", server.url + "/abort", limit=1024)
        with pytest.raises(nc.NextcloudError):
            client.request("GET", server.url + "/large", limit=1024)
    finally:
        server.close()


def test_xxe_and_entity_documents_are_rejected():
    hostile = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM '
               b'"file:///etc/passwd">]><d:multistatus xmlns:d="DAV:">'
               b'<d:href>&e;</d:href></d:multistatus>')
    with pytest.raises(nc.NextcloudError):
        nc.parse_xml(hostile)


def test_partial_multistatus_is_not_misread_as_remote_deletion():
    partial = multistatus(
        '<d:response><d:href>/calendar/item.ics</d:href><d:propstat>'
        '<d:prop><d:getetag/></d:prop><d:status>HTTP/1.1 507 Insufficient Storage</d:status>'
        '</d:propstat></d:response>')
    with pytest.raises(nc.NextcloudError) as raised:
        nc._responses(partial, strict=True)
    assert raised.value.code == "partial_multistatus"


def test_discovery_listing_reports_and_stable_source_ids():
    records = []
    calendar_home = "https://cloud.example/nc/remote.php/dav/calendars/user/"
    address_home = "https://cloud.example/nc/remote.php/dav/addressbooks/users/user/"
    calendar = calendar_home + "work/"
    addressbook = address_home + "contacts/"
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:event-1\r\n"
           "DTSTART;VALUE=DATE:20260108\r\nRRULE:FREQ=MONTHLY;BYDAY=2TH\r\n"
           "SUMMARY:Ordinal\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    vcf = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-1\r\nN:Example;Ada;;;\r\n"
           "FN:Ada Example\r\nTEL;TYPE=HOME:1\r\nTEL;TYPE=CELL:2\r\n"
           "EMAIL:a@example.test\r\nPHOTO;ENCODING=b;TYPE=JPEG:/9j/2Q==\r\nEND:VCARD\r\n")

    def transport(method, url, headers, body, timeout, limit):
        records.append((method, url, headers, body, timeout, limit))
        if ".well-known/caldav" in url:
            return 207, {}, multistatus(dav_response(url, [
                ("c:calendar-home-set", "<d:href>%s</d:href>" % calendar_home)]),
                namespaces='xmlns:c="urn:ietf:params:xml:ns:caldav"')
        if ".well-known/carddav" in url:
            return 207, {}, multistatus(dav_response(url, [
                ("a:addressbook-home-set", "<d:href>%s</d:href>" % address_home)]),
                namespaces='xmlns:a="urn:ietf:params:xml:ns:carddav"')
        if method == "PROPFIND" and url == calendar_home:
            return 207, {}, multistatus(dav_response(calendar, [
                ("d:displayname", "Work"),
                ("d:resourcetype", '<c:calendar xmlns:c="urn:ietf:params:xml:ns:caldav"/>')]))
        if method == "PROPFIND" and url == address_home:
            return 207, {}, multistatus(dav_response(addressbook, [
                ("d:displayname", "Contacts"),
                ("d:resourcetype", '<a:addressbook xmlns:a="urn:ietf:params:xml:ns:carddav"/>')]))
        if method == "REPORT" and url == calendar:
            return 207, {}, multistatus(dav_response(calendar + "event.ics", [
                ("d:getetag", '&quot;cal-1&quot;'),
                ("c:calendar-data", html.escape(ics))]),
                namespaces='xmlns:c="urn:ietf:params:xml:ns:caldav"')
        if method == "REPORT" and url == addressbook:
            return 207, {}, multistatus(dav_response(addressbook + "contact.vcf", [
                ("d:getetag", '&quot;card-1&quot;'),
                ("a:address-data", html.escape(vcf))]),
                namespaces='xmlns:a="urn:ietf:params:xml:ns:carddav"')
        raise AssertionError((method, url))

    client = nc.DavHttpClient("https://cloud.example/nc", "user", "secret",
                              transport=transport)
    dav = nc.NextcloudDav(client)
    calendars, books = dav.collections("calendar"), dav.collections("addressbook")
    assert calendars[0]["uid"] == nc.source_id("calendar", calendar)
    assert books[0]["uid"] == nc.source_id("addressbook", addressbook)
    cal_item = dav.report(calendar, "calendar")[0]
    card_item = dav.report(addressbook, "addressbook")[0]
    parsed_event = m.ics_lesen(cal_item["data"])["termine"][0]
    parsed_contact = m.vcf_lesen(card_item["data"])["kontakte"][0]
    assert parsed_event["wiederholung"] == {
        "art": "monthly", "bis": "", "ordinal": 2, "wochentag": "TH"}
    assert len(parsed_contact["telefone"]) == 2 and parsed_contact["foto"].startswith(
        "data:image/jpeg;base64,")
    assert all(record[2]["Authorization"].startswith("Basic ") for record in records)


def test_generic_baikal_discovery_relative_redirects_and_vtodo_capability():
    calls = []

    def transport(method, url, headers, body, _timeout, _limit):
        calls.append((method, url, headers, body))
        path = urllib.parse.urlsplit(url).path
        if path == "/.well-known/caldav":
            return 301, {"Location": "/dav.php/"}, b""
        if path == "/dav.php/":
            return 207, {}, multistatus(dav_response("dav.php/", [
                ("d:current-user-principal", "<d:href>principals/alice/</d:href>")]))
        if path == "/dav.php/principals/alice/":
            return 207, {}, multistatus(dav_response(path, [
                ("c:calendar-home-set", "<d:href>../../calendars/alice/</d:href>")]),
                namespaces='xmlns:c="urn:ietf:params:xml:ns:caldav"')
        if path == "/.well-known/carddav":
            return 207, {}, multistatus(dav_response(path, [
                ("a:addressbook-home-set", "<d:href>/dav.php/addressbooks/alice/</d:href>")]),
                namespaces='xmlns:a="urn:ietf:params:xml:ns:carddav"')
        if path == "/dav.php/calendars/alice/":
            components = ('<c:supported-calendar-component-set>'
                          '<c:comp name="VEVENT"/></c:supported-calendar-component-set>')
            return 207, {}, multistatus(dav_response("work/", [
                ("d:displayname", "Work"),
                ("d:resourcetype", '<c:calendar xmlns:c="urn:ietf:params:xml:ns:caldav"/>'),
                ("c:supported-calendar-component-set", components.split(">", 1)[1].rsplit("<", 1)[0])]),
                namespaces='xmlns:c="urn:ietf:params:xml:ns:caldav"')
        if path == "/dav.php/addressbooks/alice/":
            return 207, {}, multistatus(dav_response("contacts/", [
                ("d:displayname", "Contacts"),
                ("d:resourcetype", '<a:addressbook xmlns:a="urn:ietf:params:xml:ns:carddav"/>')]),
                namespaces='xmlns:a="urn:ietf:params:xml:ns:carddav"')
        raise AssertionError((method, url))

    client = nc.DavHttpClient("https://dav.example/dav.php/", "alice", "not-in-errors",
                              transport=transport)
    client.account_type = "generic-dav"
    dav = nc.NextcloudDav(client)
    calendars = dav.collections("calendar")
    books = dav.collections("addressbook")
    assert calendars == [{"uid": "generic-dav-calendar:ff15e1cb495b36c977ba783d0848a6845514d25b04d0bfc5cadcff6a6c86c014",
                          "name": "Work", "href": "https://dav.example/dav.php/calendars/alice/work/",
                          "art": "calendar", "supportsVtodo": False}]
    assert books[0]["uid"].startswith("generic-dav-addressbook:")
    assert all("remote.php" not in url for _method, url, _headers, _body in calls)
    assert sum(url.endswith("/dav.php/") for _method, url, _headers, _body in calls) == 1


def test_generic_discovery_falls_back_to_configured_subpath_base():
    calls = []
    home = "https://dav.example/dav.php/calendars/alice/"

    def transport(method, url, _headers, _body, _timeout, _limit):
        calls.append((method, url))
        path = urllib.parse.urlsplit(url).path
        if path == "/.well-known/caldav":
            return 404, {}, b""
        if path == "/dav.php/":
            return 207, {}, multistatus(dav_response(path, [
                ("d:current-user-principal", "<d:href>principals/alice/</d:href>")]))
        if path == "/dav.php/principals/alice/":
            return 207, {}, multistatus(dav_response(path, [
                ("c:calendar-home-set", "<d:href>../../calendars/alice/</d:href>")]),
                namespaces='xmlns:c="urn:ietf:params:xml:ns:caldav"')
        if url == home:
            return 207, {}, multistatus()
        raise AssertionError((method, url))

    client = nc.DavHttpClient("https://dav.example/dav.php", "alice", "secret",
                              transport=transport)
    client.account_type = "generic-dav"
    assert nc.NextcloudDav(client).collections("calendar") == []
    assert calls[:3] == [
        ("PROPFIND", "https://dav.example/.well-known/caldav"),
        ("PROPFIND", "https://dav.example/dav.php/"),
        ("PROPFIND", "https://dav.example/dav.php/principals/alice/"),
    ]


def test_dav_etag_conflict_and_conditional_create_delete():
    records = []

    def transport(method, url, headers, body, _timeout, _limit):
        records.append((method, url, headers, body))
        if method == "PUT" and headers.get("If-None-Match") == "*":
            return 201, {"ETag": '"new"'}, b""
        return 412, {}, b""

    dav = nc.NextcloudDav(nc.DavHttpClient(
        "https://cloud.example", "user", "secret", transport=transport))
    assert dav.put("https://cloud.example/cal/a.ics", "BEGIN:VCALENDAR", create=True) == '"new"'
    with pytest.raises(nc.HttpStatusError) as raised:
        dav.put("https://cloud.example/cal/a.ics", "BEGIN:VCALENDAR", '"old"')
    assert raised.value.status == 412
    with pytest.raises(nc.HttpStatusError):
        dav.delete("https://cloud.example/cal/a.ics", '"old"')
    assert records[1][2]["If-Match"] == '"old"' and records[3][2]["If-Match"] == '"old"'


def test_dav_put_without_etag_is_rejected_before_network_access():
    records = []
    dav = nc.NextcloudDav(nc.DavHttpClient(
        "https://cloud.example", "user", "secret",
        transport=lambda *args: records.append(args)))
    with pytest.raises(nc.NextcloudError) as raised:
        dav.put("https://cloud.example/cal/a.ics", "BEGIN:VCALENDAR", "")
    assert raised.value.code == "missing_etag"
    assert records == []


def test_caldav_put_rejects_local_attachment_before_network_access():
    records = []

    def transport(method, url, headers, body, _timeout, _limit):
        records.append((method, url, headers, body))
        return 201, {"ETag": '"new"'}, b""

    dav = nc.NextcloudDav(nc.DavHttpClient(
        "https://cloud.example", "user", "secret", transport=transport))
    text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:local\r\n"
            "ATTACH;X-REF=\"urn:test\";FMTTYPE=application/pdf:file:///home/mia/very\r\n"
            " private.pdf\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    with pytest.raises(nc.NextcloudError) as raised:
        dav.put("https://cloud.example/cal/local.ics", text, create=True)
    assert raised.value.code == "local_attachment"
    assert records == []


def test_deterministic_put_412_is_verified_as_resume_success():
    text = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:u1\r\nFN:Probe\r\nEND:VCARD\r\n"
    calls = []

    def transport(method, url, headers, body, _timeout, _limit):
        calls.append((method, url))
        if method == "PUT":
            return 412, {}, b""
        return 200, {"ETag": '"resumed"'}, text.encode()

    dav = nc.NextcloudDav(nc.DavHttpClient(
        "https://cloud.example", "user", "secret", transport=transport))
    assert dav.put("https://cloud.example/book/u1.vcf", text, create=True) == '"resumed"'
    assert [call[0] for call in calls] == ["PUT", "GET"]


def test_windows_hmac_goldens_and_tamper_rejection():
    vector = json.loads((FIXTURES / "windows-nextcloud-mailbox.json").read_text())
    protocol_transport_id = bytes(range(16))
    nonsecret_hmac_protocol_vector = bytes(range(1, 33))
    assert protocol_transport_id.hex() == vector["transport_id_hex"]
    message = nc.create_mailbox_message(
        protocol_transport_id, "alpha", "beta", {"text": "Blüte"},
        nonsecret_hmac_protocol_vector)
    receipt = nc.create_mailbox_receipt(
        protocol_transport_id, "beta", "alpha", nonsecret_hmac_protocol_vector)
    assert message.decode() == vector["message"] and receipt.decode() == vector["receipt"]
    assert nc.read_mailbox_document(
        message, protocol_transport_id, "alpha", "beta",
        nonsecret_hmac_protocol_vector) == {
        "text": "Blüte"}
    nc.read_mailbox_document(
        receipt, protocol_transport_id, "beta", "alpha",
        nonsecret_hmac_protocol_vector, True)
    e2e = nc.create_mailbox_message(
        protocol_transport_id, "alpha", "beta", vector["e2e_envelope"],
        nonsecret_hmac_protocol_vector)
    assert e2e.decode() == vector["e2e_message"]
    assert nc.read_mailbox_document(
        vector["e2e_message"].encode(), protocol_transport_id, "alpha", "beta",
        nonsecret_hmac_protocol_vector
    ) == vector["e2e_envelope"]
    changed = json.loads(message)
    changed["inhalt"]["text"] = "changed"
    with pytest.raises(nc.NextcloudError):
        nc.read_mailbox_document(
            nc.canonical(changed), protocol_transport_id, "alpha", "beta",
            nonsecret_hmac_protocol_vector)


def test_mailbox_exact_windows_paths_listing_and_idempotent_put():
    requests = []
    listed = bytes(range(16, 32))
    puts = 0

    def transport(method, url, headers, body, _timeout, _limit):
        nonlocal puts
        requests.append((method, url, headers, body))
        if method == "MKCOL":
            return 201, {}, b""
        if method == "PUT":
            puts += 1
            return (201 if puts == 1 else 412), {}, b""
        if method == "PROPFIND":
            listing = multistatus(
                dav_response(url, []),
                dav_response(url + listed.hex() + ".json", []),
                dav_response(url + "not-a-message.txt", []))
            return 207, {}, listing
        raise AssertionError((method, url))

    client = nc.DavHttpClient("https://cloud.example/nc", "a b@example.test",
                              "application-password", transport=transport)
    mailbox = nc.NextcloudMailbox(client)
    mailbox.ensure("beta")
    transport_id, key = bytes(range(16)), bytes(range(1, 33))
    assert mailbox.upload(transport_id, "alpha", "beta", {"x": 1}, key)
    assert not mailbox.upload(transport_id, "alpha", "beta", {"x": 1}, key)
    assert mailbox.list_incoming("beta") == [listed]
    assert requests[0][1] == (
        "https://cloud.example/nc/remote.php/dav/files/a%20b%40example.test/Magnolie/")
    assert requests[5][1].endswith("/Magnolie/baum-1/quittungen/beta/")
    assert all("application-password" not in item[1] for item in requests)
    assert all(item[2]["Authorization"].startswith("Basic ") for item in requests)
    put_requests = [item for item in requests if item[0] == "PUT"]
    assert all(item[2]["If-None-Match"] == "*" for item in put_requests)


class FakeMailbox:
    def __init__(self):
        self.ack = False
        self.uploads = []
        self.ensured = []
        self.deleted = []

    def receipt_exists(self, transport_id, sender, recipient, key):
        return self.ack

    def ensure(self, recipient):
        self.ensured.append(recipient)

    def upload(self, transport_id, sender, recipient, envelope, key):
        self.uploads.append((bytes(transport_id), sender, recipient,
                             json.dumps(envelope, sort_keys=True)))
        return len(self.uploads) == 1

    def delete(self, kind, recipient, transport_id):
        self.deleted.append((kind, recipient, bytes(transport_id)))


def tree_pair():
    left, right = m.baum_schluessel_erzeugen("Linux"), m.baum_schluessel_erzeugen("Windows")
    partner = m.baum_partner_aufnehmen(left, "Windows", right["kennung"],
                                       right["oeffentlich"])
    partner["bestaetigt"] = True
    left["an"] = True
    return left, partner


def test_mailbox_fifo_retry_stable_transport_dedupe_and_ack():
    state, partner = tree_pair()
    queued = []
    first = m.baum_einreihen(queued, partner["kennung"], "notiz", {"text": "one"})
    second = m.baum_einreihen(queued, partner["kennung"], "notiz", {"text": "two"})
    mailbox = FakeMailbox()
    start = m.datetime(2026, 8, 17, 10, 0, 0)
    report = m.baum_post_zustellen(state, queued, start, mailbox=mailbox)
    assert report["versucht"] == 1 and len(mailbox.uploads) == 1 and len(queued) == 2
    stable_id = first["transportId"]
    stable_envelope = json.dumps(first["briefUmschlag"], sort_keys=True)
    mailbox.ack = True
    report = m.baum_post_zustellen(
        state, queued, start + m.timedelta(minutes=2), mailbox=mailbox)
    assert report["zugestellt"] == 1 and len(queued) == 1
    assert stable_id == first["transportId"] and stable_envelope == json.dumps(
        first["briefUmschlag"], sort_keys=True)
    assert mailbox.deleted[0][0] == "nachrichten" and second in queued


def test_outbox_blocks_younger_partner_entries_until_oldest_is_due():
    state, first_partner = tree_pair()
    first_partner["adresse"] = "127.0.0.1"
    other_keys = m.baum_schluessel_erzeugen("Other")
    other = m.baum_partner_aufnehmen(state, "Other", other_keys["kennung"],
                                    other_keys["oeffentlich"], "127.0.0.2")
    other["bestaetigt"] = True
    queued = []
    start = m.datetime(2026, 8, 17, 10, 0, 0)
    oldest = m.baum_einreihen(queued, first_partner["kennung"], "notiz",
                              {"text": "oldest"}, start)
    oldest.update({"versuche": 1, "zuletzt": "2026-08-17 10:00:00"})
    younger = m.baum_einreihen(queued, first_partner["kennung"], "notiz",
                               {"text": "younger"}, start)
    independent = m.baum_einreihen(queued, other["kennung"], "notiz",
                                   {"text": "other"}, start)
    sent = []
    sender = lambda url, _envelope: sent.append(url) or True

    report = m.baum_post_zustellen(state, queued, start, sender=sender)
    assert report["zugestellt"] == 1 and len(sent) == 1 and "127.0.0.2" in sent[0]
    assert queued == [oldest, younger] and independent not in queued

    report = m.baum_post_zustellen(state, queued, start + m.timedelta(minutes=1),
                                   sender=sender)
    assert report["zugestellt"] == 1 and len(sent) == 2 and "127.0.0.1" in sent[1]
    assert queued == [younger]


def test_mailbox_envelope_is_persisted_before_first_network_attempt(tmp_path):
    state, partner = tree_pair()
    path = tmp_path / "outbox.json"
    queued = []
    m.baum_einreihen(queued, partner["kennung"], "notiz", {"text": "durable"})
    assert m.baum_post_schreiben(queued, str(path))

    class InspectMailbox(FakeMailbox):
        def receipt_exists(self, transport_id, sender, recipient, key):
            persisted = m.baum_post_lesen(str(path))
            assert persisted[0]["transportId"] == queued[0]["transportId"]
            assert persisted[0]["briefZaehler"] == 1
            assert persisted[0]["briefUmschlag"]["magnolie"] == "baum-1"
            return False

    report = m.baum_post_wartung(
        state, str(path), jetzt=m.datetime(2026, 8, 17, 10, 0, 0),
        mailbox=InspectMailbox())
    assert report["versucht"] == 1
    persisted = m.baum_post_lesen(str(path))
    assert persisted[0]["briefZaehler"] == partner["zaehler_raus"] == 1


def test_direct_http_rejection_does_not_fallback_to_mailbox():
    state, partner = tree_pair()
    partner["adresse"] = "127.0.0.1"
    mailbox = FakeMailbox()

    def rejected(url, envelope):
        raise urllib.error.HTTPError(url, 503, "unavailable", {}, None)

    assert not m.baum_senden(state, partner, "notiz", {"text": "x"},
                             sender=rejected, transport_id=base64.b64encode(
                                 bytes(range(16))).decode(), mailbox=mailbox)
    assert mailbox.uploads == []


class SyncDav:
    def __init__(self, resources, fail_put=False, supports_vtodo=True):
        self.resources = resources
        self.fail_put = fail_put
        self.supports_vtodo = supports_vtodo
        self.puts = []
        self.deletes = []

    def collections(self, kind):
        href = "https://cloud.example/%s/" % kind
        return [{"uid": nc.source_id(kind, href), "name": kind,
                 "href": href, "art": kind,
                 **({"supportsVtodo": self.supports_vtodo} if kind == "calendar" else {})}]

    def report(self, _href, kind):
        return list(self.resources[kind])

    def put(self, href, data, etag=None, create=False):
        self.puts.append((href, data, etag, create))
        if self.fail_put:
            raise nc.HttpStatusError(412)
        return '"written"'

    def delete(self, href, etag):
        self.deletes.append((href, etag))
        return True


class SyncProbe:
    def __init__(self):
        self.snapshots = []
        self.payload = None

    def _journal_snapshot(self, reason):
        self.snapshots.append(reason)

    def antwort(self, callback, payload):
        assert callback == "App.syncFertig"
        self.payload = payload


def event_ics(uid="remote", title="Remote", modified="20260817T100000Z",
              rrule="RRULE:FREQ=MONTHLY;BYDAY=2TH\r\n"):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:%s\r\n"
            "DTSTART;VALUE=DATE:20260813\r\nLAST-MODIFIED:%s\r\n%s"
            "SUMMARY:%s\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n" %
             (uid, modified, rrule, title))


def task_ics(uid="remote-task", title="Remote task", modified="20260817T100000Z"):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:%s\r\n"
            "LAST-MODIFIED:%s\r\nSUMMARY:%s\r\nEND:VTODO\r\nEND:VCALENDAR\r\n" %
            (uid, modified, title))


def contact_vcf(uid="remote-contact", name="Example", rev="20260817T100000Z"):
    return ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:%s\r\nN:%s;Ada;;;\r\n"
            "FN:Ada %s\r\nTEL;TYPE=HOME:1\r\nTEL;TYPE=CELL:2\r\n"
            "EMAIL;TYPE=HOME:a@example.test\r\nEMAIL;TYPE=WORK:b@example.test\r\n"
            "PHOTO;ENCODING=b;TYPE=JPEG:/9j/2Q==\r\nREV:%s\r\n"
            "END:VCARD\r\n" % (uid, name, name, rev))


def run_sync(monkeypatch, dav, data, calendar=True, contacts=False):
    monkeypatch.setattr(m, "NextcloudDav", lambda _client: dav)
    monkeypatch.setattr(m, "configured_client", lambda _store: object())
    monkeypatch.setattr(m, "nextcloud_speicher", lambda: object())
    probe = SyncProbe()
    calendar_uid = dav.collections("calendar")[0]["uid"] if calendar else ""
    book_uid = dav.collections("addressbook")[0]["uid"] if contacts else ""
    m.Fenster._nextcloud_sync_ausfuehren(
        probe, {"daten": data}, [calendar_uid] if calendar else [], book_uid)
    return probe


def empty_data():
    return {"termine": [], "kontakte": [], "jahrestage": [],
            "geloescht": {"termine": [], "kontakte": []},
            "letzteSyncs": {"kalender": {}, "adressbuecher": {}},
            "syncMetadaten": {"nextcloud": {"kalender": {},
                "adressbuecher": {}, "quarantinedDeletes": {},
                "transaktionen": {}}}}


def test_calendar_without_vtodo_support_leaves_local_tasks_untouched(monkeypatch):
    dav = SyncDav({"calendar": [], "addressbook": []}, supports_vtodo=False)
    data = empty_data()
    data["aufgaben"] = [{"id": "local-task", "uid": "task-1", "titel": "Local"}]
    data["geloescht"]["aufgaben"] = []
    result = run_sync(monkeypatch, dav, data)
    assert len(result.payload["aufgaben"]) == 1
    assert {key: result.payload["aufgaben"][0][key] for key in ("id", "uid", "titel")} == {
        "id": "local-task", "uid": "task-1", "titel": "Local"}
    assert dav.puts == [] and dav.deletes == []


def test_nextcloud_safe_first_calendar_sync_preserves_local_and_tombstone(monkeypatch):
    href = "https://cloud.example/calendar/remote.ics"
    dav = SyncDav({"calendar": [{"href": href, "etag": '"one"',
                                  "data": event_ics()}], "addressbook": []})
    data = empty_data()
    data["termine"] = [{"uid": "local", "datum": "2026-08-17", "zeit": "",
                        "titel": "Local", "geaendert": 1, "sync": True}]
    data["geloescht"]["termine"] = [{"uid": "old", "zeit": 1}]
    probe = run_sync(monkeypatch, dav, data)
    assert probe.snapshots == ["pre-sync"] and not dav.puts and not dav.deletes
    assert {item["uid"] for item in probe.payload["termine"]} == {"local", "remote"}
    assert probe.payload["geloescht"]["termine"][0]["uid"] == "old"
    remote = next(item for item in probe.payload["termine"] if item["uid"] == "remote")
    assert remote["wiederholung"]["ordinal"] == 2


def test_nextcloud_established_delete_and_etag_cursor_commit(monkeypatch):
    href = "https://cloud.example/calendar/remote.ics"
    dav = SyncDav({"calendar": [{"href": href, "etag": '"one"',
                                  "data": event_ics()}], "addressbook": []})
    data = empty_data()
    uid = dav.collections("calendar")[0]["uid"]
    data["letzteSyncs"]["kalender"][uid] = 2_000_000_000_000
    data["syncMetadaten"]["nextcloud"]["kalender"][uid] = {
        "initialisiert": True, "letzterSync": 2_000_000_000_000,
        "etags": {"remote": {"href": href, "etag": '"one"'}}}
    data["geloescht"]["termine"] = [{"uid": "remote", "zeit": 2_000_000_000_001,
                                       "syncKalenderUid": uid}]
    probe = run_sync(monkeypatch, dav, data)
    assert dav.deletes == [(href, '"one"')]
    assert probe.payload["geloescht"]["termine"] == []
    assert isinstance(probe.payload["letzteSyncs"]["kalender"][uid], int)
    assert probe.payload["syncMetadaten"]["nextcloud"]["kalender"][uid]["initialisiert"]


def test_second_consecutive_vtodo_sync_creates_updates_and_deletes(monkeypatch):
    task_one = "https://cloud.example/calendar/task-one.ics"
    task_two = "https://cloud.example/calendar/task-two.ics"
    dav = SyncDav({"calendar": [
        {"href": task_one, "etag": '"one"', "data": task_ics("task-one", "One")},
        {"href": task_two, "etag": '"two"', "data": task_ics("task-two", "Two")},
    ], "addressbook": []})

    first = run_sync(monkeypatch, dav, empty_data()).payload
    uid = dav.collections("calendar")[0]["uid"]
    metadata = first["syncMetadaten"]["nextcloud"]["kalender"][uid]
    assert metadata["initialisiert"] and metadata["aufgabenInitialisiert"]

    first["aufgaben"] = [item for item in first["aufgaben"] if item["uid"] != "task-two"]
    first["aufgaben"][0].update(titel="One locally changed", geaendert=2_000_000_000_001)
    first["aufgaben"].append({"id": "local-three", "uid": "task-three",
                              "titel": "Three", "geaendert": 2_000_000_000_002,
                              "sync": False, "syncKalenderUid": uid})
    first["geloescht"]["aufgaben"] = [{"uid": "task-two",
        "zeit": 2_000_000_000_003, "syncKalenderUid": uid}]
    dav.puts.clear()

    second = run_sync(monkeypatch, dav, first).payload

    assert len(dav.puts) == 2
    assert {call[0] for call in dav.puts} == {
        task_one, "https://cloud.example/calendar/" +
        m._dav_uid_dateiname("task-three", ".ics")}
    assert dav.deletes == [(task_two, '"two"')]
    assert {item["uid"] for item in second["aufgaben"]} == {"task-one", "task-three"}
    metadata = second["syncMetadaten"]["nextcloud"]["kalender"][uid]
    assert metadata["initialisiert"] and metadata["aufgabenInitialisiert"]
    assert set(metadata["aufgabenEtags"]) == {"task-one", "task-three"}


def test_nextcloud_established_remote_delete_removes_only_synced_item(monkeypatch):
    dav = SyncDav({"calendar": [], "addressbook": []})
    data = empty_data()
    uid = dav.collections("calendar")[0]["uid"]
    data["letzteSyncs"]["kalender"][uid] = 100
    data["syncMetadaten"]["nextcloud"]["kalender"][uid] = {
        "initialisiert": True, "letzterSync": 100, "etags": {}}
    data["termine"] = [
        {"uid": "remote-gone", "datum": "2026-08-13", "zeit": "",
         "titel": "Gone", "geaendert": 10, "sync": True,
         "syncKalenderUid": uid},
        {"uid": "local-new", "datum": "2026-08-14", "zeit": "",
         "titel": "Keep", "geaendert": 200, "sync": False,
         "syncKalenderUid": uid},
    ]
    probe = run_sync(monkeypatch, dav, data)
    assert {item["uid"] for item in probe.payload["termine"]} == {"local-new"}
    assert len(dav.puts) == 1 and dav.puts[0][3] is True


def test_nextcloud_etag_conflict_keeps_old_cursor(monkeypatch):
    href = "https://cloud.example/calendar/remote.ics"
    dav = SyncDav({"calendar": [{"href": href, "etag": '"one"',
                                  "data": event_ics(modified="20200101T000000Z")}],
                   "addressbook": []}, fail_put=True)
    data = empty_data()
    uid = dav.collections("calendar")[0]["uid"]
    old = {"initialisiert": True, "letzterSync": 100,
           "etags": {"remote": {"href": href, "etag": '"one"'}}}
    data["letzteSyncs"]["kalender"][uid] = 100
    data["syncMetadaten"]["nextcloud"]["kalender"][uid] = old
    data["termine"] = [{"uid": "remote", "datum": "2026-08-13", "zeit": "",
                        "titel": "New local", "geaendert": 2_000_000_000_000,
                        "sync": True, "syncKalenderUid": uid}]
    probe = run_sync(monkeypatch, dav, data)
    assert dav.puts and probe.payload["letzteSyncs"]["kalender"][uid] == 100
    assert probe.payload["syncMetadaten"]["nextcloud"]["kalender"][uid] == old
    assert probe.payload["kontaktVorschau"] is None


def test_nextcloud_uid_kollision_remote_sieg_uebernimmt_ics_roundtrip(monkeypatch):
    href = "https://cloud.example/calendar/remote.ics"
    remote_text = event_ics(
        uid="gleich", title="Remote gewinnt", modified="20260818T100000Z",
        rrule=("RDATE;VALUE=DATE:20260820\r\n"
               "LOCATION:Serverraum\r\n"
               "ATTACH:web+opaque:anbieter/kennung?x=1\r\n"))
    dav = SyncDav({"calendar": [{"href": href, "etag": '"neu"',
                                  "data": remote_text}], "addressbook": []})
    data = empty_data()
    uid = dav.collections("calendar")[0]["uid"]
    data["letzteSyncs"]["kalender"][uid] = 100
    data["syncMetadaten"]["nextcloud"]["kalender"][uid] = {
        "initialisiert": True, "letzterSync": 100,
        "etags": {"gleich": {"href": href, "etag": '"alt"'}}}
    data["termine"] = [{"uid": "gleich", "datum": "2026-08-13", "zeit": "",
        "titel": "Lokal alt", "geaendert": 10, "sync": True,
        "syncKalenderUid": uid, "icsRoundtrip": ["LOCATION:Lokal"],
        "icsKomplex": False, "icsSerienUid": ""}]

    probe = run_sync(monkeypatch, dav, data)
    termin = probe.payload["termine"][0]
    assert termin["titel"] == "Remote gewinnt"
    assert not termin["icsKomplex"] and not termin["icsSerienUid"]
    assert termin["wiederholung"] == {
        "art": "custom", "bis": "", "daten": ["2026-08-20"]}
    assert "LOCATION:Serverraum" in termin["icsRoundtrip"]
    assert "ATTACH:web+opaque:anbieter/kennung?x=1" in termin["icsRoundtrip"]
    assert not dav.puts


def test_caldav_series_update_puts_complete_resource(monkeypatch):
    resource_text = (FIXTURES / "caldav-series-resource.ics").read_text()
    href = "https://cloud.example/calendar/series.ics"
    dav = SyncDav({"calendar": [{"href": href, "etag": '"series-1"',
                                  "data": resource_text}], "addressbook": []})
    parsed = m.ics_lesen(resource_text)["termine"]
    master = next(item for item in parsed if not any(
        line.startswith("RECURRENCE-ID") for line in item["icsRoundtrip"]))
    override = next(item for item in parsed if item is not master)
    master["titel"] = "Lokal geänderte Serienrunde"
    master["geaendert"] = 2_000_000_000_000
    master["sync"] = True
    override["titel"] = "Lokal verschobene Instanz"
    override["geaendert"] = 2_000_000_000_001
    override["sync"] = True
    data = empty_data()
    uid = dav.collections("calendar")[0]["uid"]
    master["syncKalenderUid"] = uid
    override["syncKalenderUid"] = uid
    data["termine"] = [master, override]
    data["letzteSyncs"]["kalender"][uid] = 100
    data["syncMetadaten"]["nextcloud"]["kalender"][uid] = {
        "initialisiert": True, "letzterSync": 100,
        "etags": {master["uid"]: {"href": href, "etag": '"series-1"'}}}

    run_sync(monkeypatch, dav, data)

    assert len(dav.puts) == 2
    written = dav.puts[-1][1]
    assert written.startswith("BEGIN:VCALENDAR")
    assert written.count("BEGIN:VEVENT") == 2
    assert "SUMMARY:Lokal geänderte Serienrunde" in written
    assert "SUMMARY:Lokal verschobene Instanz" in written
    assert "RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000" in written
    assert "EXDATE;TZID=Europe/Berlin:20261026T100000" in written
    assert "BEGIN:VTIMEZONE" in written and written.count("BEGIN:VALARM") == 2
    assert "X-EXAMPLE-META;X-TOKEN=alpha:opaque-value" in written
    assert written.count("DESCRIPTION:Reminder") == 1


def test_nextcloud_partial_report_aborts_without_result(monkeypatch):
    dav = SyncDav({"calendar": [{"href": "https://cloud.example/calendar/bad.ics",
                                  "etag": '"bad"', "data": "not an ics"}],
                   "addressbook": []})
    with pytest.raises(ValueError):
        run_sync(monkeypatch, dav, empty_data())
    assert not dav.puts and not dav.deletes


def test_nextcloud_mixed_calendar_components_are_ignored_without_losing_targets(monkeypatch):
    resource = event_ics(uid="event-with-journal", title="Termin")
    resource = resource.replace(
        "END:VCALENDAR", "BEGIN:VJOURNAL\r\nUID:journal-1\r\n"
        "SUMMARY:Nicht abbildbar\r\nEND:VJOURNAL\r\nBEGIN:VFREEBUSY\r\n"
        "UID:busy-1\r\nEND:VFREEBUSY\r\nBEGIN:X-CUSTOM\r\nUID:custom-1\r\n"
        "END:X-CUSTOM\r\nEND:VCALENDAR")
    dav = SyncDav({"calendar": [{"href": "https://cloud.example/calendar/mixed.ics",
                                   "etag": '"mixed"', "data": resource}],
                    "addressbook": []})

    probe = run_sync(monkeypatch, dav, empty_data())
    assert [item["uid"] for item in probe.payload["termine"]] == ["event-with-journal"]
    assert not dav.puts and not dav.deletes


def test_event_only_sync_ignores_unreadable_vtodo(monkeypatch):
    resource = event_ics(uid="valid-event", title="Termin").replace(
        "END:VCALENDAR", "BEGIN:VTODO\r\nUID:broken-task\r\n"
        "END:VTODO\r\nEND:VCALENDAR")
    dav = SyncDav({"calendar": [{"href": "https://cloud.example/calendar/mixed.ics",
                                   "etag": '"mixed"', "data": resource}],
                    "addressbook": []}, supports_vtodo=False)

    probe = run_sync(monkeypatch, dav, empty_data())

    assert [item["uid"] for item in probe.payload["termine"]] == ["valid-event"]
    assert probe.payload["aufgaben"] == []


@pytest.mark.parametrize("target", [
    "BEGIN:VEVENT\r\nUID:broken-event\r\nSUMMARY:No date\r\nEND:VEVENT\r\n",
    "BEGIN:VTODO\r\nUID:broken-task\r\nEND:VTODO\r\n",
])
def test_nextcloud_mixed_resource_still_rejects_unreadable_target(monkeypatch, target):
    resource = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VJOURNAL\r\n"
                "UID:journal-1\r\nEND:VJOURNAL\r\n" + target + "END:VCALENDAR\r\n")
    dav = SyncDav({"calendar": [{"href": "https://cloud.example/calendar/bad-mixed.ics",
                                  "etag": '"bad"', "data": resource}],
                   "addressbook": []})
    with pytest.raises(RuntimeError, match=re.escape(
            m._("The Nextcloud calendar was not read completely."))):
        run_sync(monkeypatch, dav, empty_data())
    assert not dav.puts and not dav.deletes


def test_appointment_delete_preserves_shared_calendar_resource(monkeypatch):
    href = "https://cloud.example/calendar/shared.ics"
    resource = event_ics(uid="remove-me", title="Remove me").replace(
        "END:VCALENDAR", "BEGIN:VTODO\r\nUID:keep-task\r\nSUMMARY:Keep task\r\n"
        "END:VTODO\r\nBEGIN:VJOURNAL\r\nUID:keep-journal\r\n"
        "END:VJOURNAL\r\nEND:VCALENDAR")
    dav = SyncDav({"calendar": [{"href": href, "etag": '"shared"', "data": resource}],
                   "addressbook": []})
    data = empty_data()
    uid = dav.collections("calendar")[0]["uid"]
    data["letzteSyncs"]["kalender"][uid] = 100
    data["syncMetadaten"]["nextcloud"]["kalender"][uid] = {
        "initialisiert": True, "letzterSync": 100,
        "etags": {"remove-me": {"href": href, "etag": '"shared"'}}}
    data["geloescht"]["termine"] = [{"uid": "remove-me", "zeit": 2_000_000_000_000,
                                        "syncKalenderUid": uid}]

    run_sync(monkeypatch, dav, data)

    assert dav.deletes == [] and len(dav.puts) == 1
    written = dav.puts[0][1]
    assert "UID:remove-me" not in written
    assert "UID:keep-task" in written and "UID:keep-journal" in written


@pytest.mark.parametrize(("kind", "remove"), [
    ("VEVENT", m.ics_termin_resource_entfernen),
    ("VTODO", m.ics_aufgabe_resource_entfernen),
])
def test_delete_ignores_orphaned_timezone_component(kind, remove):
    resource = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                "BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nEND:VTIMEZONE\r\n"
                f"BEGIN:{kind}\r\nUID:remove-me\r\n"
                + ("DTSTART:20260903T090000Z\r\n" if kind == "VEVENT" else
                   "LAST-MODIFIED:20260903T090000Z\r\nSUMMARY:Remove me\r\n")
                + f"END:{kind}\r\nEND:VCALENDAR\r\n")
    assert remove(resource, "remove-me") is None


def test_nextcloud_reports_complex_series_with_existing_read_only_text(monkeypatch):
    complex_event = event_ics(rrule=(
        "RRULE:FREQ=WEEKLY\r\nEXDATE;VALUE=DATE:20260820\r\n"))
    dav = SyncDav({"calendar": [{"href": "https://cloud.example/calendar/complex.ics",
                                  "etag": '"complex"', "data": complex_event}],
                   "addressbook": []})

    probe = run_sync(monkeypatch, dav, empty_data())

    assert probe.payload["nextcloudKomplexeSerien"] == 1
    termin = probe.payload["termine"][0]
    assert termin["icsKomplex"] and termin["icsReadOnly"]
    assert termin["icsReadOnlyGrund"] == "Nextcloud"
    assert not dav.puts and not dav.deletes
    erwartet = m.ngettext(
        "%(count)s recurring appointment imported only once.",
        "%(count)s recurring appointments imported only once.", 1) % {"count": 1}
    assert dav.collections("calendar")[0]["name"] + ": " + erwartet in \
        probe.payload["bericht"]


def test_nextcloud_contact_first_roundtrip_preserves_photo_and_values(monkeypatch):
    href = "https://cloud.example/addressbook/contact.vcf"
    dav = SyncDav({"calendar": [], "addressbook": [{"href": href,
        "etag": '"card"', "data": contact_vcf()}]})
    probe = run_sync(monkeypatch, dav, empty_data(), calendar=False, contacts=True)
    contact = probe.payload["kontakte"][0]
    assert len(contact["telefone"]) == 2 and len(contact["emailEintraege"]) == 2
    assert contact["foto"] == "data:image/jpeg;base64,/9j/2Q=="
    assert not dav.puts and not dav.deletes


def test_provider_vcard_versions_preserve_uid_unknown_fields_and_parameters():
    parsed = m.vcf_lesen((FIXTURES / "provider-vcards.vcf").read_text())
    assert [item["uid"] for item in parsed["kontakte"]] == [
        "thunderbird-original-uid", "apple-original-uid", "nextcloud-original-uid"]
    written = m.vcf_schreiben(parsed["kontakte"])
    assert "X-MOZILLA-HTML:TRUE" in written
    assert "X-ABRELATEDNAMES;TYPE=friend:Grace Hopper" in written
    assert "KIND:individual" in written and "IMPP;PREF=1:xmpp:nora@example.test" in written
    assert ";PREF=1:ada@example.test" in written
    assert ";X-SERVICE-TYPE=signal:0203 1" in written


def test_nextcloud_changed_etag_beats_stagnant_contact_rev(monkeypatch):
    href = "https://cloud.example/addressbook/contact.vcf"
    dav = SyncDav({"calendar": [], "addressbook": [{"href": href,
        "etag": '"new"', "data": contact_vcf(name="Remote neu", rev="20200101T000000Z")}]})
    data = empty_data()
    uid = dav.collections("addressbook")[0]["uid"]
    data["letzteSyncs"]["adressbuecher"][uid] = 100
    data["syncMetadaten"]["nextcloud"]["adressbuecher"][uid] = {
        "initialisiert": True, "letzterSync": 100,
        "etags": {"remote-contact": {"href": href, "etag": '"old"'}}}
    data["kontakte"] = [{"uid": "remote-contact", "nachname": "Example",
        "vorname": "Lokal", "geaendert": 200, "sync": True,
        "davHref": href, "davEtag": '"old"'}]
    probe = run_sync(monkeypatch, dav, data, calendar=False, contacts=True)
    contact = probe.payload["kontakte"][0]
    assert contact["nachname"] == "Remote neu" and not dav.puts
    assert contact["davEtag"] == '"new"'


def test_nextcloud_contact_etag_conflict_keeps_cursor_and_metadata(monkeypatch):
    href = "https://cloud.example/addressbook/contact.vcf"
    dav = SyncDav({"calendar": [], "addressbook": [{"href": href,
        "etag": '"same"', "data": contact_vcf(rev="20200101T000000Z")}]}, fail_put=True)
    data = empty_data()
    uid = dav.collections("addressbook")[0]["uid"]
    old = {"initialisiert": True, "letzterSync": 100,
           "etags": {"remote-contact": {"href": href, "etag": '"same"'}}}
    data["letzteSyncs"]["adressbuecher"][uid] = 100
    data["syncMetadaten"]["nextcloud"]["adressbuecher"][uid] = old
    data["kontakte"] = [{"uid": "remote-contact", "nachname": "Lokal neu",
        "vorname": "Ada", "geaendert": 2_000_000_000_000, "sync": True,
        "davHref": href, "davEtag": '"same"'}]
    probe = run_sync(monkeypatch, dav, data, calendar=False, contacts=True)
    assert dav.puts and probe.payload["letzteSyncs"]["adressbuecher"][uid] == 100
    assert probe.payload["syncMetadaten"]["nextcloud"]["adressbuecher"][uid] == old
    assert probe.payload["kontaktVorschau"]["fehler"] == 1


def test_legacy_eds_status_additively_reports_nextcloud_sources(monkeypatch):
    calendar = {"uid": "nextcloud-calendar:" + "a" * 64, "name": "Cloud",
                "href": "https://cloud.example/calendar/", "art": "calendar"}
    book = {"uid": "nextcloud-addressbook:" + "b" * 64, "name": "Cards",
            "href": "https://cloud.example/addressbook/", "art": "addressbook"}
    monkeypatch.setattr(m, "eds_laden", lambda: False)
    monkeypatch.setitem(m._EDS, "fehler", "eds unavailable")
    monkeypatch.setattr(m, "nextcloud_status", lambda: {
        "verfuegbar": True, "aktiv": True, "server": "https://cloud.example",
        "url": "https://cloud.example", "benutzer": "user",
        "kennwortVorhanden": True, "zustand": "bereit", "fehler": "",
        "fehlerCode": "none", "kalender": [calendar], "adressbuecher": [book]})

    class Probe:
        def antwort(self, callback, payload):
            self.callback, self.payload = callback, payload

    probe = Probe()
    m.Fenster._eds_status_arbeit(probe)
    assert probe.callback == "App.edsStatus"
    assert probe.payload["kalender"] == [] and probe.payload["adressbuecher"] == []
    assert probe.payload["nextcloud"]["zustand"] == "bereit"
    assert probe.payload["alleKalender"][0]["quelle"] == "nextcloud"
    assert probe.payload["alleAdressbuecher"][0]["uid"] == book["uid"]


def test_mixed_provider_selection_is_partitioned_without_rejection():
    cloud_calendar = "nextcloud-calendar:" + "a" * 64
    cloud_book = "nextcloud-addressbook:" + "b" * 64
    assert m.sync_quellen_aufteilen(["eds-calendar", cloud_calendar], "eds-book") == (
        [cloud_calendar], ["eds-calendar"], "", "eds-book")
    assert m.sync_quellen_aufteilen(["eds-calendar", cloud_calendar], cloud_book) == (
        [cloud_calendar], ["eds-calendar"], cloud_book, "")
    generic_book = "generic-dav-addressbook:" + "c" * 64
    assert m.sync_quellen_aufteilen([], generic_book) == ([], [], generic_book, "")


def test_mixed_provider_resume_journal_is_private_and_removable(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    stand = {"id": "a" * 64, "status": "prepared", "phase": "nextcloud"}
    m.sync_transaktion_schreiben(stand)
    pfad = tmp_path / "sync-transaktion.aes"
    assert stand["id"].encode() not in pfad.read_bytes()
    assert m.sync_transaktion_lesen() == stand
    assert pfad.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / ".sync-transaktion.key").stat().st_mode & 0o777 == 0o600
    m.sync_transaktion_abschliessen()
    assert not pfad.exists()
