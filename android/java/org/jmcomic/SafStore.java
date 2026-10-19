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

    /** 显示名(DocumentsUI 给的 OpenableColumns.DISPLAY_NAME)
     *
     * 注意 tree URI 上**取不到**显示名：OpenableColumns 只对 document URI 有效，
     * 必须先用 buildDocumentUriUsingTree 换成该树的根 document URI 再查。
     * 真机踩过：直接查 tree URI 返回 null -> 设置页"下载目录"显示不出用户选的名字，
     * 看起来就像"设置没生效"。
     */
    public static String DisplayName(Context context, Uri uri) {
        Uri target = uri;
        boolean isTree = false;
        try {
            isTree = DocumentsContract.isTreeUri(uri);
            if (isTree) {
                target = DocumentsContract.buildDocumentUriUsingTree(
                        uri, DocumentsContract.getTreeDocumentId(uri));
            }
        } catch (Exception ignore) {
        }
        String name = QueryName(context, target);
        if (name == null || name.length() == 0) {
            try {
                String docId = isTree ? DocumentsContract.getTreeDocumentId(uri) : "";
                int colon = docId.lastIndexOf(':');
                String tail = colon >= 0 ? docId.substring(colon + 1) : docId;
                int slash = tail.lastIndexOf('/');
                name = slash >= 0 ? tail.substring(slash + 1) : tail;
            } catch (Exception ignore) {
            }
        }
        return name == null ? "" : name;
    }

    private static String QueryName(Context context, Uri uri) {
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

    // ------------------------------------------------------------------
    // 相对路径读写(下载/阅读直接在 SAF 目录里按 "commies/某本/…/0001.jpg" 干活)
    // ------------------------------------------------------------------
    //
    // 为什么要有这一组：下载不能"先落私有目录再整体导出" —— 用户把下载路径改成
    // 某个目录之后，文件在下载过程中就必须待在那个目录里(取消/崩溃也不会在私有
    // 目录留残渣)。所以 Python 侧手里的路径是 "saf://<树>/commies/…"，
    // 由这里把它解析成 document uri 再读写。
    //
    // 性能：一页图一次 openOutputStream 是不可避免的，但**每页都重新列一遍父目录**
    // 是可以避免的 —— 下载一本漫画有几百页，全都在同一个目录下。这里按目录缓存
    // 一次子项表，新建的文件直接塞进缓存，实测把"每页 2 次 query"降到"每目录 1 次"。

    /** 目录里的一个条目 */
    public static final class Doc {
        public final Uri uri;
        public final String name;
        public final boolean dir;
        public final long size;

        Doc(Uri uri, String name, boolean dir, long size) {
            this.uri = uri;
            this.name = name;
            this.dir = dir;
            this.size = size;
        }
    }

    /** relDir -> 目录 document uri */
    private static final java.util.HashMap<String, Uri> DirCache = new java.util.HashMap<>();
    /** 目录 document uri -> (名字 -> 条目) */
    private static final java.util.HashMap<String, java.util.HashMap<String, Doc>> ChildCache =
            new java.util.HashMap<>();

    /** 目录被外部改过(删除/导出)时整体失效 */
    public static void InvalidateCache() {
        synchronized (DirCache) {
            DirCache.clear();
            ChildCache.clear();
        }
    }

    public static Uri RootDoc(Uri treeUri) {
        return DocumentsContract.buildDocumentUriUsingTree(
                treeUri, DocumentsContract.getTreeDocumentId(treeUri));
    }

    /** "a/b/c" -> ["a","b","c"] */
    private static List<String> Parts(String rel) {
        List<String> out = new ArrayList<String>();
        if (rel == null) {
            return out;
        }
        for (String part : rel.split("/")) {
            if (part.length() > 0) {
                out.add(part);
            }
        }
        return out;
    }

    public static String ParentOf(String rel) {
        int index = rel == null ? -1 : rel.lastIndexOf('/');
        return index <= 0 ? "" : rel.substring(0, index);
    }

    public static String NameOf(String rel) {
        int index = rel == null ? -1 : rel.lastIndexOf('/');
        return index < 0 ? (rel == null ? "" : rel) : rel.substring(index + 1);
    }

    /** 列一个目录的子项(带缓存；reload=true 时强制重列) */
    public static java.util.HashMap<String, Doc> ChildrenOf(Context context, Uri dirUri, boolean reload) {
        String key = dirUri.toString();
        if (!reload) {
            synchronized (DirCache) {
                java.util.HashMap<String, Doc> cached = ChildCache.get(key);
                if (cached != null) {
                    return cached;
                }
            }
        }
        java.util.HashMap<String, Doc> map = new java.util.HashMap<String, Doc>();
        Cursor cursor = null;
        try {
            Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(
                    dirUri, DocumentsContract.getDocumentId(dirUri));
            cursor = context.getContentResolver().query(children, new String[]{
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                    DocumentsContract.Document.COLUMN_SIZE}, null, null, null);
            if (cursor != null) {
                while (cursor.moveToNext()) {
                    String id = cursor.getString(0);
                    String name = cursor.getString(1);
                    String mime = cursor.getString(2);
                    long size = cursor.isNull(3) ? -1 : cursor.getLong(3);
                    if (name == null) {
                        continue;
                    }
                    map.put(name, new Doc(DocumentsContract.buildDocumentUriUsingTree(dirUri, id),
                            name, DocumentsContract.Document.MIME_TYPE_DIR.equals(mime), size));
                }
            }
        } catch (Exception ignore) {
        } finally {
            if (cursor != null) {
                try {
                    cursor.close();
                } catch (Exception ignore) {
                }
            }
        }
        synchronized (DirCache) {
            ChildCache.put(key, map);
        }
        return map;
    }

    /** 逐级创建/查找目录，返回目录 uri(失败时返回能到的最后一级) */
    public static Uri EnsureDirRel(Context context, Uri treeUri, String relDir) {
        Uri root = RootDoc(treeUri);
        List<String> parts = Parts(relDir);
        if (parts.isEmpty()) {
            return root;
        }
        String key = treeUri.toString() + "|" + relDir;
        synchronized (DirCache) {
            Uri cached = DirCache.get(key);
            if (cached != null) {
                return cached;
            }
        }
        Uri parent = root;
        StringBuilder built = new StringBuilder();
        for (String part : parts) {
            if (built.length() > 0) {
                built.append('/');
            }
            built.append(part);
            String subKey = treeUri.toString() + "|" + built;
            Uri sub = null;
            synchronized (DirCache) {
                sub = DirCache.get(subKey);
            }
            if (sub == null) {
                sub = EnsureChildDir(context, parent, part);
                if (sub == null) {
                    return parent;
                }
                synchronized (DirCache) {
                    DirCache.put(subKey, sub);
                }
            }
            parent = sub;
        }
        return parent;
    }

    /** 找相对路径对应的条目(不存在返回 null) */
    public static Doc FindRel(Context context, Uri treeUri, String rel) {
        String parentRel = ParentOf(rel);
        String name = NameOf(rel);
        if (name.length() == 0) {
            return new Doc(RootDoc(treeUri), "", true, -1);
        }
        Uri dir = EnsureDirRel(context, treeUri, parentRel);
        java.util.HashMap<String, Doc> children = ChildrenOf(context, dir, false);
        Doc doc = children.get(name);
        if (doc != null) {
            return doc;
        }
        // 可能是外部新增的(比如用户往目录里放了文件)：重列一次
        children = ChildrenOf(context, dir, true);
        return children.get(name);
    }

    /** 找相对路径对应的文件；不存在就创建(父目录自动建) */
    public static Uri EnsureFileRel(Context context, Uri treeUri, String rel) throws Exception {
        Doc found = FindRel(context, treeUri, rel);
        if (found != null && !found.dir) {
            return found.uri;
        }
        String parentRel = ParentOf(rel);
        String name = Sanitize(NameOf(rel));
        Uri dir = EnsureDirRel(context, treeUri, parentRel);
        Uri created = DocumentsContract.createDocument(
                context.getContentResolver(), dir, MimeOf(name), name);
        if (created == null) {
            throw new Exception("createDocument failed: " + rel);
        }
        java.util.HashMap<String, Doc> children = ChildrenOf(context, dir, false);
        children.put(name, new Doc(created, name, false, -1));
        return created;
    }

    /** 读一个相对路径的文件；不存在返回 null */
    public static InputStream OpenRead(Context context, Uri treeUri, String rel) throws Exception {
        Doc found = FindRel(context, treeUri, rel);
        if (found == null || found.dir) {
            return null;
        }
        try {
            return context.getContentResolver().openInputStream(found.uri);
        } catch (Exception es) {
            // 缓存的 uri 可能已失效(用户在文件管理器里删了/改名了)：清缓存重找一次
            InvalidateCache();
            found = FindRel(context, treeUri, rel);
            if (found == null || found.dir) {
                return null;
            }
            return context.getContentResolver().openInputStream(found.uri);
        }
    }

    /** 写一个相对路径的文件(存在就截断重写)，返回写入字节数 */
    public static long WriteStream(Context context, Uri treeUri, String rel,
                                   InputStream source, long size) throws Exception {
        Uri uri = EnsureFileRel(context, treeUri, rel);
        OutputStream out;
        try {
            out = context.getContentResolver().openOutputStream(uri, "wt");
        } catch (Exception es) {
            // 缓存里的 uri 可能已经失效(用户在外面删了)：清缓存重来一次
            InvalidateCache();
            uri = EnsureFileRel(context, treeUri, rel);
            out = context.getContentResolver().openOutputStream(uri, "wt");
        }
        if (out == null) {
            throw new Exception("openOutputStream failed: " + rel);
        }
        long written = 0;
        try {
            byte[] buffer = new byte[64 * 1024];
            while (true) {
                int want = buffer.length;
                if (size >= 0 && written + want > size) {
                    want = (int) (size - written);
                }
                if (size >= 0 && want <= 0) {
                    break;
                }
                int len = source.read(buffer, 0, want);
                if (len <= 0) {
                    break;
                }
                out.write(buffer, 0, len);
                written += len;
            }
            out.flush();
        } finally {
            try {
                out.close();
            } catch (Exception ignore) {
            }
        }
        // 刚 createDocument 出来的条目在缓存里 size 是 -1，写完把真实大小记上
        // (否则 vfs.Size() 会一直返回 -1)
        try {
            String name = NameOf(rel);
            Uri parent = EnsureDirRel(context, treeUri, ParentOf(rel));
            ChildrenOf(context, parent, false).put(name, new Doc(uri, name, false, written));
        } catch (Exception ignore) {
        }
        return written;
    }

    /** 读一个相对路径的文件到输出流，返回字节数；不存在返回 -1 */
    public static long ReadStream(Context context, Uri treeUri, String rel, OutputStream target)
            throws Exception {
        InputStream in = OpenRead(context, treeUri, rel);
        if (in == null) {
            return -1;
        }
        long total = 0;
        try {
            byte[] buffer = new byte[64 * 1024];
            int len;
            while ((len = in.read(buffer)) > 0) {
                target.write(buffer, 0, len);
                total += len;
            }
            target.flush();
        } finally {
            try {
                in.close();
            } catch (Exception ignore) {
            }
        }
        return total;
    }

    /** 删除相对路径(目录递归)，返回删掉的条目数 */
    public static org.json.JSONObject DeleteRel(Context context, Uri treeUri, String rel)
            throws Exception {
        Doc found = FindRel(context, treeUri, rel);
        org.json.JSONObject out = new org.json.JSONObject();
        org.json.JSONArray errors = new org.json.JSONArray();
        int[] counter = new int[]{0, 0};   // [文件数, 目录数]
        if (found != null) {
            DeleteDoc(context, found, errors, counter);
        }
        InvalidateCache();
        out.put("ok", true);
        out.put("files", counter[0]);
        out.put("dirs", counter[1]);
        out.put("count", counter[0] + counter[1]);
        if (errors.length() > 0) {
            // 目录删不掉不算失败(见下面的注释)；把细节带出去方便排查
            out.put("errors", errors);
        }
        return out;
    }

    /**
     * 递归删除；文件必须删掉，目录"尽力而为"
     *
     * 真机/模拟器实测：ExternalStorageProvider 对**目录**的 deleteDocument 经常直接
     * 回一句 `IllegalStateException: Failed to delete <path>`（哪怕目录已经空了），
     * 而 ContentResolver.delete 在 SAF 上是 UnsupportedOperationException。
     * 用户真正在意的是"漫画文件没了、列表里也没了"，留几个空目录无伤大雅 ——
     * 所以这里文件删失败才计入 errors，目录删失败只记录不报错。
     */
    private static void DeleteDoc(Context context, Doc doc, org.json.JSONArray errors, int[] counter) {
        try {
            if (doc.dir) {
                for (Doc child : ChildrenOf(context, doc.uri, true).values()) {
                    DeleteDoc(context, child, errors, counter);
                }
            }
            boolean ok = false;
            Exception last = null;
            try {
                ok = DocumentsContract.deleteDocument(context.getContentResolver(), doc.uri);
            } catch (Exception es) {
                last = es;
            }
            if (!ok) {
                try {
                    ok = context.getContentResolver().delete(doc.uri, null, null) > 0;
                } catch (Exception es) {
                    if (last == null) {
                        last = es;
                    }
                }
            }
            if (ok) {
                if (doc.dir) {
                    counter[1] += 1;
                } else {
                    counter[0] += 1;
                }
            } else if (!doc.dir) {
                errors.put(doc.name + ": " + (last == null ? "delete returned false"
                        : last.getClass().getSimpleName() + ":" + last.getMessage()));
            }
        } catch (Exception es) {
            if (!doc.dir) {
                errors.put(doc.name + " (walk): " + es.getClass().getSimpleName());
            }
        }
    }

    /** 列出相对路径目录的子项 [name, isDir, size] */
    public static org.json.JSONArray ListRel(Context context, Uri treeUri, String rel) throws Exception {
        org.json.JSONArray out = new org.json.JSONArray();
        Uri dir = EnsureDirRel(context, treeUri, rel);
        for (Doc doc : ChildrenOf(context, dir, true).values()) {
            org.json.JSONArray item = new org.json.JSONArray();
            item.put(doc.name);
            item.put(doc.dir);
            item.put(doc.size);
            out.put(item);
        }
        return out;
    }
}
