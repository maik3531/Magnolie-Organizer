"use strict";
// Compile only the byte-exact actual SocialUri/HTTPS policy methods. Phone,
// profile and OS-launch routes are throwing dependencies, never test fallbacks.
const fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const { findExecutable, assertSpawned } = require("./native-test-process");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "BridgeDispatcher.cs"), "utf8");
function method(signature) {
  const start = source.indexOf(signature);
  assert.ok(start >= 0 && source.indexOf(signature, start + 1) < 0, "Exact native method must be unique");
  const next = /\n    (?:private|internal|public) static /.exec(source.slice(start + signature.length));
  const end = next ? start + signature.length + next.index : -1;
  assert.ok(end > start, "Exact native method end must be present");
  return source.slice(start, end);
}
const social = method("    private static string SocialUri(JsonElement message)");
const policy = method("    private static bool IsAllowedHttpsTarget(string target)");
const candidate = process.env.DOTNET_HOST_PATH || (process.env.DOTNET_ROOT
  ? path.join(process.env.DOTNET_ROOT, process.platform === "win32" ? "dotnet.exe" : "dotnet")
  : process.platform === "win32" ? path.join(process.env.ProgramFiles || "C:\\Program Files", "dotnet/dotnet.exe") : "dotnet");
const found = findExecutable([candidate], ["--version"], 8);
assert.ok(found.command, "Working .NET 8-compatible SDK required: " + found.diagnostics.join("; "));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-attachment-native-"));
try {
  const config = path.join(temp, "NuGet.Config"), home = path.join(temp, "home");
  fs.mkdirSync(home);
  fs.writeFileSync(config, '<configuration><packageSources><clear /></packageSources></configuration>');
  const xml = value => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  fs.writeFileSync(path.join(temp, "Policy.csproj"), `<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
    <OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable><NuGetAudit>false</NuGetAudit><UseSharedCompilation>false</UseSharedCompilation>
    <BuildInParallel>false</BuildInParallel><RestoreConfigFile>${xml(config)}</RestoreConfigFile>
    </PropertyGroup></Project>`);
  const cases = [
    { uri: "https://example.org/public%20attachment.pdf?part=1#section", expected: true },
    { uri: "https://drive.google.com/public-document", expected: true },
    { uri: "http://example.org/public%20attachment.pdf?part=1#section", expected: false },
    { uri: "https://user:password@example.org/private.pdf", expected: false },
    { uri: "file:///synthetic/not-a-real-file.pdf", expected: false },
    { uri: "javascript:throw('never executed')", expected: false },
    { uri: "webdav://example.org/synthetic.pdf", expected: false }
  ];
  fs.writeFileSync(path.join(temp, "Program.cs"), `using System.Text.Json;
class Program {
  static string Text(JsonElement value, string name) => value.GetProperty(name).GetString() ?? "";
  static string Profile(string prefix, string value) => throw new Exception("Unexpected profile route");
  static class NativeMethods { public static bool HasUriScheme(string value) => throw new Exception("OS handlers forbidden"); }
  static class PhoneUri { public static string Build(string service, string value, string country, bool installed) => throw new Exception("Unexpected phone route"); }
${social}
${policy}
  static void Main() {
    using var tests = JsonDocument.Parse(${JSON.stringify(JSON.stringify(cases))});
    foreach (var test in tests.RootElement.EnumerateArray()) {
      var uri = test.GetProperty("uri").GetString()!;
      using var request = JsonDocument.Parse(JsonSerializer.Serialize(new { dienst = "custom", wert = uri, aktionArt = "url", aktionZiel = uri, land = "DE" }));
      var result = SocialUri(request.RootElement);
      if (result != (test.GetProperty("expected").GetBoolean() ? uri : "")) throw new Exception("Actual native attachment policy mismatch");
    }
    Console.WriteLine("C# CALENDAR ATTACHMENT POLICY PASSED: 7 actual method cases, no OS handler or network execution");
  }
}`);
  const result = spawnSync(found.command, ["run", "--project", path.join(temp, "Policy.csproj"), "--verbosity", "quiet", "--disable-build-servers"], {
    encoding: "utf8", timeout: 120000,
    env: { ...process.env, HOME: home, DOTNET_CLI_HOME: home, DOTNET_CLI_TELEMETRY_OPTOUT: "1",
      DOTNET_GENERATE_ASPNET_CERTIFICATE: "false", DOTNET_NOLOGO: "1", DOTNET_CLI_USE_MSBUILD_SERVER: "0",
      MSBUILDDISABLENODEREUSE: "1", NUGET_PACKAGES: path.join(temp, "packages") }
  });
  assertSpawned(result, "Actual calendar attachment native policy");
  assert.equal(result.status, 0, result.stderr + result.stdout);
  assert.match(result.stdout, /C# CALENDAR ATTACHMENT POLICY PASSED/);
  console.log(result.stdout.trim());
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
