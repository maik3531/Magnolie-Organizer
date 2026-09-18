// Evaluate the actual Settings list expressions without starting either application.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const files = [path.join(__dirname, '../app/web/anwendung.js')];
const linuxRoot = process.env.MAGNOLIE_LINUX_SOURCE || path.join(__dirname, '../../magnolie-organizer');
if (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linuxRoot)) {
  files.push(path.join(linuxRoot, 'web/anwendung.js'));
}
for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  const peers = source.match(/const telefone = (\(telefonStand\.peers[\s\S]*?);/)[1];
  const devices = source.match(/const btGeraete = (\(telefonStand\.bluetooth[\s\S]*?);/)[1];
  const phoneList = new Function('telefonStand', `return ${peers};`);
  const bluetoothList = new Function('telefonStand', `return ${devices};`);
  assert.deepEqual(phoneList({ peers: [
    { device_id: 'trusted-a', display_name: 'Friendly phone' },
    { device_id: 'trusted-a', display_name: 'Product model' },
    { device_id: 'trusted-b', display_name: 'Friendly phone' }
  ] }).map(p => p.device_id), ['trusted-a', 'trusted-b']);
  assert.deepEqual(bluetoothList({ bluetooth: { devices: [
    { address: 'AA:BB:CC:DD:EE:01', name: 'Friendly phone' },
    { address: 'aa:bb:cc:dd:ee:01', name: 'Product model' },
    { address: 'AA:BB:CC:DD:EE:02', name: 'Friendly phone' }
  ] } }).map(p => p.address), ['AA:BB:CC:DD:EE:01', 'AA:BB:CC:DD:EE:02']);
  assert.equal(phoneList({ peers: [{ display_name: 'Unknown' }, { display_name: 'Unknown' }] }).length, 2);
}
console.log(`Phone Settings: identity deduplication passed for ${files.length} source tree(s)`);
