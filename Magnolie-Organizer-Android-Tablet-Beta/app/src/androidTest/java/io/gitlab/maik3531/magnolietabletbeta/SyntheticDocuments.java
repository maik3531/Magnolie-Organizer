package io.gitlab.maik3531.magnolietabletbeta;

import android.database.Cursor;
import android.database.MatrixCursor;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract.Document;
import android.provider.DocumentsContract.Root;
import android.provider.DocumentsProvider;
import java.io.File;
import java.io.FileNotFoundException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Standalone test provider; no target-app/Kotlin dependencies or user directories. */
public final class SyntheticDocuments extends DocumentsProvider {
    private File directory() {
        File directory=new File(getContext().getFilesDir(),"synthetic-documents");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IllegalStateException("Synthetic directory unavailable");
        return directory;
    }
    private File file(String id) {
        if (!SyntheticDocumentControl.validName(id)) throw new IllegalArgumentException("Invalid synthetic document ID");
        return new File(directory(),id);
    }
    @Override public boolean onCreate() { return true; }
    @Override public Cursor queryRoots(String[] projection) {
        String[] columns=projection!=null ? projection : new String[]{Root.COLUMN_ROOT_ID,Root.COLUMN_DOCUMENT_ID,Root.COLUMN_TITLE,Root.COLUMN_FLAGS,Root.COLUMN_MIME_TYPES,Root.COLUMN_AVAILABLE_BYTES};
        MatrixCursor cursor=new MatrixCursor(columns); MatrixCursor.RowBuilder row=cursor.newRow();
        for (String column:columns) {
            Object value=null;
            if (column.equals(Root.COLUMN_ROOT_ID)||column.equals(Root.COLUMN_DOCUMENT_ID)) value="root";
            else if (column.equals(Root.COLUMN_TITLE)) value="Tablet Beta Test Documents";
            else if (column.equals(Root.COLUMN_FLAGS)) value=Root.FLAG_SUPPORTS_CREATE|Root.FLAG_LOCAL_ONLY;
            else if (column.equals(Root.COLUMN_MIME_TYPES)) value="application/json\napplication/pdf\ntext/calendar";
            else if (column.equals(Root.COLUMN_AVAILABLE_BYTES)) value=100000000L;
            row.add(column,value);
        }
        return cursor;
    }
    private Cursor cursor(List<String> ids,String[] projection) {
        String[] columns=projection!=null ? projection : new String[]{Document.COLUMN_DOCUMENT_ID,Document.COLUMN_DISPLAY_NAME,Document.COLUMN_MIME_TYPE,Document.COLUMN_FLAGS,Document.COLUMN_SIZE,Document.COLUMN_LAST_MODIFIED};
        MatrixCursor cursor=new MatrixCursor(columns);
        for (String id:ids) {
            File document=id.equals("root") ? directory() : file(id); MatrixCursor.RowBuilder row=cursor.newRow();
            for (String column:columns) {
                Object value=null;
                if (column.equals(Document.COLUMN_DOCUMENT_ID)) value=id;
                else if (column.equals(Document.COLUMN_DISPLAY_NAME)) value=id.equals("root") ? "Tablet Beta Test Documents" : id;
                else if (column.equals(Document.COLUMN_MIME_TYPE)) value=id.equals("root") ? Document.MIME_TYPE_DIR : id.endsWith(".pdf") ? "application/pdf" : id.endsWith(".ics") ? "text/calendar" : "application/json";
                else if (column.equals(Document.COLUMN_FLAGS)) value=id.equals("root") ? Document.FLAG_DIR_SUPPORTS_CREATE : Document.FLAG_SUPPORTS_WRITE|Document.FLAG_SUPPORTS_DELETE;
                else if (column.equals(Document.COLUMN_SIZE)) value=document.length();
                else if (column.equals(Document.COLUMN_LAST_MODIFIED)) value=document.lastModified();
                row.add(column,value);
            }
        }
        return cursor;
    }
    @Override public Cursor queryDocument(String id,String[] projection) { return cursor(Collections.singletonList(id),projection); }
    @Override public Cursor queryChildDocuments(String parent,String[] projection,String sortOrder) {
        if (!parent.equals("root")) throw new IllegalArgumentException("Unexpected synthetic parent");
        List<String> ids=new ArrayList<>(); File[] children=directory().listFiles();
        if (children!=null) for (File child:children) if (child.isFile()) ids.add(child.getName());
        Collections.sort(ids);return cursor(ids,projection);
    }
    @Override public ParcelFileDescriptor openDocument(String id,String mode,CancellationSignal signal) throws FileNotFoundException {
        return ParcelFileDescriptor.open(file(id),ParcelFileDescriptor.parseMode(mode));
    }
    @Override public String createDocument(String parent,String mimeType,String name) throws FileNotFoundException {
        if (!parent.equals("root")) throw new IllegalArgumentException("Unexpected synthetic parent");
        File document=file(name);
        try { if (!document.createNewFile()) throw new FileNotFoundException("Synthetic fixture already exists"); }
        catch (java.io.IOException failure) { throw new FileNotFoundException("Synthetic fixture creation failed"); }
        return document.getName();
    }
    @Override public void deleteDocument(String id) throws FileNotFoundException {
        if (!file(id).delete()) throw new FileNotFoundException("Synthetic deletion failed");
    }
    @Override public boolean isChildDocument(String parent,String id) { return parent.equals("root") && file(id).isFile(); }
}
