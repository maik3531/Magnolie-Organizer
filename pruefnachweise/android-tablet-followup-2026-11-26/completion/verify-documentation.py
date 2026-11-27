from pathlib import Path
import argparse
import hashlib
import json
import subprocess

parser = argparse.ArgumentParser(description='Compare the final documentation-only follow-up with the CI101 tested tree and runtime assets.')
parser.add_argument('--repository', type=Path, required=True)
parser.add_argument('--ci-projection', type=Path, required=True)
parser.add_argument('--base-commit', required=True, help='CI101 remote commit or its documented same-tree local commit')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
repo = args.repository.resolve()
ci = args.ci_projection.resolve()
current = repo / 'Magnolie-Organizer-Android-Tablet-Beta/app/build/generated/projection/assets/projection.json'
a = json.loads(ci.read_text())
b = json.loads(current.read_text())
assert a['sourceHash'] == 'dbe502cf4ad4661be79dca584c120d8623676cf8be5c3ff0d61eba840b676c09'
assert len(a['outputs']) == 83 and a['outputs'] == b['outputs']
base = args.base_commit
tree = subprocess.check_output(['git', 'rev-parse', base+'^{tree}'], cwd=repo, text=True).strip()
assert tree == '06c1a8cf6f115908dc21252682c2a358246f2cb7'
changed = subprocess.check_output(['git', 'diff', '--name-only', base], cwd=repo, text=True).splitlines()
docs = {'ARBEITSSTAND.md', 'contracts/android-tablet-followup-2026-11-26.md',
        'Magnolie-Organizer-Android-Tablet-Beta/README.md'}
evidence_prefix = 'pruefnachweise/android-tablet-followup-2026-11-26/'
assert all(p in docs or p.startswith(evidence_prefix) for p in changed), changed
smoke = 'Magnolie-Organizer-Android-Tablet-Beta/app/src/androidTest/java/io/gitlab/maik3531/magnolietabletbeta/NativeSystemProviderSmoke.kt'
raw = (repo/smoke).read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'd8b598923ef3f1d092ed3ffb83268571e748a6cb3ac035c8fb69ca0e1826fba3'
assert raw == subprocess.check_output(['git', 'show', base+':'+smoke], cwd=repo)
result = {
    'kind': 'derived-final-documentation-comparison',
    'testedRun': 45822320243,
    'testedRemoteHead': '7a7d90b04796cf338b98f0fdbb87e8da1c967043',
    'comparedBaseCommit': base, 'testedTree': tree,
    'testedProjection': a['sourceHash'], 'documentationProjection': b['sourceHash'],
    'originalProjectionSha256': hashlib.sha256(ci.read_bytes()).hexdigest(),
    'currentProjectionSha256': hashlib.sha256(current.read_bytes()).hexdigest(),
    'runtimeOutputCount': 83, 'allRuntimeOutputsByteIdentical': True,
    'changedTrackedPathsAtVerification': changed,
    'onlyDocumentationOrEvidenceChanged': True,
    'fixtureSourceSha256': hashlib.sha256(raw).hexdigest(),
    'runtimeOutputs': b['outputs'],
    'scope': 'Executed comparison only; no new APK or emulator run is attributed to the final documentation/evidence commit.'
}
dest = args.output
dest.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['testedProjection','documentationProjection','runtimeOutputCount','allRuntimeOutputsByteIdentical','onlyDocumentationOrEvidenceChanged']}))
