"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const bridgeFiles = fs.readdirSync(root).filter(file => /^BridgeDispatcher(?:\.[A-Za-z]+)?\.cs$/.test(file)).sort();
const bridge = bridgeFiles.map(file => {
  const source = read(file);
  assert.match(source, /partial class BridgeDispatcher\b/, `Unexpected dispatcher source: ${file}`);
  return source;
}).join("\n");
assert.ok(bridgeFiles.includes("BridgeDispatcher.Background.cs") && bridgeFiles.includes("BridgeDispatcher.Sync.cs"));
const mainForm = read("MainForm.cs");
const application = read("app", "web", "anwendung.js");
const html = read("app", "web", "index.html");

assert.match(mainForm, /__MAGNOLIE_BRUECKE__/,
  "native host must inject the randomized bridge name");
assert.match(application, /window\.__MAGNOLIE_BRUECKE__/);
assert.match(application, /messageHandlers\[this\.name\]/);
assert.doesNotMatch(application, /window\.chrome\.webview/);

for (const command of [
  "speichern", "beenden_abgebrochen", "beenden_bereit", "tray_einstellungen",
  "gesamtarchiv_waehlen", "gesamtarchiv_pruefen", "gesamtarchiv_importieren",
  "gesamtarchiv_exportieren", "notiz_anhang_datei", "graph_anmelden",
  "graph_abmelden", "sync", "sozial"
]) assert.match(bridge, new RegExp(`case "${command}"`),
  `Windows bridge command missing: ${command}`);

assert.match(application, /notiz_anhang_datei/,
  "note attachment open/save must still use the Windows host");
assert.match(application, /graph_anmelden/);
assert.match(application, /sync-windows-quelle/);
assert.match(application, /teamsVerfuegbar/);
assert.match(application, /teams-call/);
assert.match(application, /gesamtarchiv_exportieren/);
assert.match(application, /contributor_pruefen/);
assert.match(application, /trayEinstellungen/);

for (const command of [
  "telefon_stand", "telefon_ein", "telefon_pairing_oeffnen",
  "telefon_pairing_bestaetigen", "telefon_freigabe", "telefon_status_anfordern",
  "telefon_waehlen", "telefon_annehmen", "telefon_auflegen", "telefon_bluetooth_schalten",
  "telefon_anruf_anzeigen", "telefon_anruf_lautstaerke_wiederherstellen",
  "telefon_sms_benachrichtigen", "telefon_meldung_anzeigen",
  "kde_pairing_start", "kde_pairing_confirm", "kde_pairing_complete",
  "kde_reconnect", "kde_sms_senden", "personal_sync_einstellungen",
  "personal_sync_senden", "personal_sync_lauf_senden",
  "personal_sync_attachment_index", "telefon_personal_sync_commit"
]) assert.ok(application.includes(`cmd: "${command}"`),
  `expected native command contract missing from web UI: ${command}`);

const communicationCommands = new Set(Array.from(application.matchAll(
  /cmd:\s*"((?:telefon|kde|personal_sync)_[a-z0-9_]+)"/g), (match) => match[1]));
for (const command of communicationCommands) assert.match(bridge,
  new RegExp(`case "${command}"`),
  `Windows bridge does not dispatch current web command: ${command}`);
assert.doesNotMatch(bridge, /case "telefon_sms_senden"/,
  "obsolete Magnolie SMS transport remains in the Windows dispatcher");
assert.match(bridge, /SendAsync\("App\.kdeSmsStatus"/,
  "current KDE submission status is not emitted by the dispatcher");
assert.doesNotMatch(bridge, /SendAsync\("App\.telefonSmsStatus"/,
  "obsolete Magnolie outbound SMS status must not be required as a live native callback");
const lazyKde = read("BridgeDispatcher.Background.cs").match(/private KdeConnectSms kdeConnectSms\s*\{[\s\S]*?(?=\n    private Task QueueBackground)/)?.[0];
assert.ok(lazyKde, "KDE service initializer was not inspected");
assert.match(lazyKde, /lock \(serviceGate\)[\s\S]*ObjectDisposedException.ThrowIf\(disposed, this\)/);
assert.match(lazyKde, /if \(kdeInstance is not null\) return kdeInstance/);
for (const [callback, handler] of [["StatusChanged", "HandleKdeStatusChanged"],
  ["SmsReceived", "HandleKdeSmsReceived"], ["PairingChanged", "HandleKdePairingChanged"]]) {
  const registration = `created.${callback} += ${handler}`;
  assert.strictEqual(lazyKde.split(registration).length - 1, 1, `Register exactly once: ${callback}`);
  assert.ok(lazyKde.indexOf(registration) < lazyKde.indexOf("kdeInstance = created"), "Do not publish a partly subscribed service");
}
assert.match(lazyKde, /catch \{ created.Dispose\(\); throw; \}/, "Failed optional initialization must dispose its candidate");
assert.match(bridge, /QueueBackground\(ResumeOptionalServicesAsync\)/);
assert.match(bridge, /private async Task ResumeOptionalServicesAsync\(\)[\s\S]*try \{ _ = kdeConnectSms; \}[\s\S]*catch/);
assert.match(bridge, /internal async Task ShutdownAsync\(\)[\s\S]*kdeInstance\?\.Dispose\(\)/,
  "Shutdown must dispose only an initialized KDE instance, not create an optional service");
assert.match(read("KdeConnectSms.cs"), /public void Dispose\(\) \{ if \(backend.IsValueCreated\) backend.Value.Dispose\(\); \}/);
// Execute the actual initializer with an in-memory event source, never a phone service.
const dotnet = [process.env.DOTNET_HOST_PATH, "/tmp/opencode/dotnet-8.0.408/dotnet", "dotnet"]
  .filter(Boolean).find(command => spawnSync(command, ["--version"], { encoding: "utf8" }).status === 0);
assert.ok(dotnet, ".NET 8 is required for the optional-service lifecycle fixture");
const lifecycle = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-service-lifecycle-"));
try {
  const home = path.join(lifecycle, "home"); fs.mkdirSync(home);
  fs.writeFileSync(path.join(lifecycle, "Lifecycle.csproj"), `<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
    <OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable><NuGetAudit>false</NuGetAudit><RestoreSources></RestoreSources>
    </PropertyGroup></Project>`);
  fs.writeFileSync(path.join(lifecycle, "Program.cs"), `
internal sealed class Probe {
  private readonly object serviceGate = new(), paths = new();
  private bool disposed;
  private KdeConnectSms? kdeInstance;
  internal int Calls;
  private void HandleKdeStatusChanged() => Calls++;
  private void HandleKdeSmsReceived() => Calls++;
  private void HandleKdePairingChanged() => Calls++;
  ${lazyKde}
  internal KdeConnectSms Get() => kdeConnectSms;
  internal void Stop() { disposed = true; kdeInstance?.Dispose(); }
}
internal sealed class KdeConnectSms : IDisposable {
  internal static int Created, Disposed;
  internal static bool FailSubscription;
  private Action? status, sms, pairing;
  internal KdeConnectSms(object paths) { Interlocked.Increment(ref Created); }
  internal event Action StatusChanged { add => status += value; remove => status -= value; }
  internal event Action SmsReceived {
    add { if (FailSubscription) { FailSubscription = false; throw new InvalidOperationException("subscription fault"); } sms += value; }
    remove => sms -= value;
  }
  internal event Action PairingChanged { add => pairing += value; remove => pairing -= value; }
  internal void Emit() { status?.Invoke(); sms?.Invoke(); pairing?.Invoke(); }
  public void Dispose() { Interlocked.Increment(ref Disposed); status = sms = pairing = null; }
}
internal static class Program {
  private static void Check(bool condition) { if (!condition) throw new Exception("Lifecycle assertion failed"); }
  static void Main() {
    var probe = new Probe(); var values = new KdeConnectSms[64];
    Parallel.For(0, values.Length, index => values[index] = probe.Get());
    Check(KdeConnectSms.Created == 1 && values.All(value => ReferenceEquals(value, values[0])));
    values[0].Emit(); Check(probe.Calls == 3);
    probe.Stop(); Check(KdeConnectSms.Disposed == 1);
    try { probe.Get(); throw new Exception("Disposed service was recreated"); } catch (ObjectDisposedException) { }
    var retry = new Probe(); KdeConnectSms.FailSubscription = true;
    try { retry.Get(); throw new Exception("Subscription fault was ignored"); } catch (InvalidOperationException) { }
    Check(KdeConnectSms.Created == 2 && KdeConnectSms.Disposed == 2);
    retry.Get().Emit(); Check(KdeConnectSms.Created == 3 && retry.Calls == 3);
    retry.Stop(); Check(KdeConnectSms.Disposed == 3);
    Console.WriteLine("OPTIONAL SERVICE LIFECYCLE PASSED");
  }
}`);
  const result = spawnSync(dotnet, ["run", "--project", path.join(lifecycle, "Lifecycle.csproj"), "--verbosity", "quiet"], {
    encoding: "utf8", timeout: 120000,
    env: { ...process.env, HOME: home, DOTNET_CLI_HOME: home, DOTNET_CLI_TELEMETRY_OPTOUT: "1",
      DOTNET_GENERATE_ASPNET_CERTIFICATE: "false", DOTNET_NOLOGO: "1", NUGET_PACKAGES: path.join(lifecycle, "packages") }
  });
  assert.strictEqual(result.status, 0, (result.error || "") + result.stdout + result.stderr);
  assert.match(result.stdout, /OPTIONAL SERVICE LIFECYCLE PASSED/);
} finally { fs.rmSync(lifecycle, { recursive: true, force: true }); }
assert.match(read("BridgeDispatcher.Sync.cs"),
  /personalSyncWebCommits[\s\S]*WaitAsync\(TimeSpan\.FromSeconds\(30\)\)/,
  "personal sync ACK is not gated by the web durable-save commit");
assert.match(application, /nachDauerhaftemSpeichern\(\(\) => Bruecke\.sende\(\{ cmd: "sync_commit"/,
  "provider sync result is not acknowledged after durable UI commit");
assert.match(application, /ausstehendeTransaktion[\s\S]*cmd: "sync", transactionId: transactionId/,
  "provider sync retry is not bound to a persisted unique transaction");
assert.match(application, /delete DATEN\.syncMetadaten\.nextcloud\.ausstehendeTransaktion/,
  "successful provider sync does not retire its transaction before the follow-up sync");
assert.match(bridge, /case "sync_commit": CommitSynchronization/,
  "provider sync commit is not dispatched");
assert.match(mainForm, /JSON\.parse\([^)]+\)/,
  "WebView callback arguments are not JSON-decoded from serialized data");
assert.match(mainForm, /BalloonTipClicked[\s\S]*App\.telefonAntwort/,
  "Windows notification click does not open the SMS reply composer");

for (const event of [
  "graphKonfiguration", "graphAnmeldung", "graphAbmeldung",
  "telefonStand", "telefonPairingOffen", "telefonPairingCode", "telefonGekoppelt",
  "geraetOeffnen", "geraetStatus", "kdePairingCode", "kdePairingStatus",
  "kdeSmsStatus", "telefonSmsEmpfangen", "telefonMeldung", "telefonFehler",
  "telefonEingehenderAnruf", "telefonWaehlStatus", "telefonAnnehmStatus", "telefonAuflegeStatus",
  "personalSync", "personalSyncFehler"
]) assert.match(application, new RegExp(`\\b${event}\\(nutzlast\\)`),
  `expected native event contract missing from App: ${event}`);

assert.doesNotMatch(html, /id="(?:telefon|sms)-schleier"/,
  "obsolete static communication dialogs remain in HTML");
assert.doesNotMatch(application, /cmd: "telefon_sms_senden"/,
  "obsolete Magnolie SMS command remains in UI");
assert.match(application, /if \(laufenderSpeicher\) return;/,
  "save serialization guard is missing");
assert.match(application, /vorBeenden\(\)[\s\S]*?speichereJetzt\(true\)/,
  "close does not flush pending data");
assert.match(application,
  /if \(beendenGewuenscht && Bruecke\.vorhanden\)[\s\S]*?cmd: "beenden_abgebrochen"/,
  "save failure does not release the native close state");
assert.match(bridge, /case "drucken": form\.ShowPrintDialog\(Text\(message, "html"\)\)/,
  "Windows printing does not pass the generated preview page to the native form");
assert.match(mainForm, /new HtmlPrintForm\(html, paths,/,
  "Windows printing does not load the generated preview page in a separate WebView");
assert.match(bridge, /regionsNode\.EnumerateArray\(\)/,
  "Windows holiday retrieval must process every selected region");
assert.match(bridge, /HolidayDownloadMaxBytes = 8 \* 1024 \* 1024/,
  "Windows holiday responses must have a cumulative size limit");
assert.match(bridge, /regionErforderlich/,
  "Windows holiday retrieval must reject a missing required region");

console.log("NATIVE INTEGRATION SMOKE TEST PASSED");
