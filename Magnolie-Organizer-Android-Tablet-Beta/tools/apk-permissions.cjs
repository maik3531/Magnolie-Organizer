'use strict';

// Existing HTTPS/reminders plus explicit read-only source discovery. AndroidX
// core:1.13.1 adds precisely this signature-only receiver permission (official
// AAR SHA256 2c27de199535675005553066597a4b20fa1eea7c228ab4ef6b32b5fe39ca1f59).
const RECEIVER = 'io.gitlab.maik3531.magnolieorganizer.tablet.beta.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION';
const REQUIRED = Object.freeze([
  'android.permission.INTERNET',
  'android.permission.POST_NOTIFICATIONS',
  'android.permission.RECEIVE_BOOT_COMPLETED',
  'android.permission.READ_CALENDAR',
  'android.permission.READ_CONTACTS',
  RECEIVER,
]);
function verifyReceiverProtection(xmltree) {
  const declarations=[];
  let current=null;
  const finish=()=>{if(current) declarations.push(current);current=null;};
  for(const line of xmltree.split(/\r?\n/)) {
    const element=/^(\s*)E: ([\w:-]+)(?:\s|$)/.exec(line);
    if(element) {
      if(current && element[1].length<=current.indent) finish();
      if(['permission','permission-tree','permission-group'].includes(element[2]))
        current={kind:element[2],indent:element[1].length,names:[],protections:[]};
      else if(current) current.nested=true;
      continue;
    }
    if(!current || current.nested) continue;
    const attribute=/^\s+A: android:(name|protectionLevel)\(0x[0-9a-f]+\)=(.*)$/.exec(line);
    if(!attribute) continue;
    if(attribute[1]==='name') current.names.push(attribute[2].match(/^"([^"]+)"/)?.[1]);
    else current.protections.push(attribute[2]);
  }
  finish();
  const own=declarations.filter(declaration=>declaration.names.includes(RECEIVER));
  if(declarations.length!==1 || own.length!==1 || own[0].kind!=='permission' || own[0].names.length!==1 || own[0].protections.length!==1 ||
     !/^\(type 0x11\)0x2(?:\s|$)/.test(own[0].protections[0]))
    throw Error('App-owned receiver permission must have exactly signature protection');
}
function verifyAppPermissions(badging,xmltree) {
  const actual = new Set();
  for (const line of badging.split(/\r?\n/)) {
    if (!/^uses-(?:permission|implied-permission)/.test(line)) continue;
    const match = /^uses-permission: name='([^']+)'$/.exec(line);
    if (!match || !REQUIRED.includes(match[1]) || actual.has(match[1]))
      throw Error('Unsupported or ambiguous APK permission declaration');
    actual.add(match[1]);
  }
  if (REQUIRED.some(permission => !actual.has(permission)))
    throw Error('Missing required beta APK permission');
  verifyReceiverProtection(xmltree);
  return [...actual].sort();
}
module.exports = {verifyAppPermissions};
