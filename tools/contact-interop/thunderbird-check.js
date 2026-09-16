const fs = require('node:fs');
const path = require('node:path');
const {spawn, spawnSync} = require('node:child_process');
const assert = require('node:assert/strict');

async function run(cards) {
  const root = process.env.CONTACT_INTEROP_HOME;
  assert.ok(root?.startsWith('/tmp/opencode/'));
  assert.equal(process.env.CONTACT_INTEROP_SANDBOX, '1', 'Use the private test sandbox');
  const binary = path.join(root, 'thunderbird/thunderbird');
  assert.ok(fs.existsSync(binary), 'Prepare the pinned Thunderbird test copy with thunderbird.py first');
  const profile = fs.mkdtempSync(path.join(root, 'thunderbird-profile-'));
  const output = path.join(root, 'thunderbird-output.json');
  const results = {};
  fs.mkdirSync('/tmp/.X11-unix', {recursive: true, mode: 0o1777});
  const software = {...process.env, LIBGL_ALWAYS_SOFTWARE: '1', NO_AT_BRIDGE: '1', GIO_USE_VFS: 'local',
    __EGL_VENDOR_LIBRARY_FILENAMES: '/usr/share/glvnd/egl_vendor.d/50_mesa.json'};
  delete software.MOZ_HEADLESS;
  delete software.GTK_USE_PORTAL;
  const display = spawn('bwrap', ['--die-with-parent', '--unshare-user', '--uid', '0', '--gid', '0', '--ro-bind', '/', '/',
    '--bind', '/tmp', '/tmp', '--bind', root, root,
    '--ro-bind', path.join(__dirname, 'xkb-rules'), '/usr/share/X11/xkb/rules/evdev',
    '--ro-bind', path.join(__dirname, 'xkb-rules'), '/usr/share/X11/xkb/rules/base',
    'Xvfb', '-displayfd', '1', '-screen', '0', '1280x800x24', '-nolisten', 'tcp', '-noreset', '-nolock'],
    {env: software, detached: true, stdio: ['ignore', 'pipe', 'inherit']});
  try {
  const displayNumber = await new Promise((resolve, reject) => {
    display.stdout.once('data', data => resolve(data.toString().trim()));
    display.once('error', reject);
    display.once('exit', code => reject(new Error('Xvfb exited: ' + code)));
  });
  for (const phase of ['baseline', 'import', 'reload']) {
    fs.writeFileSync(path.join(root, 'thunderbird-input.json'), JSON.stringify({phase, cards}));
    fs.rmSync(output, {force: true});
    const child = spawnSync('dbus-run-session', ['--config-file=' + path.join(__dirname, 'dbus-session.conf'),
      '--', binary, '-no-remote', '-profile', profile, '-mail'], {
      env: {...software, DISPLAY: ':' + displayNumber, MOZ_CRASHREPORTER_DISABLE: '1', MOZ_DBUS_REMOTE: '0'},
      encoding: 'utf8', timeout: 90000,
    });
    fs.writeFileSync(path.join(root, 'thunderbird-' + phase + '.log'), (child.stdout || '') + (child.stderr || ''));
    if (child.stdout) process.stdout.write(child.stdout);
    if (child.stderr) process.stderr.write(child.stderr);
    assert.equal(child.status, 0, 'Thunderbird ' + phase + ': ' + (child.error || child.signal || child.stderr));
    assert.ok(fs.existsSync(output), 'Thunderbird did not finish its contact gate');
    results[phase] = JSON.parse(fs.readFileSync(output, 'utf8'));
    assert.ok(!results[phase].error, JSON.stringify(results[phase]));
    assert.equal(results[phase].version, '140.8.0');
    const diagnostics = (child.stdout || '').split('\n').filter(line => line.startsWith('CONTACT_GATE_DIAGNOSTIC '))
      .map(line => JSON.parse(line.slice('CONTACT_GATE_DIAGNOSTIC '.length)));
    assert.ok((child.stdout || '').split('\n').filter(Boolean).every(line => line.startsWith('CONTACT_GATE_DIAGNOSTIC ')),
      'Unexpected Thunderbird standard output');
    assert.ok(diagnostics.length <= 1, 'Additional Thunderbird diagnostics');
    // ESR 140.8.0 emits this even when closing an empty fixture. Never excuse a
    // parsing/storage diagnostic, additional warning, or a changed shutdown error.
    for (const diagnostic of diagnostics) assert.deepEqual(diagnostic, {stage: 'shutdown',
      message: 'uncaught exception: undefined', source: '', line: 0, category: 'chrome javascript', stack: 'undefined'});
    assert.equal((child.stderr || '').trim(), diagnostics.length ? 'JavaScript error: , line 0: uncaught exception: undefined' : '');
    if (phase === 'baseline') {
      assert.equal(results[phase].saved.length, 0, 'The control profile must contain no contacts');
      results.baseline.diagnostics = diagnostics;
    } else assert.deepEqual(diagnostics, results.baseline.diagnostics, 'No diagnostics beyond the empty-profile control');
  }
  fs.writeFileSync(path.join(root, 'thunderbird-evidence.json'), JSON.stringify(results, null, 2));
  console.log('Thunderbird: empty-profile control, native import, and process reload completed; no additional diagnostics.');
  return results;
  } finally {
    try { process.kill(-display.pid, 'SIGTERM'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
  }
}

module.exports = {run};
if (require.main === module) {
  run([{text: 'BEGIN:VCARD\r\nVERSION:4.0\r\nUID;VALUE=text:synthetic-bootstrap\r\nN:Van Dame;;;;\r\nFN:Club contact\r\nBDAY:--0229\r\nANNIVERSARY:--0607\r\nEND:VCARD\r\n'}]).then(result => {
    assert.deepEqual(result.import.imported[0].birthday, ['', '2', '29']);
    assert.deepEqual(result.reload.saved[0].anniversary, ['', '6', '7']);
    console.log('PASS native Thunderbird import, SQLite save and process restart');
  }).catch(error => { console.error(error); process.exitCode = 1; });
}
