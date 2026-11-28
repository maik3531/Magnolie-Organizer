#!/usr/bin/env python3
"""Refs #854/#857: actual C# provider with synthetic and captured BE/NL responses.

Uses an existing .NET SDK; downloads/installs nothing. Build files remain in
the explicitly supplied scratch directory. --source-root supports baseline
replay with exactly the same case file and unchanged public entry point.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--framework", default="net8.0", choices=("net8.0", "net9.0", "net10.0"),
                        help="Host test target only; does not modify the Windows product target")
    parser.add_argument("--provider-fixtures", type=Path,
                        default=Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "holiday-groups-2026-11-28")
    parser.add_argument("--prepare-only", action="store_true", help="Materialize source-bound harness without claiming a compiler run")
    args = parser.parse_args()
    project = args.source_root / "magnolie-organizer-windows"
    target = args.build_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    bridge = (project / "BridgeDispatcher.cs").read_text()

    def between(start, end):
        if bridge.count(start) != 1 or bridge.count(end) != 1:
            raise RuntimeError("Actual C# source boundary changed: " + start)
        first, last = bridge.index(start), bridge.index(end)
        if last <= first:
            raise RuntimeError("Actual C# source boundaries are reordered")
        return bridge[first:last]

    members = [between("    private async Task FetchHolidaysAsync(", "    private async Task ImportAsync("),
               between("    private static string Text(", "    private static int Integer("),
               between("    private static bool Boolean(", "    private static int Port(")]
    record = "    private sealed record HolidayRegion(string Code, string Name);"
    if bridge.count(record) != 1:
        raise RuntimeError("Actual HolidayRegion declaration changed")
    members.append(record)
    actual = "#nullable enable\nnamespace MagnolieOrganizer.Windows; public sealed partial class HolidayFetchCoverageHost {\n" + "\n".join(members) + "\n}\n"
    (target / "ProviderMethods.g.cs").write_text(actual)
    setup = (project / "FirstRunSetupState.cs").read_text()
    boundary = "internal sealed class FirstRunSetupState\n"
    if setup.count(boundary) != 1:
        raise RuntimeError("Actual setup normalizer source boundary changed")
    (target / "SetupNormalizer.g.cs").write_text("#nullable enable\n" + setup[:setup.index(boundary)])
    (target / "OpenHolidayData.cs").write_text((project / "OpenHolidayData.cs").read_text())
    fixture = Path(__file__).with_suffix(".cs.txt")
    (target / "Cases.cs").write_text(fixture.read_text())
    (target / "GlobalUsings.cs").write_text("global using System.Globalization;\nglobal using System.Text.Json;\n")
    (target / "HolidayCoverage.csproj").write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>{args.framework}</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors>
    <RestoreSources></RestoreSources></PropertyGroup>
</Project>
''')
    (target / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>\n')
    inputs = {str(path.relative_to(args.source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (project / "BridgeDispatcher.cs", project / "OpenHolidayData.cs", project / "FirstRunSetupState.cs")}
    inputs["case_file_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
    fixture_root = args.provider_fixtures.resolve()
    for capture in sorted(fixture_root.glob("*.json")):
        inputs["fixture/" + capture.name] = hashlib.sha256(capture.read_bytes()).hexdigest()
    inputs["extracted_members_sha256"] = hashlib.sha256(actual.encode()).hexdigest()
    (target / "source-bindings.json").write_text(json.dumps(inputs, indent=2) + "\n")
    if args.prepare_only:
        print(json.dumps({"status": "prepared-only", "source_bindings": inputs}, indent=2))
        return 0
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
               DOTNET_CLI_HOME=str(target / "cli-state"), MAGNOLIE_HOLIDAY_GROUP_FIXTURES=str(fixture_root))
    build = subprocess.run([args.dotnet, "build", str(target / "HolidayCoverage.csproj"), "--configuration", "Release",
                            "--nologo", "-p:UseSharedCompilation=false"], env=env, text=True, capture_output=True)
    (target / "build.log").write_text(build.stdout + build.stderr)
    print(build.stdout + build.stderr, end="")
    if build.returncode:
        return build.returncode
    run = subprocess.run([args.dotnet, str(target / f"bin/Release/{args.framework}/HolidayCoverage.dll")], env=env,
                         text=True, capture_output=True)
    (target / "run.log").write_text(run.stdout + run.stderr)
    print(run.stdout + run.stderr, end="")
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
