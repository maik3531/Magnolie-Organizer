#!/usr/bin/env python3
"""Run actual attachment functions with explicit Android boundary seams on the JVM.

The repository Robolectric test's assertions run unchanged; its two runner/config
annotations are removed because this environment has no Android/Robolectric SDK.
FileProvider here checks only the synthetic authority; this is not a provider or
APK acceptance. Kotlin coroutines, Java filesystem writes, and JUnit are real.
"""
from pathlib import Path
import json,subprocess,sys,hashlib,tempfile,resource,signal,shutil
root=Path(sys.argv[1]);dest=Path(sys.argv[2]);dest.mkdir(parents=True,exist_ok=True)
tests=Path(sys.argv[3]) if len(sys.argv)>3 else root
src=dest/'seams';classes=dest/'java';src.mkdir(exist_ok=True);classes.mkdir(exist_ok=True)
java={
'android/content/Context.java':'''package android.content;
public class Context {
 private final java.io.File cache;
 public Context(java.io.File cache){this.cache=cache;}
 public java.io.File getCacheDir(){return cache;}
 public String getPackageName(){return "io.gitlab.maik3531.magnolienotes";}
 public ContentResolver getContentResolver(){return new ContentResolver();}
 public void startActivity(Intent intent){}
}
''',
'android/content/ContextWrapper.java':'''package android.content;
public class ContextWrapper extends Context {
 protected final Context base;
 public ContextWrapper(Context base){super(null);this.base=base;}
 @Override public java.io.File getCacheDir(){return base.getCacheDir();}
 @Override public String getPackageName(){return base.getPackageName();}
 @Override public ContentResolver getContentResolver(){return base.getContentResolver();}
 @Override public void startActivity(Intent intent){base.startActivity(intent);}
}
''',
'android/content/ContentResolver.java':'''package android.content;
public class ContentResolver {public java.io.OutputStream openOutputStream(android.net.Uri uri,String mode){throw new UnsupportedOperationException("not part of opening probe");}}
''',
'android/content/Intent.java':'''package android.content;
public class Intent {
 public static final String ACTION_VIEW="android.intent.action.VIEW";
 public static final int FLAG_GRANT_READ_URI_PERMISSION=1,FLAG_ACTIVITY_NEW_TASK=0x10000000;
 private String action,type;private android.net.Uri data;private int flags;
 public Intent(String action){this.action=action;}
 public Intent setDataAndType(android.net.Uri uri,String mime){data=uri;type=mime;return this;}
 public Intent addFlags(int flags){this.flags|=flags;return this;}
 public String getAction(){return action;}public String getType(){return type;}
 public android.net.Uri getData(){return data;}public int getFlags(){return flags;}
}
''',
'android/content/ActivityNotFoundException.java':'''package android.content;
public class ActivityNotFoundException extends RuntimeException {public ActivityNotFoundException(String message){super(message);}}
''',
'android/net/Uri.java':'''package android.net;
public class Uri {private final String value;public Uri(String value){this.value=value;}public String getScheme(){return value.substring(0,value.indexOf(':'));}}
''',
'androidx/core/content/FileProvider.java':'''package androidx.core.content;
public class FileProvider {
 public static android.net.Uri getUriForFile(android.content.Context context,String authority,java.io.File file){
  if(!authority.equals("io.gitlab.maik3531.magnolienotes.dateien"))throw new IllegalArgumentException("synthetic missing provider");
  if(!file.isFile())throw new IllegalArgumentException("synthetic missing file");
  return new android.net.Uri("content://"+authority+"/anhaenge/"+file.getName());
 }
}
''',
'androidx/test/core/app/ApplicationProvider.java':'''package androidx.test.core.app;
public class ApplicationProvider {
 private static final android.content.Context CONTEXT=new android.content.Context(new java.io.File(System.getProperty("probe.cache")));
 @SuppressWarnings("unchecked") public static <T extends android.content.Context>T getApplicationContext(){return (T)CONTEXT;}
}
'''}
for name,body in java.items():
 f=src/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(body)
subprocess.run(['java','-m','jdk.compiler/com.sun.tools.javac.Main','-d',str(classes)]+list(map(str,src.rglob('*.java'))),check=True)
model=src/'Anhang.kt';model.write_text('''package io.gitlab.maik3531.magnolienotes.daten
data class Anhang(val id:String,val name:String="",val art:String="image",val daten:String="")
''')
prefix=Path('magnolie-notes/app/src')
pkg=Path('java/io/gitlab/maik3531/magnolienotes')
product=[root/prefix/'main'/pkg/'AnhangDatei.kt',root/prefix/'main'/pkg/'daten/AnhangPruefung.kt']
testsource=tests/prefix/'test'/pkg/'AnhangOeffnenTest.kt'
projected=dest/'AnhangOeffnenTest.kt'
projected.write_text('\n'.join(line for line in testsource.read_text().splitlines() if not line.startswith(('import org.junit.runner.RunWith','import org.robolectric.','@RunWith','@Config')))+'\n')
limit=src/'LimitProbe.kt';limit.write_text('''package probe
import androidx.test.core.app.ApplicationProvider
import android.content.Context
import io.gitlab.maik3531.magnolienotes.AnhangDatei
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import java.io.File
import kotlinx.coroutines.runBlocking
fun main()=runBlocking {
 val context=ApplicationProvider.getApplicationContext<Context>()
 val attachment=Anhang("fault","pixel.png","image","data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jFJkAAAAASUVORK5CYII=")
 try { println("result="+AnhangDatei.oeffnen(context,attachment)) }
 catch(error:Throwable){println("escaped=${error.javaClass.name}: ${error.message}")}
 val folder=File(context.cacheDir,"anhaenge")
 println("original="+File(folder,"fault.png").readText())
 println("temporaryFiles="+folder.listFiles().orEmpty().count{it.name.endsWith(".neu")})
}
''')
jars=sorted(Path('$REVIEW_TOOLS/kotlin').glob('*.jar'))
cp=':'.join(map(str,jars));target=dest/'regression.jar';compilecp=str(classes)+':'+cp
originaltests=tests/prefix/'test'/pkg/'AnhangDateiTest.kt'
subprocess.run(['java','-cp',cp,'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-classpath',compilecp,'-d',str(target)]+list(map(str,product+[model,projected,originaltests,limit])),check=True)
cp=str(target)+':'+compilecp
with tempfile.TemporaryDirectory(prefix='cache-',dir=dest) as cache:
 result=subprocess.run(['java','-XX:-UsePerfData','-Dprobe.cache='+cache,'-cp',cp,'org.junit.runner.JUnitCore','io.gitlab.maik3531.magnolienotes.AnhangDateiTest','io.gitlab.maik3531.magnolienotes.AnhangOeffnenTest'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 junit_exit=result.returncode
 (dest/'junit.log').write_text(result.stdout);print(result.stdout);print('junit_exit='+str(junit_exit))
with tempfile.TemporaryDirectory(prefix='write-failure-',dir=dest) as cache:
 folder=Path(cache)/'anhaenge';folder.mkdir();(folder/'fault.png').write_text('keep')
 def limited():
  signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
  resource.setrlimit(resource.RLIMIT_FSIZE,(32,32))
 result=subprocess.run(['java','-XX:-UsePerfData','-Dprobe.cache='+cache,'-cp',cp,'probe.LimitProbeKt'],preexec_fn=limited,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 (dest/'write-failure.log').write_text(result.stdout);print('Real OS file-size limit at 32 bytes, only this subprocess:');print(result.stdout);print('write_probe_exit='+str(result.returncode))
manifest={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in product+[testsource,originaltests]}
(dest/'source-hashes.json').write_text(json.dumps(manifest,indent=2)+'\n')

raise SystemExit(junit_exit or (0 if result.returncode == 0 and 'result=false\n' in result.stdout and 'original=keep\n' in result.stdout and 'temporaryFiles=0\n' in result.stdout else 1))
