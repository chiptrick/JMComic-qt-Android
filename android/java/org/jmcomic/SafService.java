package org.jmcomic;

import android.app.Service;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.DocumentsContract;
import android.util.Log;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.Arrays;
import java.util.Comparator;

/**
 * 常驻在**本进程**里的 SAF 工作线程 —— Python 侧唯一的 Android API 入口。
 *
 * 为什么要有它(而不是直接 Python 调 Java)见 tools/saf_bridge.py 的模块注释：
 * 没有 pyjnius / QJniObject，只能靠"文件信箱"通信：
 *
 *     <appData>/saf/inbox/<reqId>.json   Python 写请求
 *     <appData>/saf/outbox/<reqId>.json  Java 写结果
 *
 * 本 Service 只做三件事：
 *   1. 轮询 inbox 取请求(100ms，空闲时退到 500ms)
 *   2. 在后台线程用 ContentResolver 干活(拷贝/列目录/打开目录)
 *   3. 需要界面(选文件/选目录)时，把活交给 SafPickActivity，自己不写结果
 *
 * 它由 Python 用 `am start-service` 拉起一次：Android 16 上 `am start` 启 Activity
 * 会被 assertPackageMatchesCallingUid 拦下(调用方包名被写死成 com.android.shell)，
 * 而 `am start-service --user 0` 是允许的 —— 这条路是实测可用的。
 */
public class SafService extends Service {

    private static final String TAG = "JmSaf";
    private static final int IdleSleepMs = 120;
    private static final int BusySleepMs = 20;

    private Thread worker = null;
    private volatile boolean running = false;
    private Handler main = null;

    @Override
    public void onCreate() {
        super.onCreate();
        main = new Handler(Looper.getMainLooper());
        // 数据面：Python 通过 127.0.0.1:<port> 直接读写 SAF 文档(见 SafIoServer)
        SafIoServer.Start(this);
        StartWorker();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        SafIoServer.Start(this);
        StartWorker();
        // 不 STICKY：进程被杀之后 inbox 里的老请求已经没有意义，
        // Python 侧下次要用会自己再 am start-service 一次
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void StartWorker() {
        if (worker != null && worker.isAlive()) {
            return;
        }
        running = true;
        worker = new Thread(new Runnable() {
            @Override
            public void run() {
                Loop();
            }
        }, "jm-saf");
        worker.setDaemon(true);
        worker.start();
        Log.i(TAG, "saf service ready");
    }

    private void Loop() {
        while (running) {
            boolean busy = false;
            try {
                File[] files = SafStore.InboxDir(this).listFiles();
                if (files != null && files.length > 0) {
                    Arrays.sort(files, new Comparator<File>() {
                        @Override
                        public int compare(File a, File b) {
                            return a.getName().compareTo(b.getName());
                        }
                    });
                    for (File file : files) {
                        if (!file.getName().endsWith(".json")) {
                            // 半截文件(Python 正在写)：下一轮再取
                            continue;
                        }
                        busy = true;
                        Handle(file);
                    }
                }
            } catch (Exception es) {
                Log.w(TAG, "saf loop: " + es);
            }
            try {
                Thread.sleep(busy ? BusySleepMs : IdleSleepMs);
            } catch (InterruptedException es) {
                break;
            }
        }
    }

    private void Handle(File file) {
        String text = null;
        try {
            text = ReadAll(file);
        } catch (Exception es) {
            Log.w(TAG, "read request failed: " + es);
        }
        // 先把文件挪走：处理失败也不会被无限重试
        try {
            file.delete();
        } catch (Exception ignore) {
        }
        if (text == null) {
            return;
        }
        String reqId = "";
        JSONObject request;
        try {
            request = new JSONObject(text);
            reqId = request.optString("id", "");
        } catch (Exception es) {
            Log.w(TAG, "bad request json: " + es);
            return;
        }
        String op = request.optString("op", "");
        Log.i(TAG, "saf op=" + op + " id=" + reqId);
        try {
            if ("pick".equals(op)) {
                // 结果由 SafPickActivity 写(它是唯一能收到 onActivityResult 的一方)
                StartPicker(reqId, request);
                return;
            }
            JSONObject result;
            if ("ping".equals(op)) {
                result = new JSONObject();
                result.put("ok", true);
                result.put("pid", android.os.Process.myPid());
            } else if ("open".equals(op)) {
                result = Open(request);
            } else if ("copyIn".equals(op)) {
                Uri uri = Uri.parse(request.optString("uri", ""));
                File target = new File(request.optString("to", ""));
                result = SafStore.CopyTreeIn(this, uri, target);
            } else if ("copyOut".equals(op)) {
                Uri uri = Uri.parse(request.optString("uri", ""));
                File source = new File(request.optString("from", ""));
                result = SafStore.CopyTreeOut(this, source, uri, request.optString("sub", ""));
            } else if ("writeFile".equals(op)) {
                Uri uri = Uri.parse(request.optString("uri", ""));
                File source = new File(request.optString("from", ""));
                result = SafStore.WriteFile(this, uri, source);
            } else if ("deleteTree".equals(op)) {
                // 给"导出后清理本地副本"预留：当前不用
                result = new JSONObject();
                result.put("ok", true);
            } else {
                result = SafStore.Fail(new Exception("unknown op: " + op));
            }
            SafStore.WriteResult(this, reqId, result);
        } catch (Throwable es) {
            Log.w(TAG, "saf op failed: " + es);
            SafStore.WriteResult(this, reqId, SafStore.Fail(es));
        }
    }

    private void StartPicker(final String reqId, final JSONObject request) {
        final String kind = request.optString("kind", "file");
        final String mime = request.optString("mime", "*/*");
        final String copyTo = request.optString("copyTo", "");
        final String defaultName = request.optString("defaultName", "");
        main.post(new Runnable() {
            @Override
            public void run() {
                try {
                    // 只带 NEW_TASK(从 Service 里起 Activity 必须) + 不要动画。
                    //
                    // **绝不能带 FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS**：SafPickActivity 与
                    // 主 QtActivity 同 affinity，NEW_TASK 会复用**同一个任务**，这个 flag
                    // 于是把整个应用任务标记成"不进多任务" —— 真机现象就是按 HOME 后
                    // 多任务列表里找不到本应用，但进程/Service 还在后台跑。
                    // 该 Activity 自己的"不出现"由清单里的
                    // android:excludeFromRecents + android:taskAffinity=""(独立任务)保证。
                    Intent intent = new Intent(SafService.this, SafPickActivity.class);
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                            | Intent.FLAG_ACTIVITY_NO_ANIMATION);
                    intent.putExtra("reqId", reqId);
                    intent.putExtra("kind", kind);
                    intent.putExtra("mime", mime);
                    intent.putExtra("copyTo", copyTo);
                    intent.putExtra("defaultName", defaultName);
                    startActivity(intent);
                } catch (Exception es) {
                    Log.w(TAG, "start pick activity failed: " + es);
                    SafStore.WriteResult(SafService.this, reqId, SafStore.Fail(es));
                }
            }
        });
    }

    /** 打开一个目录/文件给系统文件管理器(DocumentsUI 认 vnd.android.document/directory) */
    private JSONObject Open(JSONObject request) {
        String uriText = request.optString("uri", "");
        String path = request.optString("path", "");
        JSONObject out = new JSONObject();
        Uri uri = null;
        String mime;
        if (uriText.startsWith("content://")) {
            uri = Uri.parse(uriText);
            // tree uri 交给 DocumentsUI 只会停在存储根目录；换成"这棵树的根 document uri"
            // 才会直接进到用户选的那个文件夹
            try {
                if (DocumentsContract.isTreeUri(uri)) {
                    uri = DocumentsContract.buildDocumentUriUsingTree(
                            uri, DocumentsContract.getTreeDocumentId(uri));
                }
            } catch (Exception ignore) {
            }
            mime = DocumentsContract.Document.MIME_TYPE_DIR;
        } else if (path.length() > 0 && !SafStore.IsAppPrivate(this, path)) {
            // 不在应用专属目录里：file:// 交给文件管理器。别的应用没有读权限时
            // 由它自己报错 —— 但至少是"跳过去了"，不再是"点了没反应"
            uri = Uri.fromFile(new File(path));
            mime = new File(path).isDirectory()
                    ? DocumentsContract.Document.MIME_TYPE_DIR : SafStore.MimeOf(path);
        } else {
            try {
                out.put("ok", false);
                out.put("reason", "sandbox");
                out.put("path", path);
            } catch (Exception ignore) {
            }
            return out;
        }
        final Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                | Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        intent.setDataAndType(uri, mime);
        try {
            startActivity(intent);
            out.put("ok", true);
        } catch (ActivityNotFoundException es) {
            out = SafStore.Fail(es);
            try {
                out.put("reason", "no_handler");
            } catch (Exception ignore) {
            }
        } catch (Exception es) {
            out = SafStore.Fail(es);
        }
        return out;
    }

    private static String ReadAll(File file) throws Exception {
        InputStream in = new FileInputStream(file);
        try {
            byte[] buffer = new byte[(int) file.length()];
            int offset = 0;
            while (offset < buffer.length) {
                int len = in.read(buffer, offset, buffer.length - offset);
                if (len <= 0) {
                    break;
                }
                offset += len;
            }
            return new String(buffer, 0, offset, "UTF-8");
        } finally {
            in.close();
        }
    }
}
