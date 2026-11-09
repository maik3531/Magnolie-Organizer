package io.gitlab.maik3531.magnolietabletbeta;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Test APK's standalone process must not depend on the target APK's Kotlin runtime. */
public final class SyntheticDocumentControl extends BroadcastReceiver {
    static boolean validName(String name) {
        return name != null && name.matches("[A-Za-z0-9._ -]{1,160}") && !name.equals(".") && !name.equals("..");
    }
    @Override public void onReceive(Context context, Intent intent) {
        String name=intent.getStringExtra("name");
        if (!validName(name)) throw new IllegalArgumentException("Invalid synthetic document name");
        File directory=new File(context.getFilesDir(),"synthetic-documents");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IllegalStateException("Synthetic directory unavailable");
        File file=new File(directory,name);
        try {
            if (intent.getBooleanExtra("delete",false)) {
                if (file.exists() && !file.delete()) throw new IllegalStateException("Synthetic deletion failed");
                complete(new byte[0]); return;
            }
            if (intent.hasExtra("text")) {
                String text=intent.getStringExtra("text");
                if (text==null || text.length()>=500000) throw new IllegalArgumentException("Synthetic text limit");
                byte[] bytes=text.getBytes(StandardCharsets.UTF_8);
                if (bytes.length>=750000) throw new IllegalArgumentException("Synthetic byte limit");
                try (FileOutputStream output=new FileOutputStream(file)) { output.write(bytes); }
            }
            if (!file.isFile() || file.length()>=750000) throw new IllegalStateException("Synthetic fixture unavailable or oversized");
            byte[] bytes=new byte[(int)file.length()];
            try (FileInputStream input=new FileInputStream(file)) {
                int offset=0;
                while (offset<bytes.length) {
                    int count=input.read(bytes,offset,bytes.length-offset);
                    if (count<0) throw new IllegalStateException("Synthetic fixture changed while reading");
                    offset+=count;
                }
                if (input.read()!=-1) throw new IllegalStateException("Synthetic fixture exceeded byte limit");
            }
            complete(bytes);
        } catch (java.io.IOException failure) { throw new IllegalStateException("Synthetic fixture I/O failed",failure); }
    }
    private void complete(byte[] bytes) {
        Bundle result=new Bundle(); result.putByteArray("bytes",bytes);
        setResult(Activity.RESULT_OK,"synthetic fixture",result);
    }
}
