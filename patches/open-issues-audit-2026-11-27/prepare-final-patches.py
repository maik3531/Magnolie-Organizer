#!/usr/bin/env python3
"""Bind the reviewed patch series to a frozen upstream base and existing proofs."""
import hashlib, json, os, runpy, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parent / 'open-audit-final-current'
BASE = '7a490dd87e94eec08d7f09cb95a04b34bf4621c2'
PREVIOUS_HEAD = '32ff7d88af51c7e52275b3a0be348dae913c8598'
FINAL_HEAD = 'f3ea06e275ce6cd7547106096cfd96d27cf57e15'
OUT = HERE / 'final-patches'

def git(*args, env=None):
    return subprocess.check_output(['git', '-C', str(CHECKOUT), *args], env=env)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def source(path, ref='HEAD'):
    return git('show', f'{ref}:{path}')

head = git('rev-parse', 'HEAD').decode().strip()
tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
assert head == FINAL_HEAD, ('frozen final source', head, FINAL_HEAD)
assert not git('status', '--porcelain').strip()
commits = git('rev-list', '--reverse', f'{BASE}..HEAD').decode().splitlines()
names = ['01-566-preserve-csv-contact-fields.patch', '02-192-correct-mcp-coverage.patch',
         '03-790-correct-current-source-test.patch', '04-330-shared-media-wait.patch',
         '05-330-initial-recovery-and-refresh.patch', '06-395-organizer-suggestions.patch',
         '07-844-calendar-color-followup.patch', '08-845-nextcloud-birthday-followup.patch',
         '09-845-exported-birthday-exception-guard.patch']
assert len(commits) == len(names) == 9
assert commits[-2:] == [PREVIOUS_HEAD, FINAL_HEAD]
for commit, token in zip(commits[5:], ['Refs #395', 'Refs #844', 'Refs #845', 'Refs #845']):
    assert token in git('show', '-s', '--format=%s', commit).decode()

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

# Import only the tail runner's read-only helpers, never main()/build/tests.
tail_runner = HERE / 'run-final-csharp-tail.py'
helpers = runpy.run_path(str(tail_runner), run_name='audit_tail_binding_helpers')
current = helpers['inspect_checkout'](CHECKOUT, PREVIOUS_HEAD)
reused = helpers['bind_previous_evidence'](CHECKOUT, HERE, PREVIOUS_HEAD)
tail_relative = 'validation/final-csharp-tail/manifest.json'
tail_path = HERE / tail_relative
tail = json.loads(tail_path.read_text())
assert tail['runner_sha256'] == sha(tail_runner.read_bytes())
assert tail['head'] == head and tail['tree'] == tree
for key in ['previous_head', 'previous_tree', 'allowed_changes', 'source_changes',
            'previous_is_ancestor', 'other_tracked_paths_unchanged']:
    assert tail[key] == current[key], (tail_relative, key)
for key in ['passed', 'build_executed_by_runner', 'all_groups_completed', 'test_runs_passed',
            'head_unchanged', 'tree_unchanged', 'inputs_unchanged', 'assembly_unchanged_during_tests']:
    assert tail[key] is True, (tail_relative, key)
assert tail['build_exit_code'] == 0
assert not tail.get('error') and not tail.get('final_binding_error')
assert not tail['status_before'] and not tail['status_after']
assert tail['python_or_dom_tests_executed_by_runner'] is False
assert tail['reused_python_ui_evidence'] == reused
assert tail['expected_filters'] == 14 and tail['expected_groups'] == tail['passed_groups'] == 17
expected_runs = ['core-build'] + [name for name, _, _ in helpers['GROUPS']]
assert [run['name'] for run in tail['runs']] == expected_runs
assert '-t:Rebuild' in tail['runs'][0]['command']
assert '-p:RestoreLockedMode=true' in tail['runs'][0]['command']
for run in tail['runs']:
    assert run['exit_code'] == 0 and run['passed'] is True, run['name']
    assert sha((tail_path.parent / run['log']).read_bytes()) == run['sha256'], run['name']
for run, (_, term, count) in zip(tail['runs'][1:], helpers['GROUPS']):
    assert run['command'][-1] == term
    assert run['expected_groups'] == run['selected_groups'] == run['passed_groups'] == run['total_groups'] == count > 0
    assert run['group_count_matches'] is True
assert tail['source_diff']['sha256'] == sha(git('diff', '--binary', '--full-index', PREVIOUS_HEAD, head))
assert sha((tail_path.parent / tail['source_diff']['path']).read_bytes()) == tail['source_diff']['sha256']
assert set(tail['tracked_build_and_fixture_inputs']) == set(helpers['build_input_paths'](CHECKOUT))
bind('Fresh final C# locked rebuild and 17 groups', tail['tracked_build_and_fixture_inputs'])
assert sha((CHECKOUT / tail['assembly_path']).read_bytes()) == tail['assembly_sha256']

reused_evidence = []
for proof in reused['bindings']:
    bind('Unchanged Python/UI proof from ' + PREVIOUS_HEAD[:8] + ': ' + proof['manifest'], proof['inputs'])
    reused_evidence.append({**proof, 'bound_to_final_head': head,
                            'binding_manifest': tail_relative,
                            'binding_manifest_sha256': sha(tail_path.read_bytes())})

pipeline_relative = 'import-export/final-tail-pipeline/pipeline-manifest.json'
pipeline_path = HERE / pipeline_relative
pipeline = json.loads(pipeline_path.read_text())
assert pipeline['head_at_execution'] == head
assert pipeline['passed'] == 48 and len(pipeline['results']) == 48
assert not pipeline.get('error')
assert pipeline['assembly_sha256'] == tail['assembly_sha256']
assert pipeline['build_executed_by_runner'] is False and pipeline['build_exit_code'] is None
assert all(row['passed'] is True for row in pipeline['results'])
vectors = json.loads(source('contracts/calendar-color-remainders.json'))
expected_cases = {(runtime, edition, vector['id']) for runtime in ['python', 'csharp']
                  for edition in ['linux', 'windows'] for vector in vectors}
assert len(expected_cases) == 48
assert {(row['runtime'], row['edition'], row['id']) for row in pipeline['results']} == expected_cases
assert len(pipeline['commands']) == 9
for run in pipeline['commands']:
    assert run['exit_code'] == 0, run['label']
    assert sha((pipeline_path.parent / run['log']).read_bytes()) == run['log_sha256'], run['label']
assert set(pipeline['source_hashes']) == {
    'magnolie-organizer/bin/magnolie-organizer', 'magnolie-organizer/web/anwendung.js',
    'magnolie-organizer-windows/ExchangeCodec.cs', 'magnolie-organizer-windows/AtomicStore.cs',
    'magnolie-organizer-windows/app/web/anwendung.js', 'contracts/calendar-color-remainders.json',
    'magnolie-organizer-windows/tests/calendar-colour-remainders.js'}
bind('Fresh final 48-case actual codec/save/reopen pipeline', pipeline['source_hashes'])
fresh_evidence = [
    {'path': relative, 'sha256': sha((HERE / relative).read_bytes()), 'source_head': head}
    for relative in [tail_relative, pipeline_relative]
]
integration_path = HERE / 'integration-final-current/manifest.json'
integration = json.loads(integration_path.read_text())
assert integration['head'] == PREVIOUS_HEAD and integration['tree'] == tail['previous_tree']
assert integration['required_passed'] is True

# Generate delivery output only after all source and evidence guards have passed.
OUT.mkdir(exist_ok=True)
for old in OUT.glob('*.patch'):
    old.unlink()  # Generated output only; published checkpoint series remain separate.
entries = []
for commit, name in zip(commits, names):
    data = git('format-patch', '-1', '--stdout', '--full-index', '--binary', commit)
    (OUT / name).write_bytes(data)
    entries.append({'path': name, 'commit': commit, 'sha256': sha(data), 'bytes': len(data),
                    'subject': git('show', '-s', '--format=%s', commit).decode().strip()})
combined = git('diff', '--binary', '--full-index', BASE, head)
(OUT / f'all-after-{BASE[:8]}.patch').write_bytes(combined)
entries.append({'path': f'all-after-{BASE[:8]}.patch', 'sha256': sha(combined), 'bytes': len(combined)})
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
        apply_checks.append({'kind': label, 'result_tree': actual, 'equal': True})

manifest={'base_commit':BASE, 'base_tree':git('rev-parse',f'{BASE}^{{tree}}').decode().strip(),
          'head':head,'result_tree':tree,'product_merged_to_main':False,
          'series':entries[:-1],'combined_patch':entries[-1], 'apply_checks':apply_checks,
          'changed_files':git('diff','--name-only',BASE,head).decode().splitlines(),
          'evidence_bindings':bindings,
          'final_evidence':fresh_evidence,
          'reused_python_ui_evidence':reused_evidence,
          'csharp_tail':{'path':tail_relative, 'sha256':sha(tail_path.read_bytes()),
              'previous_head':PREVIOUS_HEAD, 'head':head, 'groups':17,
              'build_executed_by_runner':True, 'assembly_sha256':tail['assembly_sha256'],
              'allowed_source_changes':current['allowed_changes']},
          'integration_manifest':{'path':'integration-final-current/manifest.json',
              'sha256':sha(integration_path.read_bytes()), 'source_head':PREVIOUS_HEAD,
              'used_for':'Historical complete green integration; only unchanged Python/UI results are transferred via the C# tail manifest.',
              'old_csharp_assembly_reused':False, 'old_codec_storage_pipeline_reused':False},
          'upstream_already_adopted':{'823':'50b1512234a765635f82af4537f277594fbf9878',
              '843':'66b50c44482f279d7c3566fe2959f66ebcc20cd5',
              '844_initial_fix':'8c99834367cc59c7bf936dd630e86a3194304f96',
              '845_initial_fix':'7a490dd87e94eec08d7f09cb95a04b34bf4621c2'},
          'limits':'Source/host proof only. No installed package or month-long native soak acceptance.'}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(OUT/'SHA256SUMS').write_text(''.join(f"{e['sha256']}  {e['path']}\n" for e in entries))
print(json.dumps({'head':head,'tree':tree,'patches':len(entries),'apply_checks':apply_checks,
                  'binding_differences':{b['proof']:[r['path'] for r in b['inputs'] if not r['equal']] for b in bindings if not b['all_equal']}},indent=2))
