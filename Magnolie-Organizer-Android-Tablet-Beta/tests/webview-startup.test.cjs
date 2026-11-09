// Native startup source/resource contracts. No Android UI/runtime acceptance claim.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
module.exports=function run({root}) {
 const read=name=>fs.readFileSync(path.join(root,name),'utf8');
 const catalog=JSON.parse(read('web/native-startup-i18n.json')),beta=JSON.parse(read('web/beta-i18n.json'));
 assert.deepEqual(Object.keys(catalog).sort(),Object.keys(beta).sort());
 const keys=['webview_title','webview_body','webview_update','webview_settings','webview_retry','webview_no_update','webview_unknown_provider'];
 let count=1;
 for(const [locale,strings] of Object.entries(catalog)) {
  assert.deepEqual(Object.keys(strings).sort(),[...keys].sort());assert(Object.values(strings).every(v=>typeof v==='string'&&v.trim()));
  const qualifier=locale==='en'?'values':locale==='zh_CN'?'values-zh-rCN':'values-'+locale;
  const generated=read('app/build/generated/projection/res/'+qualifier+'/strings.xml');
  for(const key of keys)assert(generated.includes('<string name="'+key+'" formatted="false">'));
  assert(!strings.webview_body.includes('WEB_MESSAGE_LISTENER'));count++;
 }
 const main=read('app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/MainActivity.kt');
 const branch=main.slice(main.indexOf('if (WebViewStartup.terminalReason('),main.indexOf('WebViewCompat.addWebMessageListener'));
 assert(branch.includes('unsupportedWebView(); return'));assert(!branch.includes('fatal()'));
 assert(main.indexOf(branch)<main.indexOf('startupMark(StartupPhase.LOAD_URL)'));count++;
 const screen=read('app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/UnsupportedWebViewScreen.kt');
 assert(!screen.includes('loadUrl')&&!screen.includes('addJavascriptInterface')&&!screen.includes('AndroidStore'));
 assert(screen.includes('appendQueryParameter("id",name)'));
 assert(screen.includes('button(R.string.webview_update,providerPackage!=null) {'));
 assert(screen.includes('button(R.string.webview_retry,action=retry)'));count++;
 const instrumentation=read('app/src/androidTest/java/io/gitlab/maik3531/magnolietabletbeta/NativeTabletInstrumentation.kt');
 assert(instrumentation.includes('if(unsupported.get(activity)!=null) {observationError=WebViewStartup.TERMINAL_REASON;break}'));
 assert(instrumentation.includes('check(gate.accepted && observationError==null)'));
 assert(instrumentation.includes('if(unsupported!=null) done.countDown()'));count++;
 count+=require('./startup-diagnostics.test.cjs')({root});
 return count;
};
