"""Synthetic document handoff only; never invokes a real mail/fax recipient."""
from pathlib import Path
import hashlib
import os
import threading
import time
from types import SimpleNamespace

import pytest
from modul_laden import quellmodul_laden


@pytest.fixture
def sender():
    return quellmodul_laden("owned_note_send", Path(__file__).resolve().parents[1] / "bin/magnolie_versand.py")


@pytest.fixture
def document(tmp_path):
    os.chmod(tmp_path, 0o700)
    target = tmp_path / "owned.pdf"
    target.write_bytes(b"%PDF-1.4\n% Owned synthetic fixture only\n%%EOF\n")
    os.chmod(target, 0o600)
    return target


def test_default_disabled_and_discovery_never_execute_an_adapter(sender, document):
    invoked = []
    discovery = sender.capabilities({}, which=lambda name: "/owned/" + name, discover_mail=lambda: {"id": "owned.desktop", "name": "Owned mail"})
    assert discovery["enabled"] is False and discovery["email"]["available"] is True and discovery["fax"]["available"] is False
    with pytest.raises(sender.SendError, match="feature_disabled"):
        sender.handoff({}, "email", "owned@example.test", "Owned notes", document, document.parent, runner=lambda args: invoked.append(args))
    assert not invoked


@pytest.mark.parametrize("kind,target,server,program", [("email", "owned@example.test", "", "xdg-email"),
    ("fax", "+49 (30) 555-0123", "fax.example.test:4559", "sendfax")])
def test_actual_handoff_arguments_preserve_pdf_and_do_not_claim_delivery(sender, document, kind, target, server, program):
    calls = []
    def runner(arguments):
        calls.append(arguments)
        assert Path(arguments[-2] if kind == "email" else arguments[-1]).read_bytes() == document.read_bytes()
        return SimpleNamespace(returncode=0)
    result = sender.handoff({"enabled": True, "faxServer": server}, kind, target, "Owned selected notes", document, document.parent,
        runner=runner, which=lambda name: "/owned/" + name, discover_mail=lambda: {"id": "owned.desktop", "name": "Owned mail"})
    assert len(calls) == 1 and calls[0][0] == "/owned/" + program
    assert result["stage"] == "handed_off" and result["accepted"] is True and result["delivery_confirmed"] is False
    assert result["document"] == {"bytes": document.stat().st_size, "sha256": hashlib.sha256(document.read_bytes()).hexdigest()}
    if kind == "fax":
        assert calls[0] == ["/owned/sendfax", "-h", server, "-n", "-d", "+49305550123", str(document)]
    else:
        assert calls[0] == ["/owned/xdg-email", "--utf8", "--subject", "Owned selected notes", "--attach", str(document), target]


def test_unavailable_unconfigured_invalid_and_failed_adapters_are_explicit(sender, document):
    config = {"enabled": True}
    with pytest.raises(sender.SendError, match="native_unavailable"):
        sender.command(config, "fax", "+49305550123", "Owned", document, which=lambda _name: "/owned/sendfax")
    with pytest.raises(sender.SendError, match="native_unavailable"):
        sender.command(config, "email", "owned@example.test", "Owned", document, which=lambda _name: "/owned/xdg-email", discover_mail=lambda: None)
    for kind, value in (("email", "owned@example.test\r\nBcc: foreign@example.test"), ("fax", "--other-option"), ("fax", "+4930;owned")):
        with pytest.raises(sender.SendError, match="invalid_recipient"):
            sender.recipient(kind, value)
    for value in ("--other-option", "user:password@host", "host;owned", "host:99999"):
        with pytest.raises(sender.SendError, match="invalid_fax_server"):
            sender.fax_server(value)
    with pytest.raises(sender.SendError) as error:
        sender.handoff(config, "email", "owned@example.test", "Owned", document, document.parent,
            runner=lambda _args: SimpleNamespace(returncode=1), which=lambda _name: "/owned/xdg-email", discover_mail=lambda: {"name": "Owned"})
    assert error.value.code == "native_operation_failed" and error.value.dispatched is True


def test_handoff_requires_private_owned_real_pdf_not_arbitrary_file_or_symlink(sender, document):
    link = document.parent / "link.pdf"
    link.symlink_to(document)
    with pytest.raises(sender.SendError, match="invalid_document"):
        sender.pdf_receipt(link, document.parent)
    document.write_bytes(b"not a PDF")
    with pytest.raises(sender.SendError, match="invalid_document"):
        sender.pdf_receipt(document, document.parent)


def wait_phase(service, token, phases):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = service.status(token)
        if value["phase"] in phases:
            return value
        time.sleep(0.005)
    raise AssertionError("Owned send fixture did not complete")


def test_async_cancel_before_pdf_completion_prevents_adapter_and_cleans_owned_document(sender, tmp_path):
    callbacks, calls = [], []
    config = {"enabled": True}
    service = sender.SendJobs(tmp_path / "spool", lambda: config,
        lambda html, path, done: callbacks.append((path, done)), which=lambda name: "/owned/" + name,
        discover_mail=lambda: {"id": "owned.desktop", "name": "Owned"}, runner=lambda args: calls.append(args))
    begun = service.begin("<p>Owned selected note</p>", "email", "owned@example.test", "Owned", service.read()["revision"])
    assert begun["phase"] == "preparing" and begun["handed_off"] is False
    cancelled = service.cancel(begun["operation_id"])
    assert cancelled["cancel_accepted"] is True and cancelled["phase"] == "cancelled"
    pdf, callback = callbacks.pop()
    Path(pdf).write_bytes(b"%PDF-1.4\nOwned selected note\n%%EOF\n")
    callback({"ok": True})
    assert not calls and not Path(pdf).parent.exists()


def test_disabling_or_changing_adapter_context_during_pdf_preparation_blocks_handoff(sender, tmp_path):
    callbacks, calls = [], []
    config = {"enabled": True}
    service = sender.SendJobs(tmp_path / "spool", lambda: config,
        lambda html, path, done: callbacks.append((path, done)), which=lambda name: "/owned/" + name,
        discover_mail=lambda: {"id": "owned.desktop", "name": "Owned"}, runner=lambda args: calls.append(args))
    begun = service.begin("<p>Owned</p>", "email", "owned@example.test", "Owned", service.read()["revision"])
    config["enabled"] = False
    pdf, callback = callbacks.pop(); Path(pdf).write_bytes(b"%PDF-1.4\nOwned\n%%EOF\n"); callback({"ok": True})
    finished = wait_phase(service, begun["operation_id"], {"failed"})
    assert finished["error_code"] == "conflict" and finished["native_outcome_unknown"] is False and not calls


def test_external_pending_cannot_be_recalled_and_success_is_only_document_handoff(sender, tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    config = {"enabled": True}
    def renderer(html, path, done):
        assert html == "<p>Only the selected owned note</p>"
        Path(path).write_bytes(b"%PDF-1.4\nOnly the selected owned note\n%%EOF\n")
        done({"ok": True})
    def runner(arguments):
        calls.append(arguments); entered.set()
        assert release.wait(2)
        return SimpleNamespace(returncode=0)
    service = sender.SendJobs(tmp_path / "spool", lambda: config, renderer, which=lambda name: "/owned/" + name,
        discover_mail=lambda: {"id": "owned.desktop", "name": "Owned"}, runner=runner)
    try:
        begun = service.begin("<p>Only the selected owned note</p>", "email", "owned@example.test", "Owned", service.read()["revision"])
        assert entered.wait(2)
        pending = service.status(begun["operation_id"])
        assert pending["phase"] == "external_pending" and pending["native_outcome_unknown"] is True and pending["can_cancel"] is False
        assert service.cancel(begun["operation_id"])["cancel_accepted"] is False
    finally:
        release.set()
    finished = wait_phase(service, begun["operation_id"], {"handed_off", "failed"})
    assert len(calls) == 1 and finished["handed_off"] is True and finished["delivery_confirmed"] is False
    assert finished["document"]["bytes"] > 0


def test_cancelled_but_still_rendering_operations_keep_the_native_resource_limit(sender, tmp_path):
    callbacks, calls = [], []
    service = sender.SendJobs(tmp_path / "spool", lambda: {"enabled": True},
        lambda html, path, done: callbacks.append((path, done)), which=lambda name: "/owned/" + name,
        discover_mail=lambda: {"id": "owned.desktop", "name": "Owned"}, runner=lambda args: calls.append(args))
    try:
        revision = service.read()["revision"]
        for _index in range(4):
            job = service.begin("<p>Owned</p>", "email", "owned@example.test", "Owned", revision)
            assert service.cancel(job["operation_id"])["cancel_accepted"] is True
        with pytest.raises(sender.SendError, match="native_busy"):
            service.begin("<p>Owned</p>", "email", "owned@example.test", "Owned", revision)
    finally:
        for path, callback in callbacks:
            Path(path).write_bytes(b"%PDF-1.4\nOwned\n%%EOF\n"); callback({"ok": True})
    assert not calls and not list((tmp_path / "spool").iterdir())


def test_native_context_is_process_bound_and_exact_operation_replay_never_resends(sender, tmp_path):
    callbacks, calls = [], []
    arguments = {"which": lambda name: "/owned/" + name, "discover_mail": lambda: {"id": "owned.desktop", "name": "Owned"},
        "runner": lambda args: calls.append(args) or SimpleNamespace(returncode=0)}
    service = sender.SendJobs(tmp_path / "spool", lambda: {"enabled": True}, lambda html, path, done: callbacks.append((path, done)), **arguments)
    other = sender.SendJobs(tmp_path / "other", lambda: {"enabled": True}, lambda *_args: None, **arguments)
    revision = service.read()["revision"]
    assert revision != other.read()["revision"]
    operation = "c" * 48
    first = service.begin("<p>Owned</p>", "email", "owned@example.test", "Owned", revision, operation)
    repeated = service.begin("<p>Owned</p>", "email", "owned@example.test", "Owned", revision, operation)
    assert first["operation_id"] == repeated["operation_id"] and len(callbacks) == 1
    with pytest.raises(sender.SendError, match="conflict"):
        service.begin("<p>Changed Owned</p>", "email", "owned@example.test", "Owned", revision, operation)
    path, done = callbacks.pop(); Path(path).write_bytes(b"%PDF-1.4\nOwned\n%%EOF\n"); done({"ok": True})
    wait_phase(service, operation, {"handed_off"})
    service.begin("<p>Owned</p>", "email", "owned@example.test", "Owned", revision, operation)
    assert len(calls) == 1


def test_expired_private_pdf_cleanup_skips_unowned_paths_and_symlinks(sender, tmp_path):
    clock = [time.time()]
    def renderer(html, path, done):
        Path(path).write_bytes(b"%PDF-1.4\nOwned\n%%EOF\n"); done({"ok": True})
    service = sender.SendJobs(tmp_path / "spool", lambda: {"enabled": True}, renderer,
        which=lambda name: "/owned/" + name, discover_mail=lambda: {"id": "owned.desktop", "name": "Owned"},
        runner=lambda _args: SimpleNamespace(returncode=0), clock=lambda: clock[0])
    job = service.begin("<p>Owned</p>", "email", "owned@example.test", "Owned", service.read()["revision"])
    wait_phase(service, job["operation_id"], {"handed_off"})
    deadline = time.monotonic() + 3
    while not service.jobs[job["operation_id"]]["finished"]:
        assert time.monotonic() < deadline
        time.sleep(0.005)
    unowned = service.root / "unrelated-user-artifact"; unowned.mkdir(); (unowned / "keep").write_text("owned test data")
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "keep").write_text("owned test data")
    (service.root / ("b" * 48)).symlink_to(outside, target_is_directory=True)
    clock[0] += 86401
    service.read()
    assert not (service.root / job["operation_id"]).exists()
    assert (unowned / "keep").read_text() == "owned test data" and (outside / "keep").read_text() == "owned test data"


def test_existing_fax_number_types_survive_native_contact_import_export(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "gi", None)
    product = quellmodul_laden("owned_note_send_contact_codec", Path(__file__).resolve().parents[1] / "bin/magnolie-organizer")
    raw = "\r\n".join(["BEGIN:VCARD", "VERSION:3.0", "N:Recipient;Owned;;;", "FN:Owned Recipient",
        "TEL;TYPE=HOMEFAX:+49305550125", "TEL;TYPE=WORKFAX:+49305550126", "TEL;TYPE=CELL:+49305550124",
        "X-OWNED:preserved", "END:VCARD", ""])
    contact = product.vcf_lesen(raw)["kontakte"][0]
    exported = product.vcf_schreiben([contact])
    restored = product.vcf_lesen(exported)["kontakte"][0]
    phones = {item["wert"]: item["typen"] for item in product._telefon_liste(restored)}
    assert "FAX" in phones["+49305550125"] and "FAX" in phones["+49305550126"]
    assert "FAX" not in phones["+49305550124"] and "X-OWNED:preserved" in exported


def test_sandbox_mail_capability_does_not_offer_an_inaccessible_host_attachment(sender, document, monkeypatch):
    monkeypatch.setattr(sender, "mail_platform_supported", lambda: False)
    state = sender.capabilities({"enabled": True}, which=lambda name: "/owned/" + name,
        discover_mail=lambda: {"id": "owned.desktop", "name": "Owned"})
    assert state["email"]["supported"] is False and state["email"]["available"] is False
    with pytest.raises(sender.SendError, match="unsupported_adapter"):
        sender.command({"enabled": True}, "email", "owned@example.test", "Owned", document,
            which=lambda name: "/owned/" + name, discover_mail=lambda: {"id": "owned.desktop", "name": "Owned"})
