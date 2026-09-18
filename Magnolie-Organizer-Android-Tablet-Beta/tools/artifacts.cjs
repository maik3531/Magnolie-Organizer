const fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const apkPath=path.join(root,'app/build/outputs/apk/debug/app-debug.apk');
const apk=fs.readFileSync(apkPath);
const manifest=JSON.parse(fs.readFileSync(path.join(root,'app/build/generated/projection/assets/projection.json')));
const web=JSON.parse(fs.readFileSync(path.join(root,'artifacts/web-test-proof.json')));
const reminders=JSON.parse(fs.readFileSync(path.join(root,'artifacts/a3-editor-vectors.json')));
const build=JSON.parse(fs.readFileSync(path.join(root,'artifacts/debug-build.json')));
if(!build.runnerTests || !build.setupHolidayCases) throw Error('Run the complete bounded debug gate first');
if(reminders.sourceHash!==manifest.sourceHash) throw Error('Editor reminder tests used a different projection');
if(web.sourceHash!==manifest.sourceHash) throw Error('Web tests did not run against this projection; rerun the gate');
const sdk=process.env.ANDROID_HOME || path.join(process.env.HOME,'.local/share/android-sdk');
const tools=path.join(sdk,'build-tools/35.0.0');
const badging=execFileSync(path.join(tools,'aapt'),['dump','badging',apkPath],{encoding:'utf8'});
if(!badging.includes("package: name='io.gitlab.maik3531.magnolieorganizer.tablet.beta'") ||
   !badging.includes("versionCode='20018'") || !badging.includes("versionName='2.0.18Beta'") ||
   !badging.includes("application-label:'Magnolie Organizer Android Tablet Beta 2.0.18Beta'")) throw Error('APK beta identity mismatch');
const signature=execFileSync(path.join(tools,'apksigner'),['verify','--print-certs',apkPath],{encoding:'utf8'});
if(!signature.includes('CN=Android Debug')) throw Error('Only the explicitly generated debug certificate is authorized');
if(/uses-permission: name='android.permission.(?:INTERNET|SEND_SMS|CALL_PHONE|READ_CONTACTS|READ_CALENDAR)'/.test(badging))
  throw Error('Unsupported native integration permission in local beta');
const appManifest=execFileSync(path.join(tools,'aapt'),['dump','xmltree',apkPath,'AndroidManifest.xml'],{encoding:'utf8'});
if(/SyntheticDocument|NativeTabletInstrumentation/.test(appManifest)) throw Error('Test component leaked into app APK');
const packagedManifest=JSON.parse(execFileSync('unzip',['-p',apkPath,'assets/projection.json'],{encoding:'utf8'}));
if(JSON.stringify(packagedManifest)!==JSON.stringify(manifest)) throw Error('APK packaged a different projection');
for(const [name,hash] of Object.entries(manifest.outputs)) if(name.startsWith('assets/')) {
  const bytes=execFileSync('unzip',['-p',apkPath,name],{maxBuffer:32*1024*1024});
  if(createHash('sha256').update(bytes).digest('hex')!==hash) throw Error('APK asset differs: '+name);
}
const results=path.join(root,'app/build/test-results/testDebugUnitTest');
let unitTests=0;
for(const file of fs.readdirSync(results).filter(f=>f.endsWith('.xml'))) {
  const text=fs.readFileSync(path.join(results,file),'utf8');
  const header=text.match(/<testsuite\s[^>]+>/)?.[0] || '';
  const attr=name=>Number(header.match(new RegExp(name+'="(\\d+)"'))?.[1] ?? NaN);
  if(!Number.isFinite(attr('tests')) || attr('failures') || attr('errors') || attr('skipped')) throw Error('Unit tests failed or skipped');
  unitTests+=attr('tests');
}
if(!unitTests) throw Error('No native unit tests ran');
const name='Magnolie-Organizer-Android-Tablet-Beta-2.0.18Beta-debug.apk';
const testName='Magnolie-Organizer-Android-Tablet-Beta-2.0.18Beta-instrumentation.apk';
const testPath=path.join(root,'app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk');
const testApk=fs.readFileSync(testPath);
const testHash=createHash('sha256').update(testApk).digest('hex');
const testSignature=execFileSync(path.join(tools,'apksigner'),['verify','--print-certs',testPath],{encoding:'utf8'});
if(!testSignature.includes('CN=Android Debug')) throw Error('Instrumentation must use debug signing');
const cert=text=>text.match(/Signer #1 certificate SHA-256 digest: (\w+)/)?.[1];
if(!cert(signature) || cert(signature)!==cert(testSignature)) throw Error('App and instrumentation signing certificates differ');
const testManifest=execFileSync(path.join(tools,'aapt'),['dump','xmltree',testPath,'AndroidManifest.xml'],{encoding:'utf8'});
if(!testManifest.includes('io.gitlab.maik3531.magnolieorganizer.tablet.beta.test') ||
   !/targetPackage[^\n]*="io.gitlab.maik3531.magnolieorganizer.tablet.beta"/.test(testManifest) ||
   !/testOnly[^\n]*0xffffffff/.test(testManifest)) throw Error('Instrumentation must be test-only and target this beta');
const hash=createHash('sha256').update(apk).digest('hex');
const out=path.join(root,'artifacts');fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(out,name),apk);
fs.writeFileSync(path.join(out,testName),testApk);
fs.writeFileSync(path.join(out,testName+'.sha256'),testHash+'  '+testName+'\n');
fs.writeFileSync(path.join(out,name+'.sha256'),hash+'  '+name+'\n');
fs.writeFileSync(path.join(out,'projection.json'),JSON.stringify(manifest,null,2)+'\n');
fs.writeFileSync(path.join(out,'apk-verification.txt'),badging+'\n'+signature);
fs.writeFileSync(path.join(out,'candidate.json'),JSON.stringify({name,sha256:hash,sourceHash:manifest.sourceHash,
  testApk:testName,testApkSha256:testHash,instrumentationTestOnly:true,
  applicationId:'io.gitlab.maik3531.magnolieorganizer.tablet.beta',signing:'debug only',
  displayName:'Magnolie Organizer Android Tablet Beta 2.0.18Beta',versionName:'2.0.18Beta',versionCode:20018,
  status:'unaccepted beta candidate; not a production release',stale:false,emulatorTested:false,
  webChecks:web.passed,editorReminderCases:reminders.cases.length,unitTests,unitReport:'app/build/reports/tests/testDebugUnitTest/index.html',
  runnerTests:build.runnerTests,setupHolidayCases:build.setupHolidayCases,setupLocales:build.setupLocales,
  apkAssetsVerified:true},null,2)+'\n');
console.log('Debug-only, emulator-UNTESTED beta candidate: '+path.join(out,name));
execFileSync(process.execPath,[path.join(root,'tools/project-web.cjs'),'--check'],{stdio:'inherit'});
