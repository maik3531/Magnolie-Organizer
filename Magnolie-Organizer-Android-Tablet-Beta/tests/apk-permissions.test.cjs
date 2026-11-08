'use strict';
const assert = require('node:assert/strict');
const {verifyAppPermissions} = require('../tools/apk-permissions.cjs');
const allowed = ['INTERNET','POST_NOTIFICATIONS','RECEIVE_BOOT_COMPLETED','READ_CALENDAR','READ_CONTACTS'];
const receiver='io.gitlab.maik3531.magnolieorganizer.tablet.beta.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION';
// aapt xmltree representation of the exact declaration in the checksum-verified
// official AndroidX core1.13.1 AAR, after applicationId placeholder merging.
const xml=`E: manifest (line=1)
  E: permission (line=4)
    A: android:name(0x01010003)="${receiver}" (Raw: "${receiver}")
    A: android:protectionLevel(0x01010009)=(type 0x11)0x2
  E: uses-permission (line=6)
    A: android:name(0x01010003)="${receiver}" (Raw: "${receiver}")
`;
const row = name => `uses-permission: name='android.permission.${name}'`;
const good = "package: name='synthetic.beta'\n" + allowed.map(row).join('\n')+`\nuses-permission: name='${receiver}'`;
assert.deepEqual(verifyAppPermissions(good,xml), [...allowed.map(name=>'android.permission.'+name),receiver].sort());
let rejected = 0;
for (const permission of ['WRITE_CALENDAR','WRITE_CONTACTS','GET_ACCOUNTS','AUTHENTICATE_ACCOUNTS',
  'MANAGE_ACCOUNTS','SEND_SMS','READ_SMS','RECEIVE_SMS','CALL_PHONE','READ_CALL_LOG','WRITE_CALL_LOG',
  'READ_PHONE_STATE','READ_EXTERNAL_STORAGE','WRITE_EXTERNAL_STORAGE','MANAGE_EXTERNAL_STORAGE','ACCESS_FINE_LOCATION']) {
  assert.throws(()=>verifyAppPermissions(good+'\n'+row(permission),xml),/Unsupported/);
  rejected++;
}
for (const missing of allowed) {
  assert.throws(()=>verifyAppPermissions(allowed.filter(name=>name!==missing).map(row).join('\n')+`\nuses-permission: name='${receiver}'`,xml),/Missing/);
  rejected++;
}
for (const ambiguous of [row('READ_CONTACTS'),
  "uses-permission-sdk-23: name='android.permission.WRITE_CONTACTS'",
  "uses-permission: name='android.permission.READ_CONTACTS' maxSdkVersion='25'",
  "uses-implied-permission: name='android.permission.WRITE_EXTERNAL_STORAGE' reason='legacy'",
  "uses-permission: name='synthetic.unknown.permission'",
  'uses-permission: malformed']) {
  assert.throws(()=>verifyAppPermissions(good+'\n'+ambiguous,xml),/Unsupported/); rejected++;
}
for(const invalid of [xml.replace('0x2','0x0'),xml.replace('0x2','0x1'),xml.replace('0x2','0x3'),
  xml.replace('0x2','0x12'),xml.replace('0x2','0x20'),'',xml.replaceAll(receiver,receiver+'.unexpected'),
  xml.replace('  E: permission (line=4)','  E: permission-tree (line=4)'),xml.replace('  E: permission (line=4)','  E: permission-group (line=4)'),xml+xml,xml+`  E: permission (line=9)\n    A: android:name(0x01010003)="synthetic.unknown.permission"\n    A: android:protectionLevel(0x01010009)=(type 0x11)0x2\n`,xml.replace('  E: permission (line=4)','  E: uses-permission (line=4)')]) {
  assert.throws(()=>verifyAppPermissions(good,invalid),/signature/); rejected++;
}
assert.throws(()=>verifyAppPermissions(good.replace(`uses-permission: name='${receiver}'`,''),xml),/Missing/);rejected++;
console.log(`1 exact read-only APK permission contract and ${rejected} negative cases passed`);
