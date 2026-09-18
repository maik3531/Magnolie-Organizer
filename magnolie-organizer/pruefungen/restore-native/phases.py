"""One bounded C# source/store fixture build; isolated output, cached packages only."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "magnolie-organizer-windows"
WORK = Path(tempfile.mkdtemp(prefix="asr02-host-", dir="/tmp/opencode"))
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
# CoreCLR reserves virtual address space above its physical heap budget. Bound
# resident memory for the entire build process tree with the caller's cgroup.
cgroup = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
limit = (Path("/sys/fs/cgroup") / cgroup.lstrip("/") / "memory.max").read_text().strip()
assert limit != "max" and int(limit) <= 6 * 1024**3, "Run in systemd scope with MemoryMax=6G"

def method(source, name):
    match = re.search(r"^    private [^\n]*\b" + name + r"\(", source, re.M)
    assert match, name
    end = re.search(r"^    (?:private|internal|public) ", source[match.end():], re.M)
    return source[match.start():match.end() + end.start()] if end else source[match.start():source.rfind("}")]

bridge = (SRC / "BridgeDispatcher.cs").read_text()
background = (SRC / "BridgeDispatcher.Background.cs").read_text()
names = ["SaveAsync", "RestoreBackupAsync", "ImportGesamtarchivAsync", "RestoreSnapshotAsync", "RequireJsonObject", "SnapshotId",
         "CreateSnapshot", "CreateRestorePoint", "PrepareRestoredData", "CompleteRestoreRuntimeAsync", "CommitRestoredProfile",
         "SendRestoreResultAsync", "RefreshReminderData", "DeleteReminderData", "UpdateReminderRuntime"]
methods = "\n".join(method(bridge, name) for name in names)
save = method(bridge, "SaveAsync")
guard = save.index("            // The persisted restore epoch")
end_guard = save.index("            if (currentPlainTextAvailable &&", guard)
# Intentional negative control: remove only the persisted-epoch guard, as in
# the original AUR fixture. Never replace the actual positive restore/save path.
methods += "\n" + (save[:guard] + save[end_guard:]).replace("Task SaveAsync(", "Task SaveBeforeAsync(")
methods += "\n" + "\n".join(method(background, name) for name in ["FencePhoneRestoreAsync", "ReleaseRestoreFence", "RetryRestoreRepairAsync", "QueueBackground", "QueueNetworkCommand", "NetworkDeadline"])
(WORK / "Program.cs").write_text(Path(__file__).with_name("Host.cs.txt").read_text().replace("/* METHODS */", methods))
project = ET.parse(SRC / "tests/CoreTests.csproj").getroot()
links = []
for node in project.findall(".//Compile"):
    name = node.get("Include", "")
    if not name or node.get("Condition"): continue
    path = (SRC / "tests" / name.replace("\\", "/")).resolve()
    links.append('<Compile Include="' + escape(str(path)) + '" />')
packages = "".join(ET.tostring(node, encoding="unicode") for node in project.findall(".//PackageReference"))
(WORK / "Host.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
    '<TargetFramework>net8.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
    '</PropertyGroup><ItemGroup>' + "".join(links) + packages + '</ItemGroup><ItemGroup><Content Include="' +
    escape(str(SRC / "app/native-i18n.json")) + '" Link="native-i18n.json" CopyToOutputDirectory="PreserveNewest" />'
    '</ItemGroup></Project>')
(WORK / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
env = dict(os.environ, HOME=str(WORK), DOTNET_CLI_HOME=str(WORK), DOTNET_PROCESSOR_COUNT="2",
    DOTNET_GCHeapHardLimit="0x30000000", DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
    DOTNET_NOLOGO="1", DOTNET_GENERATE_ASPNET_CERTIFICATE="false", NUGET_PACKAGES=os.environ.get("NUGET_PACKAGES", str(Path.home() / ".nuget/packages")),
    XDG_CONFIG_HOME=str(WORK / "config"), XDG_DATA_HOME=str(WORK / "data"), XDG_CACHE_HOME=str(WORK / "cache"))
dotnet = os.environ.get("MAGNOLIE_DOTNET", "/tmp/opencode/fivefixnative/dotnet/dotnet")
print("Private fixture:", WORK, flush=True)
subprocess.run([dotnet, "build", str(WORK / "Host.csproj"), "--configfile", str(WORK / "NuGet.Config"),
    "-m:1", "-p:UseSharedCompilation=false", "-nodeReuse:false", "-v:q"], env=env, cwd=WORK, check=True, timeout=100)
subprocess.run([dotnet, str(WORK / "bin/Debug/net8.0/Host.dll"), str(WORK / "fixtures")],
    env=env, cwd=WORK, check=True, timeout=100)
