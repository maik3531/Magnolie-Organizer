const fs = require('fs');
const crypto = require('crypto');
const assert = require('assert/strict');
const path = require('path');
const outer = path.join(__dirname, '../../contracts/baum-1-receipt-v1-vectors.json');
const v = JSON.parse(fs.readFileSync(fs.existsSync(outer) ? outer : path.join(__dirname, '../contracts/baum-1-receipt-v1-vectors.json')));
const canonical = x => JSON.stringify(Object.fromEntries(Object.keys(x).sort().map(k => [k, x[k]])));
assert.equal(canonical(v.envelope), v.canonicalEnvelope);
assert.equal(crypto.createHash('sha256').update(v.canonicalEnvelope).digest('hex'), v.receipt.envelopeSha256);
const core = { ...v.receipt }; delete core.mac;
assert.equal(canonical(core), v.canonicalCore);
const key = crypto.hkdfSync('sha256', Buffer.from(v.partnerKeyHex, 'hex'), Buffer.alloc(0),
  Buffer.from('magnolienbaum\0baum-1\0receipt-v1'), 32);
const mac = crypto.createHmac('sha256', key).update('magnolienbaum\0baum-1\0receipt-v1\0').update(v.canonicalCore).digest('base64');
assert.equal(mac, v.receipt.mac);
console.log('PASS independent portable Baum receipt vector');
