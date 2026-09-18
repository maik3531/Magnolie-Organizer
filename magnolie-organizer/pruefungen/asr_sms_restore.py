#!/usr/bin/env python3
"""Source-bound ASR-01 native state checks; synthetic data, offline tiny .NET host."""
import ast
import copy
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
W = ROOT / "magnolie-organizer-windows"
BEFORE = "--before" in sys.argv


def linux_restore():
    source = ROOT / "magnolie-organizer/bin/magnolie-organizer"
    tree = ast.parse(source.read_text())
    names = {"journal_restore_daten", "_journal_anhaenge_bewahren", "_journal_liste_ergaenzen"}
    scope = dict(json=json, uuid=uuid, jetzt_ms=lambda: 1000, _=lambda s: s)
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names],
                            type_ignores=[]), str(source), "exec"), scope)
    return scope["journal_restore_daten"]


def fixture(enabled):
    return {"einstellungen": {"adressen": {"smsSchedulingEnabled": enabled, "ownPreference": "retained"}},
            "smsPlanung": [{"id": "unknown-on-another-profile", "status": "planned", "zeit": 1,
                            "nummer": "+447700900123", "land": "GB", "text": "?????? - ??",
                            "originalText": "Привет — 你好", "clientRef": "", "fehler": ""}],
            "notizen": [], "kontakte": [], "termine": []}


def run():
    restore = linux_restore()
    scenarios = []
    archive, live = fixture(True), fixture(False)
    result = restore(archive, live)
    if BEFORE:
        assert result["einstellungen"]["adressen"]["smsSchedulingEnabled"] is True
        assert result["smsPlanung"][0]["status"] == "planned"
        print("BEFORE Linux actual restore: local false + archive true => true, unknown overdue plan remains planned")
    else:
        for enabled in (False, True, "true", None):
            live = fixture(enabled)
            for areas in (["all"], ["contacts"], ["calendar"], ["notes"], ["contacts", "notes"]):
                for mode in ("replace", "additive"):
                    old_archive, old_live = copy.deepcopy(archive), copy.deepcopy(live)
                    result = restore(archive, live, areas, mode)
                    assert archive == old_archive and live == old_live, "source archive/live object mutated"
                    expected = enabled is True if areas == ["all"] else enabled
                    assert result["einstellungen"]["adressen"]["smsSchedulingEnabled"] == expected
                    expected_plan = dict(archive["smsPlanung"][0], status="paused") if areas == ["all"] else live["smsPlanung"][0]
                    assert result["smsPlanung"] == [expected_plan]
                    if isinstance(enabled, bool) and mode == "replace":
                        scenarios.append(dict(platform="linux", enabled=enabled, partial=areas != ["all"], data=result))
            result = restore(archive)
            assert result["einstellungen"]["adressen"]["smsSchedulingEnabled"] is False
        for status in ("paused", "submitting", "queued", "submitted", "uncertain", "sent", "failed"):
            archive["smsPlanung"][0]["status"] = status
            assert restore(archive, live)["smsPlanung"][0]["status"] == ("uncertain" if status == "submitting" else status)
        print("PASS Linux actual restore: all/partial selection, live permission matrix, fresh profile, full plan content and terminal statuses")

    # Compile only actual RestoreSyncState and RestoreSelection; no Windows SDK,
    # dispatcher/runtime or transport stubs masquerading as native platform tests.
    with tempfile.TemporaryDirectory(prefix="asr-sms-native-", dir="/tmp/opencode") as tmp:
        work = Path(tmp)
        source = (W / "RecoveryJournal.cs").read_text()
        (work / "State.cs").write_text("using System.Text.Json.Nodes;\nnamespace MagnolieOrganizer.Windows;\n" +
            source[source.index("internal static class RestoreSyncState"):])
        (work / "Selection.cs").write_text((W / "RestoreSelection.cs").read_text())
        if not BEFORE:
            dispatcher = (W / "BridgeDispatcher.cs").read_text()
            snapshot_method = dispatcher[dispatcher.index("    private async Task RestoreSnapshotAsync("):
                                         dispatcher.index("    private void PrepareRestoredData(")]
            assert 'PrepareRestoredData(restored, restoreSmsPlans: areas.Contains("all"))' in snapshot_method, "Windows selection flag not integrated"
            wrapper = dispatcher[dispatcher.index("    private void PrepareRestoredData("):
                                 dispatcher.index("    private async Task<string> CompleteRestoreRuntimeAsync(")]
            (work / "Wrapper.cs").write_text('''using System.Text.Json.Nodes;
namespace MagnolieOrganizer.Windows;
internal class RestoreWrapper(string live) {
    private readonly string currentPlainText = live;
    private readonly bool currentPlainTextAvailable = true;
    private static string T(string s) => s;
    internal void Apply(JsonObject data, bool sms = true) => PrepareRestoredData(data, restoreSmsPlans: sms);
''' + wrapper + "}\n")
        for name in ("SmsSubmissionJournal.cs", "AtomicStore.cs"):
            (work / name).write_text((W / name).read_text())
        sms_source = (W / "KdeConnectSms.cs").read_text()
        method = sms_source[sms_source.index("    internal async Task<KdeConnectSendResult> SendWithResultAsync("):
                            sms_source.index("    internal Task<KdeConnectPairing> StartPairingAsync()")]
        (work / "Capture.cs").write_text('''namespace MagnolieOrganizer.Windows;
internal record KdeConnectSendResult(bool Ok, string State, string Id, string? Error = null);
internal class CapturedBackend {
    internal readonly List<string> Texts = new();
    internal Task<KdeConnectSendResult> SendSmsWithResultAsync(string number, string text, string country,
        string device, string fingerprint, CancellationToken token) {
        Texts.Add(text); return Task.FromResult(new KdeConnectSendResult(true, "submitted", ""));
    }
}
internal class SmsCaptureHost(string path, CapturedBackend capture) {
    private readonly SmsSubmissionJournal submissions = new(path);
    private readonly CapturedBackend native = capture;
''' + method + "}\n")
        (work / "Program.cs").write_text('''using System.Text.Json.Nodes;
namespace MagnolieOrganizer.Windows;
internal static class NativeLocalization { internal static string Gettext(string s) => s; }
internal static class Program {
    static void Check(bool v, string message) { if (!v) throw new Exception(message); }
    static JsonObject Fixture(bool enabled) => new() {
        ["einstellungen"] = new JsonObject { ["adressen"] = new JsonObject { ["smsSchedulingEnabled"] = enabled } },
        ["smsPlanung"] = new JsonArray { new JsonObject { ["id"] = "unknown-on-another-profile", ["status"] = "planned",
            ["nummer"] = "+447700900123", ["land"] = "GB", ["text"] = "?????? - ??", ["originalText"] = "Привет — 你好", ["zeit"] = 1 } } };
    static void Main(string[] args) {
        if (args.Length > 0) {
            var backend = new CapturedBackend(); var path = args[1];
            foreach (var command in JsonNode.Parse(File.ReadAllText(args[0]))!.AsArray().OfType<JsonObject>()) {
                string V(string k) => command[k]?.ToString() ?? "";
                var device = V("device_id"); if (device.Length == 0) device = V("deviceId");
                var fingerprint = V("device_fingerprint"); if (fingerprint.Length == 0) fingerprint = new string('1', 64);
                var count = backend.Texts.Count;
                for (var i = 0; i < 2; i++) {
                    var sent = new SmsCaptureHost(path, backend).SendWithResultAsync(V("nummer"), V("text"), V("land"), V("clientRef"), device, fingerprint).GetAwaiter().GetResult();
                    Check(sent.Ok && sent.State == "submitted", "native submitted");
                }
                Check(backend.Texts.Count == count + 1 && backend.Texts.Last() == V("text"), "exact text once, journal protects replay");
                try {
                    new SmsCaptureHost(path, backend).SendWithResultAsync(V("nummer"), V("text") + "?", V("land"), V("clientRef"), device, fingerprint).GetAwaiter().GetResult();
                    throw new Exception("changed payload accepted");
                } catch (InvalidDataException) { }
            }
            Console.WriteLine("PASS Windows actual SendWithResultAsync + journal: " + backend.Texts.Count + " exact approved texts, restart/replay and mismatches captured");
            return;
        }
        var before = /* BEFORE */;
        foreach (var enabled in new[] { false, true }) {
            var live = Fixture(enabled); var archive = Fixture(true); var raw = archive.ToJsonString();
            var result = archive.DeepClone().AsObject();
            /* FULL PREPARE */
            Check(result["einstellungen"]!["adressen"]!["smsSchedulingEnabled"]!.GetValue<bool>() == (before || enabled), "live permission");
            Check(result["smsPlanung"]![0]!["status"]!.ToString() == (before ? "planned" : "paused"), "pending pause");
            Check(archive.ToJsonString() == raw, "archive retained");
            if (!before) Console.WriteLine("FIXTURE " + new JsonObject { ["platform"] = "windows", ["enabled"] = enabled, ["partial"] = false, ["data"] = result.DeepClone() }.ToJsonString());
            result["smsPlanung"]![0]!["status"] = "planned";
            Check(JsonNode.DeepEquals(result["smsPlanung"], archive["smsPlanung"]), "exact content retained");
            PARTIAL_CHECK
        }
        Console.WriteLine((before ? "BEFORE" : "PASS") + " Windows actual RestoreSyncState: permission and pending status");
    }
}'''.replace("/* BEFORE */", "true" if BEFORE else "false")
            .replace("/* FULL PREPARE */", "RestoreSyncState.Prepare(result, live: live);" if BEFORE else "new RestoreWrapper(live.ToJsonString()).Apply(result);")
            .replace("PARTIAL_CHECK", "" if BEFORE else '''
            foreach (var area in new[] { "contacts", "calendar", "notes" }) foreach (var mode in new[] { "replace", "additive" }) {
                var selected = RestoreSelection.Select(archive, live, new[] { area }, mode);
                new RestoreWrapper(live.ToJsonString()).Apply(selected, false);
                Check(JsonNode.DeepEquals(selected["smsPlanung"], live["smsPlanung"]), "partial live plans");
                Check(selected["einstellungen"]!["adressen"]!["smsSchedulingEnabled"]!.GetValue<bool>() == enabled, "partial live preference");
                if (mode == "replace") Console.WriteLine("FIXTURE " + new JsonObject { ["platform"] = "windows", ["enabled"] = enabled, ["partial"] = true, ["data"] = selected.DeepClone() }.ToJsonString());
            }
            var fresh = archive.DeepClone().AsObject(); RestoreSyncState.Prepare(fresh);
            Check(!fresh["einstellungen"]!["adressen"]!["smsSchedulingEnabled"]!.GetValue<bool>(), "fresh profile off");
            foreach (var status in new[] { "paused", "submitting", "queued", "submitted", "uncertain", "sent", "failed" }) {
                var terminal = archive.DeepClone().AsObject(); terminal["smsPlanung"]![0]!["status"] = status;
                RestoreSyncState.Prepare(terminal, live: live);
                Check(terminal["smsPlanung"]![0]!["status"]!.ToString() == (status == "submitting" ? "uncertain" : status), "terminal status");
            }
'''))
        (work / "Host.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
        (work / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
        dotnet = os.environ.get("MAGNOLIE_DOTNET", "/tmp/opencode/fivefixnative/dotnet/dotnet")
        env = dict(os.environ, HOME=tmp, DOTNET_CLI_HOME=tmp, DOTNET_PROCESSOR_COUNT="2", DOTNET_CLI_TELEMETRY_OPTOUT="1",
                   DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_NOLOGO="1", NUGET_PACKAGES=tmp + "/packages")
        subprocess.run([dotnet, "build", str(work / "Host.csproj"), "--configfile", str(work / "NuGet.Config"), "-m:1",
                        "-p:UseSharedCompilation=false", "-nodeReuse:false", "-v:q"], env=env, check=True, timeout=90)
        host = str(work / "bin/Debug/net8.0/Host.dll")
        output = subprocess.run([dotnet, host], env=env, check=True, timeout=30, capture_output=True, text=True).stdout
        for line in output.splitlines():
            if line.startswith("FIXTURE "): scenarios.append(json.loads(line[8:]))
            else: print(line)
        if not BEFORE:
            fixtures, captured = work / "restores.json", work / "captured.json"
            fixtures.write_text(json.dumps(scenarios))
            subprocess.run(["/home/maik3531/.bun/bin/bun", str(W / "tests/asr-sms-regressions.js"),
                            "--native-restores", str(fixtures), "--capture-out", str(captured)], env=env, check=True, timeout=90)
            subprocess.run([dotnet, host, str(captured), str(work / "windows-journal.json")], env=env, check=True, timeout=30)
            linux_captured_sms(work, json.loads(captured.read_text()))


def linux_captured_sms(work, commands):
    sys.path.insert(0, str(ROOT / "magnolie-organizer/bin"))
    import magnolie_kdeconnect as kde
    calls = []
    def capture(number, text, device_id=None):
        calls.append((number, text)); return {"ok": True, "state": "queued"}
    source = ROOT / "magnolie-organizer/bin/magnolie-organizer"
    scope = dict(os=os, re=re, DEVICE_ID=kde.DEVICE_ID, SmsSubmissionJournal=kde.SmsSubmissionJournal,
                 daten_verzeichnis=lambda: str(work), _=lambda s: s,
                 _kdeconnect_backend=lambda: SimpleNamespace(send_sms=capture))
    names = {"_telefon_schluessel", "kdeconnect_sms_senden"}
    exec(compile(ast.Module(body=[n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names],
                           type_ignores=[]), str(source), "exec"), scope)
    send = scope["kdeconnect_sms_senden"]
    for cmd in commands:
        count = len(calls)
        for _ in range(2):
            result = send(cmd["nummer"], cmd["text"], cmd["land"], client_ref=cmd["clientRef"],
                          device_id=cmd.get("deviceId") or cmd.get("device_id"))
            assert result["state"] == "submitted"
        assert len(calls) == count + 1 and calls[-1] == (cmd["nummer"], cmd["text"])
        try:
            send(cmd["nummer"], cmd["text"] + "?", cmd["land"], client_ref=cmd["clientRef"],
                 device_id=cmd.get("deviceId") or cmd.get("device_id"))
            raise AssertionError("changed payload accepted")
        except ValueError: pass
    print("PASS Linux actual kdeconnect_sms_senden + journal:", len(calls), "exact approved texts, restart/replay and mismatches captured")


if __name__ == "__main__":
    run()
