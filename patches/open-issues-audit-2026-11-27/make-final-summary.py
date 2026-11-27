#!/usr/bin/env python3
"""Summarize the final source-bound proofs without relabeling older runs."""
import datetime, hashlib, json, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent / 'open-audit-final-current'
BASE = '7a490dd87e94eec08d7f09cb95a04b34bf4621c2'
FINAL = 'f3ea06e275ce6cd7547106096cfd96d27cf57e15'
PREVIOUS = '32ff7d88af51c7e52275b3a0be348dae913c8598'
sha = lambda data: hashlib.sha256(data).hexdigest()

def read(name):
    return json.loads((ROOT / name).read_text())

def ref(name):
    return {'path': name, 'sha256': sha((ROOT / name).read_bytes())}

def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()

assert git('rev-parse', 'HEAD') == FINAL
assert not git('status', '--porcelain')
patch = read('final-patches/manifest.json')
tail = read('validation/final-csharp-tail/manifest.json')
pipeline = read('import-export/final-tail-pipeline/pipeline-manifest.json')
previous = read('integration-final-current/manifest.json')
ui = read('desktop/evidence/final-current/manifest.json')
assert patch['base_commit'] == BASE and patch['head'] == FINAL
assert patch['result_tree'] == git('rev-parse', 'HEAD^{tree}')
assert len(patch['series']) == 9 and all(x['equal'] for x in patch['apply_checks'])
assert tail['head'] == FINAL and tail['previous_head'] == PREVIOUS and tail['passed'] is True
assert tail['build_executed_by_runner'] and tail['build_exit_code'] == 0
assert tail['passed_groups'] == tail['expected_groups'] == 17
assert pipeline['head_at_execution'] == FINAL and pipeline['passed'] == 48
assert pipeline['assembly_sha256'] == tail['assembly_sha256']
assert previous['head'] == PREVIOUS and previous['required_passed']
assert ui['head'] == PREVIOUS and ui['passed']
for binding in tail['reused_python_ui_evidence']['bindings']:
    assert binding['all_selected_inputs_equal'] and not binding['reexecuted_by_this_runner']
    assert sha((ROOT / binding['manifest']).read_bytes()) == binding['manifest_sha256']

contract_log = (ROOT / 'import-export/final-current/python-file-contract.log').read_text()
contract_count = len(re.findall(r'^\s*ok\s+-', contract_log, re.MULTILINE))
semantic_log = (ROOT / 'import-export/final-current/python-semantics.log').read_text()
assert contract_count == 26 and re.search(r'\b286 passed\b', semantic_log)
assert read('validation/final-current/manifest.json')['python_counts']['passed'] == 155
ui_programs = [r['name'] for r in ui['runs'] if r['name'].endswith('.js')]
assert len(ui_programs) == 15

internet = previous['internet_protocol_reused']
assert sha((ROOT / internet['path']).read_bytes()) == internet['sha256']
assert read(internet['path'])['passed']
for name, digest in internet['unchanged_transport_inputs'].items():
    assert sha((REPO / name).read_bytes()) == digest, name

summary = {
    'generated_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'base_commit': BASE, 'source_head': FINAL, 'source_tree': patch['result_tree'],
    'previous_complete_integration_head': PREVIOUS,
    'passed': True,
    'meaning': 'Required host proofs for this exact prepared patch series passed. This is not an installed product, physical-device, real-server, or month-long acceptance.',
    'patch_series': {'parts': 9, 'manifest': ref('final-patches/manifest.json'),
                     'combined_and_individual_series_produce_identical_tested_tree': True},
    'fresh_final_source_checks': [
        {'name': 'C# clean rebuild and focused regression groups', 'groups_passed': 17,
         'filters': 14, 'rebuild_executed': True, 'restore_locked': True,
         'assembly_sha256': tail['assembly_sha256'],
         'proof': ref('validation/final-csharp-tail/manifest.json')},
        {'name': 'Codec to both frontends to actual stored book to reopen/export/reimport',
         'cases_passed': 48, 'same_fresh_assembly': True,
         'proof': ref('import-export/final-tail-pipeline/pipeline-manifest.json')}
    ],
    'reused_unchanged_python_ui_results': {
        'executed_on': PREVIOUS, 'bound_to': FINAL,
        'method': 'Every selected source input, generated UI asset and result log retains its exact hash; only two C# files changed after the complete integration. C# and storage pipeline were rebuilt/rerun separately.',
        'python_restore_csv_tests_passed': 155,
        'python_import_export_semantic_tests_passed': 286,
        'direct_file_contract_checks_passed': 26,
        'javascript_programs_passed': 15, 'javascript_programs': ui_programs,
        'additional_passed': ['Independent worker ownership check', 'Actual Mac/tablet timezone projection adapters'],
        'binding_manifest': ref('validation/final-csharp-tail/manifest.json'),
        'original_integration': ref('integration-final-current/manifest.json'),
        'old_csharp_results_relabelled_as_fresh': False
    },
    'separate_source_bound_evidence': {
        'later_issue_846_mcp_path': {
            'proof': ref('new-issues/846-followup.json'),
            'execution': ref('new-issues/846/execution-manifest.json'),
            'outcome': 'The unchanged MCP program fails on the frozen base and passes with this series for both canonical desktop web sources under Node/JSDOM.',
            'boundary': 'Later upstream f8ad956e overlaps only this alias/color part. No own Bun or complete Windows archive CI acceptance; patch base remains7a.'},
        'internet_complete_protocol_group': {
            'groups_passed': 1, 'executed_on': internet['previous_head'],
            'unchanged_transport_inputs_count': len(internet['unchanged_transport_inputs']),
            'proof': ref(internet['path']),
            'boundary': 'Controlled protocol tests; no real router, mobile carrier, or physical Android background-delivery acceptance.'},
        'media_formats_mirroring_webcam': {
            'host_tests_passed': 111,
            'proof': ref('media/formats-mirror-webcam-tests-manifest.json'),
            'bounded_upstream_review': ref('media/upstream-bc9b4db5-review.json'),
            'boundary': 'Earlier host run retained at its recorded source; no native webcam target-application or physical-phone acceptance.'},
        'color_followup_independent_review': ref('import-export/after-7a490dd8-844/independent-review.json'),
        'birthday_followup_independent_review': ref('providers/nextcloud-caldav-evidence/issue-845/upstream-remainder/independent-review.json'),
        'birthday_detached_guard_independent_review': ref('providers/nextcloud-caldav-evidence/issue-845/upstream-remainder/independent-normal-detached-fix-review.json')
    },
    'counting_boundary': 'The suites overlap. These figures are not summed into a unique test total. A C# group can contain many assertions and is not counted as one individual fixture.',
    'not_claimed': [
        'Installed Windows/macOS/Linux/Android product acceptance',
        'Complete real Nextcloud rights/conflict/offline/restart matrix',
        'Internet reachability in both directions behind real routers/mobile networks',
        'Physical phone camera, screen, microphone or target-application compatibility',
        'Android Robolectric execution without its full SDK environment',
        'Named-pipe cleanup test that remained blocked in this host',
        '250,000-record performance rerun after all fixes or 30-day native tray soak',
        'Public release packages or merging the product patches into main'
    ],
    'source_worktree_clean': True
}
(ROOT / 'final-integration-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'passed': True, 'head': FINAL, 'parts': 9, 'fresh_csharp_groups': 17, 'fresh_storage_cases': 48, 'reused_python': [155, 286], 'reused_contract_checks': 26, 'reused_ui_programs': 15}))
