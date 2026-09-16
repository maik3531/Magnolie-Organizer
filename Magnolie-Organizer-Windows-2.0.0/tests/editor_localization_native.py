"""One offline C# fixture, two CPUs, 6 GiB cgroup, four-minute outer deadline."""
import os
from pathlib import Path
import subprocess
import tempfile
from xml.sax.saxutils import escape

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE.parent
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
cgroup = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
limit = (Path('/sys/fs/cgroup') / cgroup.lstrip('/') / 'memory.max').read_text().strip()
assert limit != 'max' and int(limit) <= 6 * 1024**3, 'Use systemd-run --user --scope -p MemoryMax=6G'
with tempfile.TemporaryDirectory(prefix='editor-native-', dir='/tmp/opencode') as temporary:
    work = Path(temporary)
    (work / 'Program.cs').write_text(Path(__file__).with_name('editor-localization.cs.txt').read_text())
    links = ''.join('<Compile Include="' + escape(str(SOURCE / name)) + '" />'
                    for name in ('WindowsSpellChecker.cs', 'NativeLocalization.cs'))
    (work / 'Editor.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>'
        '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
        '</PropertyGroup><ItemGroup>' + links + '<Content Include="' +
        escape(str(SOURCE / 'app/native-i18n.json')) + '" Link="native-i18n.json" '
        'CopyToOutputDirectory="PreserveNewest" /></ItemGroup></Project>')
    (work / 'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    env = dict(os.environ, HOME=str(work), DOTNET_CLI_HOME=str(work), DOTNET_PROCESSOR_COUNT='2',
        DOTNET_GCHeapHardLimit='0x30000000', DOTNET_CLI_TELEMETRY_OPTOUT='1',
        DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_NOLOGO='1', DOTNET_GENERATE_ASPNET_CERTIFICATE='false')
    dotnet = os.environ.get('MAGNOLIE_DOTNET', '/tmp/opencode/fivefixnative/dotnet/dotnet')
    print('Building one actual-class editor fixture:', work, flush=True)
    subprocess.run([dotnet, 'build', str(work / 'Editor.csproj'), '--configfile', str(work / 'NuGet.Config'),
        '-m:1', '-p:UseSharedCompilation=false', '-nodeReuse:false', '-v:q'], env=env, cwd=work, check=True, timeout=100)
    print('Running native errors and resources for all 20 locales', flush=True)
    subprocess.run([dotnet, str(work / 'bin/Debug/net8.0/Editor.dll'), str(ROOT / 'tools/editor_locales.json')],
                   env=env, cwd=work, check=True, timeout=100)
