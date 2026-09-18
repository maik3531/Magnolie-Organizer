#!/usr/bin/env python3
"""Offline portable C# host -> actual JS call functions; synthetic Android capture input."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--trace', type=Path)
parser.add_argument('--output', type=Path, default=Path('/tmp/opencode/asr04-native'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
out = args.output.resolve()
assert out.is_relative_to('/tmp/opencode') and out != Path('/tmp/opencode')
for name in ('home', 'tmp', 'obj', 'bin', 'feed'):
    (out / name).mkdir(parents=True, exist_ok=True)
dotnet = Path('/tmp/opencode/fivefixnative/dotnet')
bun = Path.home() / '.bun/bin'
packages = Path.home() / '.nuget/packages'
base = ['bwrap', '--die-with-parent', '--unshare-net', '--ro-bind', '/', '/', '--tmpfs', '/home', '--tmpfs', '/tmp',
    '--ro-bind', str(dotnet), str(dotnet),
    '--ro-bind', str(root.parent), str(root.parent), '--ro-bind', str(packages), str(packages),
    '--ro-bind', str(bun), str(bun), '--bind', str(out), str(out), '--proc', '/proc', '--dev', '/dev', '--clearenv']
if args.trace: base += ['--ro-bind', str(args.trace.resolve().parent), str(args.trace.resolve().parent)]
env = dict(PATH='/usr/bin:/bin', HOME=str(out/'home'), DOTNET_CLI_HOME=str(out/'home'),
    TMPDIR=str(out/'tmp'), DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_PROCESSOR_COUNT='2', NUGET_PACKAGES=str(packages))
for key, value in env.items(): base += ['--setenv', key, value]
project = root/'tests/CoreTests.csproj'
props = [f'-p:BaseIntermediateOutputPath={out}/obj/', f'-p:MSBuildProjectExtensionsPath={out}/obj/', '-p:NuGetAudit=false']
commands = [
    [str(dotnet/'dotnet'), 'restore', str(project), '--locked-mode', '--source', str(out/'feed'), *props],
    [str(dotnet/'dotnet'), 'build', str(project), '--no-restore', '-c', 'Release', '-m:1', '-p:UseSharedCompilation=false', f'-p:OutputPath={out}/bin/', *props],
    [str(dotnet/'dotnet'), str(out/'bin/CoreTests.dll'), '--scoped-call-host', *([str(args.trace.resolve()), str(out/'host-events.json')] if args.trace else [])],
    [str(dotnet/'dotnet'), str(out/'bin/CoreTests.dll'), 'Telefonverbindung'],
]
if args.trace: commands += [[str(bun/'bun'), str(root/'tests/callstate/outgoing.js'), str(out/'host-events.json')]]
inputs = [root/name for name in ('TelefonCoordinator.cs', 'TelefonProtocolContract.cs', 'TelefonCallContract.cs',
    'BridgeDispatcher.Sync.cs', 'app/web/anwendung.js', 'tests/OutgoingDialTests.cs', 'tests/callstate/outgoing.js', 'tests/callstate/outgoing.py')]
if args.trace:
    inputs.append(args.trace.resolve())
    inputs += [args.trace.resolve().with_name(name+'.json') for name in ('scoped-timeout', 'scoped-incoming-collision')]
def hashes(): return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
before = hashes()
stages = []
for index, command in enumerate(commands):
    result = subprocess.run(base + command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    (out/f'stage-{index}.log').write_bytes(result.stdout)
    print(result.stdout.decode(), end='', flush=True)
    stages.append(dict(command=command, exit_code=result.returncode))
    after = hashes()
    (out/'result.json').write_text(json.dumps(dict(passed=result.returncode == 0 and index == len(commands)-1 and before == after,
        sources_unchanged=before == after, sources_before=before, sources_after=after, stages=stages, hardware=False), indent=2))
    if result.returncode: raise SystemExit(result.returncode)
if before != hashes(): raise SystemExit('Source or capture changed during probe')
