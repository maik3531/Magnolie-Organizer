#!/usr/bin/env python3
"""Use the existing C# source-host project with one identical progress entry."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from xml.sax.saxutils import escape

parser = argparse.ArgumentParser()
parser.add_argument("baseline", type=Path)
parser.add_argument("patched", type=Path)
parser.add_argument("--dotnet", default="dotnet")
args = parser.parse_args()
probe = Path(__file__).resolve().with_name("WindowsProgressProbe.cs")
results = {}
with tempfile.TemporaryDirectory(prefix="magnolie-128-progress-") as temporary:
    root = Path(temporary)
    target = root / "Probe.targets"
    target.write_text('<Project><Target Name="SelectQueueProgressProbe" BeforeTargets="CoreCompile"><ItemGroup>'
        '<Compile Remove="Program.cs"/><Compile Remove="$(MSBuildProjectDirectory)/Program.cs"/>'
        '<Compile Include="' + escape(str(probe), {'"': '&quot;'}) + '"/>'
        '</ItemGroup></Target></Project>')
    for label, checkout, expected in [("baseline", args.baseline, 1), ("patched", args.patched, 0)]:
        output = root / label
        subprocess.run([args.dotnet, "build", "magnolie-organizer-windows/tests/CoreTests.csproj", "--no-restore", "--nologo",
            "-p:CustomAfterMicrosoftCommonTargets=" + str(target), "-p:OutputPath=" + str(output) + "/"], cwd=checkout, check=True)
        run = subprocess.run([args.dotnet, str(output / "CoreTests.dll")], cwd=checkout, capture_output=True, text=True)
        assert run.returncode == expected, (label, run.returncode, run.stdout, run.stderr)
        results[label] = dict(exit_code=run.returncode, observation=json.loads(run.stdout))
print(json.dumps(results, indent=2))
