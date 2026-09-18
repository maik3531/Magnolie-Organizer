"""Synthetic provenance faults only. No product build, keys or approval."""
import io
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

from test_release_packaging import candidate, write
import notes_candidate as notes
import release_gate as gate
import release_sources as sources


@pytest.mark.parametrize('boundary', ['seal', 'inspect'])
@pytest.mark.parametrize('damage', ['missing-record', 'source', 'apk', 'archive-content', 'archive-mode',
    'archive-extra', 'archive-link', 'archive-duplicate', 'archive-missing', 'certificate', 'version',
    'debuggable', 'testOnly', 'failed-test', 'skipped-test', 'empty-tests', 'command', 'failed-build', 'pin'])
def test_final_boundaries_reject_internally_rehashed_notes(candidate, monkeypatch, boundary, damage):
    root, directory, _, _ = candidate
    record_path = directory / 'Magnolie-Notes-1.0.14-provenance.json'
    record = gate.json_read(record_path)
    if damage == 'source':
        record['sources']['app/build.gradle.kts']['sha256'] = '0' * 64
        record['sourceSha256'] = sources.inventory_digest(record['sources'])
    elif damage == 'apk':
        with zipfile.ZipFile(directory / 'Magnolie-Notes-1.0.14.apk', 'a') as archive:
            archive.writestr('assets/stale.txt', b'stale APK with unchanged version')
    elif damage.startswith('archive-'):
        path = directory / 'magnolie-notes_1.0.14.tar.xz'
        with tarfile.open(path) as archive:
            entries = [(entry, archive.extractfile(entry).read()) for entry in archive]
        entry, data = entries[0]
        if damage == 'archive-content':
            entries[0] = entry, b'x' * len(data)
        elif damage == 'archive-mode':
            entry.mode ^= 0o111
        elif damage == 'archive-extra':
            extra = tarfile.TarInfo('magnolie-notes-1.0.14/../extra')
            entries.append((extra, b''))
        elif damage == 'archive-link':
            entry.type, entry.linkname, entry.size = tarfile.SYMTYPE, '/outside', 0
        elif damage == 'archive-duplicate':
            entries.append(entries[0])
        else:
            entries.pop()
        with tarfile.open(path, 'w:xz') as archive:
            for entry, data in entries:
                archive.addfile(entry, io.BytesIO(data))
    elif damage in {'certificate', 'version', 'debuggable', 'testOnly'}:
        output = notes.subprocess.check_output
        def damaged(command, **kwargs):
            text = output(command, **kwargs)
            if damage == 'certificate':
                return text.replace('a' * 64, 'c' * 64)
            if damage == 'version':
                return text.replace("versionCode='14'", "versionCode='13'")
            if command[1:3] == ['dump', 'xmltree']:
                return f'A: android:{damage}(0x01010000)=(type 0x12)0xffffffff'
            return text
        monkeypatch.setattr(notes.subprocess, 'check_output', damaged)
    elif damage in {'failed-test', 'skipped-test', 'empty-tests'}:
        record['reports'] = {} if damage == 'empty-tests' else {'TEST-Synthetic.xml':
            '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase><' +
            ('failure' if damage == 'failed-test' else 'skipped') + '/></testcase></testsuite>'}
    elif damage == 'command':
        record['command'] = [':app:assembleDebug']
    elif damage == 'failed-build':
        record['buildExitCode'] = 1
    elif damage == 'pin':
        monkeypatch.delenv('MAGNOLIE_RELEASE_CERT_SHA256')
    write(record_path, record)
    names = gate.artifact_groups('9.8.7', '1.0.14', 'amd64')['notes']
    gate.checksums(directory, names[2], names[:2] + names[3:])
    aggregate = gate.json_read(directory / 'candidate.json')
    aggregate['artifacts'] = gate.artifact_map(directory, aggregate['artifacts'])
    write(directory / 'candidate.json', aggregate)
    if damage == 'missing-record':
        record_path.unlink()
    if boundary == 'inspect':
        with pytest.raises(ValueError):
            gate.candidate_check(root, directory)
    else:
        (directory / 'candidate.json').unlink()
        frozen = directory / 'synthetic-source-record.json'
        write(frozen, sources.inventory(root))
        monkeypatch.setattr(sys, 'argv', ['release_gate.py', 'seal', '--root', str(root),
            '--candidate', str(directory), '--source-record', str(frozen), '--autopkgtest', 'passed'])
        with pytest.raises(ValueError):
            gate.main()
        assert not (directory / 'candidate.json').exists()


@pytest.mark.parametrize('damage', [None, 'source-drift', 'added-source', 'mode-drift', 'failed-build',
                                  'stale-output', 'no-tests', 'skipped-tests'])
def test_canonical_runner_measures_inputs_and_owns_fresh_output(tmp_path, monkeypatch, damage):
    root = tmp_path / 'canonical'
    source = root / 'magnolie-notes'
    write(source / 'app/build.gradle.kts', 'versionCode = 14\nversionName = "1.0.14"')
    write(root / 'contracts/synthetic.json', '{}')
    tool = tmp_path / 'synthetic-gradle'
    write(tool, 'SYNTHETIC TOOL, NEVER EXECUTED')
    apk = source / 'app/build/outputs/apk/release/app-release.apk'
    report = source / 'app/build/test-results/testReleaseUnitTest/TEST-Synthetic.xml'
    write(apk, 'stale output')
    calls = []
    def run(command, **kwargs):
        assert kwargs['cwd'] == source and kwargs['check'] is True
        calls.append(command[1:])
        if command[-1] == 'clean':
            if damage != 'stale-output':
                shutil.rmtree(source / 'app/build')
            return
        if damage == 'failed-build':
            raise subprocess.CalledProcessError(1, command)
        write(apk, 'fresh synthetic output')
        if damage != 'no-tests':
            write(report, '<testsuite tests="1" failures="0" errors="0" skipped="' +
                ('1' if damage == 'skipped-tests' else '0') + '"><testcase name="synthetic"/></testsuite>')
        if damage == 'source-drift':
            write(source / 'app/build.gradle.kts', 'changed')
        elif damage == 'added-source':
            write(source / 'new.kt', 'changed')
        elif damage == 'mode-drift':
            (source / 'app/build.gradle.kts').chmod(0o755)
    monkeypatch.setattr(notes.subprocess, 'run', run)
    monkeypatch.setattr(notes.subprocess, 'check_output', lambda *_args, **_kwargs: 'SYNTHETIC Gradle/JVM')
    monkeypatch.setattr(notes, 'audit', lambda path, *_: sources.source_identity(path))
    if damage:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            notes.build_production(root, tool, tmp_path, '1.0.14', 14, tool, tool, 'a' * 64)
    else:
        output, record = notes.build_production(root, tool, tmp_path, '1.0.14', 14, tool, tool, 'a' * 64)
        assert output == apk and record['apkSha256'] == sources.digest(apk)
        assert record['sources'] == notes.projection(root)[2]
        assert calls == [['--no-daemon', 'clean'], notes.BUILD_ARGS]
        assert not set(record).intersection({'nativeEvidence', 'userAcceptance', 'accepted'})


def test_packaging_bare_apk_cannot_manufacture_record(candidate, monkeypatch, tmp_path):
    root, directory, _, _ = candidate
    destination = tmp_path / 'new-private-input'
    monkeypatch.setattr(sys, 'argv', ['notes_candidate.py', '--root', str(root), '--apk',
        str(directory / 'Magnolie-Notes-1.0.14.apk'), '--destination', str(destination)])
    with pytest.raises(ValueError, match='executed Notes build record'):
        notes.main()
    assert not destination.exists()


def test_recorded_packaging_preserves_binding_without_approval(candidate, monkeypatch, tmp_path):
    root, directory, _, _ = candidate
    destination = tmp_path / 'repackaged'
    original = notes.subprocess.check_output
    def output(command, **kwargs):
        command = [part.replace(str(destination), str(directory)) for part in command]
        return original(command, **kwargs)
    monkeypatch.setattr(notes.subprocess, 'check_output', output)
    monkeypatch.setattr(sys, 'argv', ['notes_candidate.py', '--root', str(root), '--apk',
        str(directory / 'Magnolie-Notes-1.0.14.apk'), '--build-record',
        str(directory / 'Magnolie-Notes-1.0.14-provenance.json'), '--destination', str(destination)])
    notes.main()
    names = gate.notes_inputs(root, destination)
    assert set(path.name for path in destination.iterdir()) == set(names)
    assert sources.digest(destination / names[0]) == sources.digest(directory / names[0])
    assert gate.json_read(destination / names[3]) == gate.json_read(directory / names[3])
    assert destination.stat().st_mode & 0o777 == 0o700


def test_notes_recheck_rejects_drift_during_apk_audit(candidate, monkeypatch):
    root, directory, _, _ = candidate
    original = notes.audit
    def mutate(*args):
        result = original(*args)
        write(directory / 'Magnolie-Notes-1.0.14-provenance.json', {'changed': True})
        return result
    monkeypatch.setattr(notes, 'audit', mutate)
    with pytest.raises(ValueError, match='changed during provenance'):
        gate.notes_inputs(root, directory)


def test_certificate_required_before_any_build_process(tmp_path, monkeypatch):
    monkeypatch.setattr(notes.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('Build invoked'))
    monkeypatch.setattr(notes.subprocess, 'check_output', lambda *_args, **_kwargs: pytest.fail('Tool invoked'))
    with pytest.raises(ValueError, match='certificate'):
        notes.build_production(tmp_path, tmp_path, tmp_path, '1.0.14', 14, 'aapt', 'signer', None)


@pytest.mark.parametrize('damage', [None, 'exported', 'missing-exported', 'validation-alias', 'wrong-target',
                                  'filter', 'duplicate', 'instrumentation'])
def test_production_audit_accepts_only_the_current_internal_custom_alias(candidate, monkeypatch, damage):
    _, directory, _, _ = candidate
    block = ('    E: activity-alias (line=90)\n'
             '      A: android:name(0x01010003)=".MainActivityCustom"\n'
             '      A: android:targetActivity(0x01010202)=".MainActivity"\n'
             '      A: android:exported(0x01010010)=(type 0x12)0x0\n')
    if damage == 'exported': block = block.replace('0x12)0x0', '0x12)0xffffffff')
    elif damage == 'missing-exported': block = '\n'.join(line for line in block.splitlines() if 'android:exported' not in line) + '\n'
    elif damage == 'validation-alias': block = block.replace('MainActivityCustom', 'MainActivityValidation')
    elif damage == 'wrong-target': block = block.replace('=".MainActivity"', '=".ValidationActivity"')
    elif damage == 'filter': block += '      E: intent-filter (line=94)\n'
    elif damage == 'duplicate': block *= 2
    elif damage == 'instrumentation': block += '  E: instrumentation (line=95)\n'
    original = notes.subprocess.check_output
    def output(command, **kwargs):
        return 'E: manifest\n  E: application\n' + block if command[1:3] == ['dump', 'xmltree'] else original(command, **kwargs)
    monkeypatch.setattr(notes.subprocess, 'check_output', output)
    command = (directory / 'Magnolie-Notes-1.0.14.apk', '1.0.14', 14, 'synthetic-aapt', 'synthetic-signer', 'a' * 64)
    if damage:
        with pytest.raises(ValueError, match='alias|Alias|Instrumentation'):
            notes.audit(*command)
    else:
        assert notes.audit(*command)['sha256'] == sources.digest(command[0])
