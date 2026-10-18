package org.jmcomic;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.webkit.MimeTypeMap;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * SAF(存储访问框架)工具集 —— 只做"具体怎么读写"，不含任何界面。
 *
 * 为什么 Python 侧要绕这么一圈见 tools/saf_bridge.py 的模块注释：
 * APK 里没有 pyjnius、PySide6 也没绑 QJniObject，Python 调不到 Java API，
 * 只能让本进程里的 SafService 用 ContentResolver 代劳。
 */
public final class SafStore {

    /** 单次拷贝的硬上限：防止用户选到根目录(整块存储)时把手机塞满 */
    public static final int MaxFiles = 20000;
    /** 目录递归深度上限 */
    public static final int MaxDepth = 8;

    private SafStore() {
    }

    public static File InboxDir(Context context) {
        File dir = new File(context.getFilesDir(), "saf/inbox");
        dir.mkdirs();
        return dir;
    }

    public static File OutboxDir(Context context) {
        File dir = new File(context.getFilesDir(), "saf/outbox");
        dir.mkdirs();
        return dir;
    }

    /** 把一次请求的结果写成 JSON 文件(Python 侧轮询的就是它) */
    public static void WriteResult(Context context, String reqId, JSONObject result) {
        if (reqId == null || reqId.length() == 0) {
            return;
        }
        File out = new File(OutboxDir(context), reqId + ".json");
        File tmp = new File(OutboxDir(context), reqId + ".json.tmp");
        try {
            OutputStream stream = new FileOutputStream(tmp);
            stream.write(result.toString().getBytes("UTF-8"));
            stream.flush();
            stream.close();
            // 原子替换：Python 看到 .json 时内容一定是完整的
            if (!tmp.renameTo(out)) {
                tmp.delete();
            }
        } catch (Exception es) {
            try {
                tmp.delete();
            } catch (Exception ignore) {
            }
        }
    }

    public static JSONObject Fail(Throwable es) {
        JSONObject out = new JSONObject();
        try {
            out.put("ok", false);
            out.put("error", es == null ? "unknown" : es.getClass().getSimpleName() + ": "
                    + String.valueOf(es.getMessage()));
        } catch (Exception ignore) {
        }
        return out;
    }

    public static JSONObject Cancel() {
        JSONObject out = new JSONObject();
        try {
            out.put("ok", false);
            out.put("cancel", true);
        } catch (Exception ignore) {
        }
        return out;
    }

    /** 显示名(DocumentsUI 给的 OpenableColumns.DISPLAY_NAME) */
    public static String DisplayName(Context context, Uri uri) {
        String name = "";
        try {
            ContentResolver resolver = context.getContentResolver();
            Cursor cursor = resolver.query(uri, new String[]{OpenableColumns.DISPLAY_NAME},
                    null, null, null);
            if (cursor != null) {
                try {
                    if (cursor.moveToFirst()) {
                        int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                        if (index >= 0) {
                            name = cursor.getString(index);
                        }
                    }
                } finally {
                    cursor.close();
                }
            }
        } catch (Exception ignore) {
        }
        if (name == null) {
            name = "";
        }
        return name;
    }

    /** 把 SAF 里的一个文件拷到本地目录，返回落地后的文件(重名自动加后缀) */
    public static File CopyToDir(Context context, Uri uri, File targetDir, String fallbackName) {
        String name = DisplayName(context, uri);
        if (name == null || name.length() == 0) {
            name = fallbackName == null ? "file" : fallbackName;
        }
        name = Sanitize(name);
        targetDir.mkdirs();
        File target = Unique(targetDir, name);
        try {
            InputStream in = context.getContentResolver().openInputStream(uri);
            if (in == null) {
                return null;
            }
            try {
                FileOutputStream out = new FileOutputStream(target);
                try {
                    Copy(in, out);
                } finally {
                    out.close();
                }
            } finally {
                in.close();
            }
            return target;
        } catch (Exception es) {
            try {
                target.delete();
            } catch (Exception ignore) {
            }
            return null;
        }
    }

    /**
     * 把一个 SAF 目录树整棵拷到本地目录(导入本地漫画 / 批量超分的入参)
     *
     * 树上的一级条目直接落在 targetDir 下；如果树里只有一个目录(常见的
     * "Download/某本漫画/…" 只选到漫画目录时不会出现)，保持原样。
     */
    public static JSONObject CopyTreeIn(Context context, Uri treeUri, File targetDir) throws Exception {
        targetDir.mkdirs();
        List<String> copied = new ArrayList<String>();
        int[] counter = new int[]{0};
        String rootId = DocumentsContract.getTreeDocumentId(treeUri);
        WalkIn(context, treeUri, rootId, targetDir, 0, copied, counter);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("path", targetDir.getAbsolutePath());
        out.put("count", copied.size());
        out.put("truncated", counter[0] >= MaxFiles);
        return out;
    }

    private static void WalkIn(Context context, Uri treeUri, String docId, File dir, int depth,
                               List<String> copied, int[] counter) throws Exception {
        if (depth > MaxDepth || counter[0] >= MaxFiles) {
            return;
        }
        ContentResolver resolver = context.getContentResolver();
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, docId);
        Cursor cursor = resolver.query(children, new String[]{
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE}, null, null, null);
        if (cursor == null) {
            return;
        }
        try {
            while (cursor.moveToNext()) {
                if (counter[0] >= MaxFiles) {
                    return;
                }
                String childId = cursor.getString(0);
                String name = Sanitize(cursor.getString(1));
                String mime = cursor.getString(2);
                Uri childUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, childId);
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    File sub = new File(dir, name);
                    sub.mkdirs();
                    WalkIn(context, treeUri, childId, sub, depth + 1, copied, counter);
                } else {
                    dir.mkdirs();
                    File target = Unique(dir, name);
                    InputStream in = resolver.openInputStream(childUri);
                    if (in == null) {
                        continue;
                    }
                    try {
                        FileOutputStream out = new FileOutputStream(target);
                        try {
                            Copy(in, out);
                        } finally {
                            out.close();
                        }
                    } finally {
                        in.close();
                    }
                    copied.add(target.getAbsolutePath());
                    counter[0] += 1;
                }
            }
        } finally {
            cursor.close();
        }
    }

    /**
     * 把本地目录整棵拷到 SAF 树的 subPath 下(下载目录的"导出到所选目录")
     *
     * 同名文件已存在时**覆盖**：Qt 侧是唯一写入者，覆盖语义与本地一致，
     * 不然每次导出都会堆出 "(1)" 副本。
     */
    public static JSONObject CopyTreeOut(Context context, File srcDir, Uri treeUri, String subPath)
            throws Exception {
        ContentResolver resolver = context.getContentResolver();
        Uri parent = EnsureDir(context, treeUri, subPath);
        int[] counter = new int[]{0};
        WalkOut(context, resolver, srcDir, parent, 0, counter);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("count", counter[0]);
        return out;
    }

    private static void WalkOut(Context context, ContentResolver resolver, File dir, Uri parent,
                                int depth, int[] counter) throws Exception {
        if (depth > MaxDepth) {
            return;
        }
        File[] files = dir.listFiles();
        if (files == null) {
            return;
        }
        for (File file : files) {
            if (file.isDirectory()) {
                Uri sub = EnsureChildDir(context, parent, file.getName());
                if (sub != null) {
                    WalkOut(context, resolver, file, sub, depth + 1, counter);
                }
                continue;
            }
            String name = file.getName();
            Uri target = FindChild(context, parent, name);
            if (target == null) {
                target = DocumentsContract.createDocument(resolver, parent, MimeOf(name), name);
            }
            if (target == null) {
                continue;
            }
            InputStream in = new java.io.FileInputStream(file);
            try {
                OutputStream out = resolver.openOutputStream(target, "wt");
                if (out == null) {
                    continue;
                }
                try {
                    Copy(in, out);
                } finally {
                    out.close();
                }
            } finally {
                in.close();
            }
            counter[0] += 1;
        }
    }

    /** 把一个本地文件写到 SAF 的 document uri 上("另存为"选完位置之后用) */
    public static JSONObject WriteFile(Context context, Uri uri, File source) throws Exception {
        JSONObject out = new JSONObject();
        if (source == null || !source.isFile()) {
            out.put("ok", false);
            out.put("error", "source missing");
            return out;
        }
        InputStream in = new java.io.FileInputStream(source);
        try {
            OutputStream stream = context.getContentResolver().openOutputStream(uri, "wt");
            if (stream == null) {
                out.put("ok", false);
                out.put("error", "openOutputStream failed");
                return out;
            }
            try {
                Copy(in, stream);
            } finally {
                stream.close();
            }
        } finally {
            in.close();
        }
        out.put("ok", true);
        out.put("uri", uri.toString());
        return out;
    }

    /** 沿着 subPath("a/b/c") 逐级创建/查找目录，返回最后一级的 document uri */
    private static Uri EnsureDir(Context context, Uri treeUri, String subPath) throws Exception {
        Uri current = DocumentsContract.buildDocumentUriUsingTree(
                treeUri, DocumentsContract.getTreeDocumentId(treeUri));
        if (subPath == null) {
            return current;
        }
        for (String part : subPath.split("/")) {
            if (part.length() == 0) {
                continue;
            }
            Uri sub = EnsureChildDir(context, current, part);
            if (sub == null) {
                return current;
            }
            current = sub;
        }
        return current;
    }

    private static Uri EnsureChildDir(Context context, Uri parent, String name) {
        try {
            Uri found = FindChild(context, parent, Sanitize(name));
            if (found != null) {
                return found;
            }
            return DocumentsContract.createDocument(context.getContentResolver(), parent,
                    DocumentsContract.Document.MIME_TYPE_DIR, Sanitize(name));
        } catch (Exception es) {
            return null;
        }
    }

    private static Uri FindChild(Context context, Uri parent, String name) {
        try {
            ContentResolver resolver = context.getContentResolver();
            Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(
                    parent, DocumentsContract.getDocumentId(parent));
            Cursor cursor = resolver.query(children, new String[]{
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME}, null, null, null);
            if (cursor == null) {
                return null;
            }
            try {
                while (cursor.moveToNext()) {
                    if (name.equals(cursor.getString(1))) {
                        return DocumentsContract.buildDocumentUriUsingTree(parent, cursor.getString(0));
                    }
                }
            } finally {
                cursor.close();
            }
        } catch (Exception ignore) {
        }
        return null;
    }

    public static String MimeOf(String name) {
        int index = name.lastIndexOf('.');
        String ext = index >= 0 ? name.substring(index + 1).toLowerCase() : "";
        String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
        return mime == null ? "application/octet-stream" : mime;
    }

    /** 文件名里不能出现路径分隔符/控制字符 */
    public static String Sanitize(String name) {
        if (name == null || name.length() == 0) {
            return "unnamed";
        }
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < name.length(); i++) {
            char ch = name.charAt(i);
            if (ch == '/' || ch == '\\' || ch < ' ') {
                builder.append('_');
            } else {
                builder.append(ch);
            }
        }
        String value = builder.toString().trim();
        return value.length() == 0 ? "unnamed" : value;
    }

    /** 目标目录里不重名的文件(与桌面端行为一致：xxx (1).jpg) */
    public static File Unique(File dir, String name) {
        File target = new File(dir, name);
        if (!target.exists()) {
            return target;
        }
        String base = name;
        String ext = "";
        int index = name.lastIndexOf('.');
        if (index > 0) {
            base = name.substring(0, index);
            ext = name.substring(index);
        }
        for (int i = 1; i < 10000; i++) {
            target = new File(dir, base + " (" + i + ")" + ext);
            if (!target.exists()) {
                return target;
            }
        }
        return new File(dir, base + "-" + System.currentTimeMillis() + ext);
    }

    public static void Copy(InputStream in, OutputStream out) throws Exception {
        byte[] buffer = new byte[64 * 1024];
        int len;
        while ((len = in.read(buffer)) > 0) {
            out.write(buffer, 0, len);
        }
        out.flush();
    }

    /** 目录是否在应用的专属存储里(这类目录系统文件管理器浏览不到) */
    public static boolean IsAppPrivate(Context context, String path) {
        if (path == null) {
            return false;
        }
        try {
            String root = context.getFilesDir().getAbsolutePath();
            String external = context.getExternalFilesDir(null) == null
                    ? root : context.getExternalFilesDir(null).getAbsolutePath();
            String cache = context.getCacheDir().getAbsolutePath();
            return path.startsWith(root) || path.startsWith(external) || path.startsWith(cache);
        } catch (Exception es) {
            return false;
        }
    }

    public static boolean HasSdk(int level) {
        return Build.VERSION.SDK_INT >= level;
    }
}
