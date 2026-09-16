#!/usr/bin/env python3
"""Audit/package recorded Notes builds; compilation requires --build-production.

No installation, approval or publication. Never correct source in staging.
"""
import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import zipfile
import xml.etree.ElementTree as ET

from package_preflight import android_sdk, executable
from release_gate import checksums, regular, require, release_versions, json_read, write_record, input_bytes, release_lock
from release_sources import digest, source_identity, source_files, inventory_digest
from source_selection import PRIVATE_KEY, SECRET, private_path

BUILD_ARGS = ['--offline', '--dependency-verification', 'strict', '--no-daemon', '--no-build-cache', '--rerun-tasks',
              ':app:testReleaseUnitTest', ':app:assembleRelease']


def projection(root):
    sources = list(root.glob('magnolie-notes-*/app/build.gradle.kts'))
    require(len(sources) == 1, 'Exactly one Notes source required')
    source = sources[0].parents[1]
    files = {relative.as_posix(): path for relative, path in source_files(source)}
    contracts = {'contracts/' + relative.as_posix(): path for relative, path in source_files(root / 'contracts')}
    require(contracts and not set(files).intersection(contracts), 'Missing or ambiguous Notes contracts projection')
    files.update(contracts)
    return source, files, {name: source_identity(path) for name, path in files.items()}


def test_results(reports):
    require(isinstance(reports, dict) and reports, 'Release unit test reports required')
    for name, text in reports.items():
        require(re.fullmatch(r'TEST-[A-Za-z0-9_.$-]+\.xml', name) is not None,
                'Invalid release test report name')
        suite = ET.fromstring(text)
        cases = suite.findall('testcase')
        require(suite.tag == 'testsuite' and cases and
                int(suite.get('tests', '-1')) == len(cases) and
                all(int(suite.get(key, '-1')) == 0 for key in ('failures', 'errors', 'skipped')) and
                all(not list(case) or all(child.tag in {'system-out', 'system-err'} for child in case) for case in cases),
                'Release unit tests empty, failed or skipped')


def build_production(root, gradle, sdk, version, code, aapt, signer, certificate):
    """Trusted canonical runner, not an importer of retrospective build claims."""
    require(re.fullmatch(r'[0-9a-fA-F]{64}', certificate or '') is not None,
            'Expected production certificate SHA256 required before build')
    source, _, before = projection(root)
    gradle = regular(gradle).resolve()
    tools = {name: digest(regular(path)) for name, path in
             [('gradle', gradle), ('aapt', aapt), ('apksigner', signer)]}
    env = dict(os.environ, ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    toolchain = subprocess.check_output([str(gradle), '--version'], cwd=source, env=env, text=True)
    apk = source / 'app/build/outputs/apk/release/app-release.apk'
    reports_dir = source / 'app/build/test-results/testReleaseUnitTest'
    subprocess.run([str(gradle), '--no-daemon', 'clean'], cwd=source, env=env, check=True)
    require(not apk.exists() and not reports_dir.exists(), 'Clean did not remove old Notes outputs')
    subprocess.run([str(gradle), *BUILD_ARGS], cwd=source, env=env, check=True)
    reports = {path.name: input_bytes(path).decode('utf-8') for path in sorted(reports_dir.glob('TEST-*.xml'))}
    test_results(reports)
    # Retain executed case identities/counts, never environment properties or test stdout.
    for name, text in reports.items():
        suite = ET.fromstring(text)
        public = ET.Element('testsuite', {key: suite.get(key) for key in ('tests', 'failures', 'errors', 'skipped')})
        for case in suite.findall('testcase'):
            ET.SubElement(public, 'testcase', {key: case.get(key, '') for key in ('name', 'classname')})
        reports[name] = ET.tostring(public, encoding='unicode')
    identity = audit(apk, version, code, aapt, signer, certificate)
    require(projection(root)[2] == before, 'Canonical Notes inputs changed during build')
    require(tools == {name: digest(regular(path)) for name, path in
                     [('gradle', gradle), ('aapt', aapt), ('apksigner', signer)]}, 'Build tools changed')
    return apk, dict(schema='magnolie-notes-build-v1', version=version, versionCode=code,
                     sources=before, sourceSha256=inventory_digest(before), apkSha256=identity['sha256'],
                     certificateSha256=certificate.lower(), command=BUILD_ARGS, cleanExitCode=0,
                     buildExitCode=0, tools=tools, toolchain=toolchain, reports=reports)


def binding(root, directory, version, aapt=None, signer=None, certificate=None):
    source, _, expected = projection(root)
    code = int(re.search(r'versionCode\s*=\s*(\d+)', (source / 'app/build.gradle.kts').read_text()).group(1))
    record = json_read(directory / f'Magnolie-Notes-{version}-provenance.json')
    require(set(record) == {'schema', 'version', 'versionCode', 'sources', 'sourceSha256', 'apkSha256',
                           'certificateSha256', 'command', 'cleanExitCode', 'buildExitCode', 'tools',
                           'toolchain', 'reports'} and record['schema'] == 'magnolie-notes-build-v1',
            'Notes build provenance required')
    require(record['version'] == version and type(record['versionCode']) is int and record['versionCode'] == code and
            record['sources'] == expected and record['sourceSha256'] == inventory_digest(expected),
            'Notes build source binding differs from frozen canonical projection')
    require(record['command'] == BUILD_ARGS and
            all(type(record[key]) is int and record[key] == 0 for key in ('cleanExitCode', 'buildExitCode')) and
            set(record['tools']) == {'gradle', 'aapt', 'apksigner'} and
            all(re.fullmatch('[0-9a-f]{64}', value) for value in record['tools'].values()) and
            isinstance(record['toolchain'], str) and record['toolchain'].strip(), 'Invalid Notes build execution record')
    test_results(record['reports'])
    archive = regular(directory / f'magnolie-notes_{version}.tar.xz')
    archive_hash = digest(archive)
    actual = {}
    with tarfile.open(archive, 'r:xz') as stream:
        prefix = f'magnolie-notes-{version}/'
        for entry in stream:
            require(entry.isfile() and entry.name.startswith(prefix), 'Non-file or unsafe Notes archive member')
            name = entry.name[len(prefix):]
            require(name in expected and name not in actual and entry.size <= 64 * 1024 * 1024,
                    'Unexpected, duplicate or oversized Notes archive member')
            actual[name] = dict(sha256=hashlib.sha256(stream.extractfile(entry).read()).hexdigest(), mode=entry.mode)
    require(actual == expected and digest(archive) == archive_hash, 'Notes archive projection differs from frozen source')
    if aapt is None or signer is None:
        sdk = android_sdk(None)
        require(sdk is not None, 'Android SDK required for Notes provenance verification')
        aapt = executable(*reversed(sorted((sdk / 'build-tools').glob('*/aapt'))))
        signer = executable(*reversed(sorted((sdk / 'build-tools').glob('*/apksigner'))))
    require(aapt and signer, 'aapt and apksigner required')
    certificate = certificate or os.environ.get('MAGNOLIE_RELEASE_CERT_SHA256')
    require(certificate and record['certificateSha256'] == certificate.lower(), 'Notes certificate differs from external production pin')
    identity = audit(directory / f'Magnolie-Notes-{version}.apk', version, code, aapt, signer, certificate)
    require(identity['sha256'] == record['apkSha256'], 'Notes APK differs from recorded build output')
    require(projection(root)[2] == expected, 'Notes source changed during provenance verification')


def dex_classes(data):
    require(data.startswith(b"dex\n") and len(data) >= 112, "Invalid production DEX")
    strings, types, count, definitions = (struct.unpack_from('<I', data, offset)[0] for offset in (60, 68, 96, 100))
    for index in range(count):
        cls = struct.unpack_from('<I', data, definitions + 32 * index)[0]
        text = struct.unpack_from('<I', data, types + 4 * cls)[0]
        offset = struct.unpack_from('<I', data, strings + 4 * text)[0]
        while data[offset] & 128:
            offset += 1
        offset += 1
        yield data[offset:data.index(b'\0', offset)].decode('utf-8')


def audit(apk, version, code, aapt, apksigner, certificate):
    regular(apk)
    require(re.fullmatch(r'[0-9a-fA-F]{64}', certificate or '') is not None, "Expected production certificate SHA256 required")
    before = source_identity(apk)
    badging = subprocess.check_output([aapt, 'dump', 'badging', str(apk)], text=True)
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging, re.M)
    require(package is not None and package.groups() == ('io.gitlab.maik3531.magnolienotes', str(code), version),
            "APK package/version differs from current production source")
    require('application-debuggable' not in badging, "Debuggable APK is not production")
    manifest = subprocess.check_output([aapt, 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'], text=True)
    flags = re.findall(r'android:(?:testOnly|debuggable)[^\n]*\)\s*(0x[0-9a-fA-F]+)', manifest)
    require(not any(int(value, 16) for value in flags), "Test/debug APK is not production")
    require(not re.search(r'^\s*E: instrumentation\b', manifest, re.M), "Instrumentation manifest is not production")
    aliases = list(re.finditer(r'^([ \t]*)E: activity-alias\b[^\n]*\n', manifest, re.M))
    require(len(aliases) <= 1, "Unexpected production activity aliases")
    for alias in aliases:
        lines = []
        for line in manifest[alias.end():].splitlines():
            if line.strip() and len(line) - len(line.lstrip()) <= len(alias[1]):
                break
            lines.append(line)
        block = '\n'.join(lines)
        names = re.findall(r'android:name\([^\n]*?="([^"]+)"', block)
        targets = re.findall(r'android:targetActivity\([^\n]*?="([^"]+)"', block)
        exported = re.findall(r'android:exported\([^\n]*?=\(type 0x12\)(0x[0-9a-fA-F]+)', block)
        package = 'io.gitlab.maik3531.magnolienotes'
        require(len(names) == len(targets) == len(exported) == 1 and
                names[0] in {'.MainActivityCustom', package + '.MainActivityCustom'} and
                targets[0] in {'.MainActivity', package + '.MainActivity'} and int(exported[0], 16) == 0 and
                not re.search(r'^\s*E:', block, re.M),
                "Only the non-exported internal Custom alias is permitted in production")
    certificates = subprocess.check_output([apksigner, 'verify', '--print-certs', str(apk)], text=True)
    fingerprints = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)$', certificates, re.M)
    require([value.lower() for value in fingerprints] == [certificate.lower()], "Unexpected production signing certificate")
    require('Android Debug' not in certificates, "Android debug signing certificate rejected")
    with zipfile.ZipFile(apk) as archive:
        require(sum(entry.file_size for entry in archive.infolist()) <= 512 * 1024 * 1024, "APK exceeds payload audit bound")
        names = set()
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            require(entry.filename not in names and not path.is_absolute() and '..' not in path.parts and '\\' not in entry.filename,
                    "Unsafe or duplicate APK path")
            names.add(entry.filename)
            require(not private_path(path) and not SECRET.search(path.name) and
                    not any(part in {'tests', 'pruefungen', 'fixtures', 'contracts', 'validation'} for part in path.parts),
                    "Private/test material in APK")
            require(not stat.S_ISLNK(entry.external_attr >> 16), "APK symlink rejected")
            data = archive.read(entry)
            require(PRIVATE_KEY.search(data) is None, "Plaintext private key marker in APK payload")
            if re.fullmatch(r'classes\d*\.dex', entry.filename):
                require(entry.file_size <= 256 * 1024 * 1024, "DEX exceeds audit bound")
                for cls in dex_classes(data):
                    if cls.startswith('Lio/gitlab/maik3531/magnolienotes/'):
                        require('/validation/' not in cls and not re.search(r'/(?:Validation\w*|MagnolieTestRunner|\w+Test)(?:\$|;)', cls),
                                "Validation/instrumentation class defined in production APK")
        require('classes.dex' in names, 'Production APK must contain classes.dex')
    require(source_identity(apk) == before, "APK changed during production audit")
    return before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--apk', type=Path)
    parser.add_argument('--build-record', type=Path, help='Required for packaging an existing APK')
    parser.add_argument('--build-production', action='store_true', help='Explicitly run canonical release compilation/signing and unit tests')
    parser.add_argument('--gradle', type=Path, help='Trusted Gradle executable for --build-production')
    parser.add_argument('--android-sdk', type=Path)
    parser.add_argument('--certificate-sha256', default=os.environ.get('MAGNOLIE_RELEASE_CERT_SHA256'))
    parser.add_argument('--destination', type=Path, help='NEW directory outside canonical root; omit for read-only APK audit')
    args = parser.parse_args()
    root = args.root.resolve()
    _, version = release_versions(root)
    source = next(root.glob('magnolie-notes-*/app/build.gradle.kts')).parents[1]
    code = int(re.search(r'versionCode\s*=\s*(\d+)', (source / 'app/build.gradle.kts').read_text()).group(1))
    sdk = android_sdk(args.android_sdk)
    require(sdk is not None, "Android SDK required")
    aapt = executable(*reversed(sorted((sdk / 'build-tools').glob('*/aapt'))))
    signer = executable(*reversed(sorted((sdk / 'build-tools').glob('*/apksigner'))))
    require(aapt and signer, "aapt and apksigner required")
    if args.build_production:
        require(args.destination and args.gradle and not args.apk and not args.build_record,
                'Production build requires new destination and Gradle, not supplied APK/record')
    else:
        require(args.apk is not None, 'APK required for read-only audit or recorded packaging')
        require(not args.destination or args.build_record, 'Packaging requires an executed Notes build record')
    if args.destination:
        destination = args.destination.absolute()
        require(not destination.resolve().is_relative_to(root), 'Private Notes output must be outside canonical source')
        require(destination.parent.resolve() == destination.parent and destination.parent.is_dir() and
                not destination.exists() and not destination.is_symlink(), 'New private destination required')
    if args.build_production:
        with release_lock(root):
            args.apk, build_record = build_production(root, args.gradle, sdk, version, code, aapt, signer, args.certificate_sha256)
    elif args.destination:
        build_record = json_read(args.build_record)
    identity = audit(args.apk, version, code, aapt, signer, args.certificate_sha256)
    if not args.destination:
        print('Production APK metadata, signing certificate and payload paths verified; native acceptance remains separate.')
        return
    _, files, identities = projection(root)
    require(build_record['sources'] == identities and build_record['apkSha256'] == identity['sha256'],
            'Supplied APK/source differs from executed build record')
    destination.mkdir(mode=0o700)
    try:
        apk = destination / ('Magnolie-Notes-' + version + '.apk')
        shutil.copyfile(args.apk, apk)
        require(digest(apk) == identity['sha256'], 'APK changed before private staging')
        archive = destination / ('magnolie-notes_' + version + '.tar.xz')
        with tarfile.open(archive, 'w:xz') as output:
            for name, path in sorted(files.items()):
                data = path.read_bytes()
                require(hashlib.sha256(data).hexdigest() == identities[name]['sha256'] and
                        source_identity(path) == identities[name], 'Canonical Notes source changed during archiving')
                entry = tarfile.TarInfo('magnolie-notes-' + version + '/' + name)
                entry.size = len(data)
                entry.mode = identities[name]['mode']
                entry.mtime = 0
                output.addfile(entry, io.BytesIO(data))
        current = {relative.as_posix(): path for relative, path in source_files(source)}
        current.update({'contracts/' + relative.as_posix(): path for relative, path in source_files(root / 'contracts')})
        require({name: source_identity(path) for name, path in current.items()} == identities, 'Notes source inventory changed')
        record_name = f'Magnolie-Notes-{version}-provenance.json'
        write_record(destination / record_name, build_record)
        binding(root, destination, version, aapt, signer, args.certificate_sha256)
        checksums(destination, 'Magnolie-Notes-PRUEFSUMMEN.sha256', [apk.name, archive.name, record_name])
    except BaseException:
        shutil.rmtree(destination)
        raise
    print('Private Notes input prepared: ' + str(destination) + '; no native/user approval implied.')


if __name__ == '__main__':
    main()
