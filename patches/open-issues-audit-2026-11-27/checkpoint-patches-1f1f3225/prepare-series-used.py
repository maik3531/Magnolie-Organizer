#!/usr/bin/env python3
"""Bind the reviewed patch series to a frozen upstream base and existing proofs."""
import hashlib, json, os, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parent / 'open-audit-final'
BASE = '1f1f3225ab50fe38902bc8e790454fd944f8b693'
OUT = HERE / 'final-patches'
OUT.mkdir(exist_ok=True)
for old in OUT.glob('*.patch'):
    old.unlink()  # Generated output only; the published checkpoint series is preserved separately.

def git(*args, env=None):
    return subprocess.check_output(['git', '-C', str(CHECKOUT), *args], env=env)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def source(path, ref='HEAD'):
    return git('show', f'{ref}:{path}')

head = git('rev-parse', 'HEAD').decode().strip()
tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
assert not git('status', '--porcelain').strip()
commits = git('rev-list', '--reverse', f'{BASE}..HEAD').decode().splitlines()
names = ['01-566-preserve-csv-contact-fields.patch', '02-192-correct-mcp-coverage.patch',
         '03-790-correct-current-source-test.patch', '04-330-shared-media-wait.patch',
         '05-330-initial-recovery-and-refresh.patch']
assert len(commits) >= len(names) == 5
for i, commit in enumerate(commits[5:],6):
    subject=git('show','-s','--format=%s',commit).decode().strip()
    label=next((name for token,name in [('Refs #395','395-organizer-suggestions'),
             ('Refs #843','843-worker-url-lifecycle'),('Refs #844','844-calendar-color-followup'),
             ('Refs #845','845-nextcloud-birthday-semantics')]
             if token in subject),None)
    assert label, subject
    names.append(f'{i:02d}-{label}.patch')
entries = []
for commit, name in zip(commits, names):
    data = git('format-patch', '-1', '--stdout', '--full-index', '--binary', commit)
    (OUT / name).write_bytes(data)
    entries.append({'path':name, 'commit':commit, 'sha256':sha(data), 'bytes':len(data),
                    'subject':git('show', '-s', '--format=%s', commit).decode().strip()})
combined = git('diff', '--binary', '--full-index', BASE, head)
(OUT / f'all-after-{BASE[:8]}.patch').write_bytes(combined)
entries.append({'path':f'all-after-{BASE[:8]}.patch', 'sha256':sha(combined), 'bytes':len(combined)})
apply_checks = []
for label, files in [('combined', [OUT/f'all-after-{BASE[:8]}.patch']), ('series', [OUT/n for n in names])]:
    with tempfile.TemporaryDirectory(prefix='magnolie-audit-index-') as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp)/'index'))
        git('read-tree', BASE, env=env)
        for file in files:
            git('apply', '--cached', '--check', str(file), env=env)
            git('apply', '--cached', str(file), env=env)
        actual = git('write-tree', env=env).decode().strip()
        assert actual == tree, (label, actual, tree)
        apply_checks.append({'kind':label, 'result_tree':actual, 'equal':True})

bindings=[]
def bind(label, expected, allow_differences=False):
    rows=[]
    for path, digest in expected.items():
        current=sha(source(path))
        rows.append({'path':path, 'tested_sha256':digest, 'final_sha256':current, 'equal':current==digest})
    if not allow_differences:
        assert all(r['equal'] for r in rows), (label, [r['path'] for r in rows if not r['equal']])
    bindings.append({'proof':label, 'inputs':rows, 'all_equal':all(r['equal'] for r in rows)})

validation=json.loads((HERE/'validation/after-50b15122/manifest.json').read_text())
python_inputs={p:v for p,v in validation['inputs'].items() if p.startswith('magnolie-organizer/') or p.startswith('contracts/')}
bind('Earlier 155 Python tests: compare to final inputs; changed sources require final focused results', python_inputs, True)
ui=json.loads((HERE/'desktop/evidence/759/source-commit-binding.json').read_text())
bind('6 wait + 5 recovery + 29 source-choice cases and existing media program',
     {r['path']:r['tested_sha256'] for r in ui['exact_test_input_bindings']}, True)
bind('Automatic settings transport: earlier source review; changed TelefonWerk reviewed in bounded delta',
     {r['path']:r['sha256'] for r in ui['unchanged_automatic_transport_inputs']}, True)
for part in ['jvm','ui','helper']:
    m=json.loads((HERE/f'special-tests/providers/{part}-manifest.json').read_text())
    bind(f'Provider {part} proof on original audit base; inspect any recorded source differences',m['source_files'], True)
candidate_paths=['.github/workflows/ports-2.0.30.yml','Magnolie-Organizer-macOS-Beta/tests/test_candidate_sources.py']
bind('7 CandidateSourceTests, same source and workflow', {p:sha(source(p,'09a5cd7a90ca98ef1663e6755cc9a05bf80553fe')) for p in candidate_paths})

fresh_evidence=[]
for relative, key, head_key in [
    ('validation/final/manifest.json','inputs','head'),
    ('import-export/final/manifest.json','inputs','source_head'),
    ('desktop/evidence/final-integration/manifest.json','source_inputs','head'),
    ('import-export/final-pipeline/pipeline-manifest.json','source_hashes','head_at_execution'),
]:
    data=json.loads((HERE/relative).read_text())
    assert data[head_key]==head,(relative,data[head_key],head)
    assert data.get('passed') is True or data.get('passed')==48,(relative,'failed')
    bind('Final integrated proof: '+relative,data[key])
    fresh_evidence.append({'path':relative,'sha256':sha((HERE/relative).read_bytes()),
                           'source_head':head})
integration=json.loads((HERE/'integration-final/manifest.json').read_text())
assert integration['head']==head and integration['tree']==tree and integration['required_passed']

manifest={'base_commit':BASE, 'base_tree':git('rev-parse',f'{BASE}^{{tree}}').decode().strip(),
          'head':head,'result_tree':tree,'product_merged_to_main':False,
          'series':entries[:-1],'combined_patch':entries[-1], 'apply_checks':apply_checks,
          'changed_files':git('diff','--name-only',BASE,head).decode().splitlines(),
          'evidence_bindings':bindings,
          'final_evidence':fresh_evidence,
          'integration_manifest':{'path':'integration-final/manifest.json',
              'sha256':sha((HERE/'integration-final/manifest.json').read_bytes())},
          'upstream_already_adopted':{'823':'50b1512234a765635f82af4537f277594fbf9878',
              '843':'66b50c44482f279d7c3566fe2959f66ebcc20cd5',
              '844_initial_fix':'8c99834367cc59c7bf936dd630e86a3194304f96'},
          'limits':'Source/host proof only. No installed package or month-long native soak acceptance.'}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(OUT/'SHA256SUMS').write_text(''.join(f"{e['sha256']}  {e['path']}\n" for e in entries))
print(json.dumps({'head':head,'tree':tree,'patches':len(entries),'apply_checks':apply_checks,
                  'binding_differences':{b['proof']:[r['path'] for r in b['inputs'] if not r['equal']] for b in bindings if not b['all_equal']}},indent=2))
