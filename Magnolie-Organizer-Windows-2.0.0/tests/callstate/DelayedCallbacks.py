"""Generate a portable source-linked probe; platform callbacks are capture fakes."""
import os
import re
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
WIN = ROOT / "Magnolie-Organizer-Windows-2.0.0"
OUT = Path("/tmp/opencode/v1-v4-probe")
OUT.mkdir(exist_ok=True)
project = ET.parse(WIN / "tests/CoreTests.csproj").getroot()
for group in list(project):
    if group.tag == "ItemGroup":
        for item in list(group):
            if item.tag == "Compile" and "Include" in item.attrib and "Condition" not in item.attrib:
                item.attrib = {"Include": str((WIN / "tests" / item.attrib["Include"].replace("\\", "/")).resolve())}
            elif item.tag != "PackageReference":
                group.remove(item)
props = project.find("PropertyGroup")
ET.SubElement(props, "EnableDefaultCompileItems").text = "false"
ET.SubElement(props, "TreatWarningsAsErrors").text = "false"
items = ET.SubElement(project, "ItemGroup")
for name in ("DelayedCallbacks.cs", "Framework.cs"):
    ET.SubElement(items, "Compile", Include=str(Path(__file__).parent / name))
ET.SubElement(items, "Compile", Include=str(OUT / "MainForm.cs"))
ET.ElementTree(project).write(OUT / "Probe.csproj")

source = (WIN / "MainForm.cs").read_text()
methods = []
for name, end in (("TrackIncomingCall", "    internal void ShowIncomingCall"),
                  ("ShowIncomingCall", "    internal void ShowTelefonNotification"),
                  ("SendAsync", "    internal async void CloseAfterSave")):
    start = re.search(r"    internal [^\n]*\b" + name + r"\(", source).start()
    methods.append(source[start:source.index(end, start)])
(OUT / "MainForm.cs").write_text("using System.Text.Json;\nusing System.Text.Json.Nodes;\nnamespace MagnolieOrganizer.Windows;\ninternal partial class MainForm {\n" + "\n".join(methods) + "\n}\n" + source[source.index("internal static class JsonOptions"):])
env = dict(os.environ, DOTNET_PROCESSOR_COUNT="2", DOTNET_CLI_TELEMETRY_OPTOUT="1", TMPDIR="/tmp/opencode")
subprocess.run(["/tmp/opencode/fivefixnative/dotnet/dotnet", "run", "--project", str(OUT / "Probe.csproj"),
                "-p:UseSharedCompilation=false", "-m:1"], env=env, check=True)
