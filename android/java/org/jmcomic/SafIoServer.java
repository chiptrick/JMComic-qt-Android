package org.jmcomic;

import android.content.Context;
import android.net.Uri;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 本机回环 IO 通道 —— Python 直接读写 SAF 目录的"数据面"。
 *
 * 为什么需要它
 * ------------
 * 用户把下载路径选成某个目录之后，下载过程中的每个文件都必须**直接落在那 个目录**
 * 里。而 SAF 给的是 content:// URI，Python 没有 pyjnius / QJniObject，碰不到
 * ContentResolver；用文件信箱传二进制(JSON + base64)会把字节先写进私有目录，
 * 既违背"文件始终在目标目录"，也白白多一次落盘。
 *
 * 所以这里开一个 127.0.0.1 上的 socket：
 *
 *     请求(一行 JSON)   {"op":"write","uri":"content://…","rel":"commies/x/1.jpg","size":12345}
 *                      然后是正好 size 字节的原始数据
 *     应答(一行 JSON)   {"ok":true,"size":12345}
 *
 * 读同理：应答头之后跟 N 字节原始数据。列表/stat/删除这类没有大数据的走同一个
 * socket，只是应答里多几个字段。全程**不落地临时文件**。
 *
 * 端口写在 &lt;filesDir&gt;/saf/io.port (内容和文件 mtime 一起变)，Python 侧连不上
 * 就 am start-service 拉起本 Service 再重连。
 *
 * 大文件是一次 64KB 的循环拷贝，一本漫画几百页也就几十毫秒一页。
 */
public final class SafIoServer {

    private static final String TAG = "JmSafIo";
    /** 请求头上限：正常只有几百字节，留足余量防畸形请求 */
    private static final int MaxHeader = 64 * 1024;
    private static final int PortFileVersion = 1;

    private static final Object Lock = new Object();
    private static boolean started = false;
    private static ServerSocket server = null;
    private static ExecutorService pool = null;

    private SafIoServer() {
    }

    public static synchronized void Start(Context context) {
        if (started) {
            return;
        }
        started = true;
        final Context app = context.getApplicationContext();
        try {
            server = new ServerSocket(0, 32, InetAddress.getByName("127.0.0.1"));
            WritePort(app, server.getLocalPort());
            pool = Executors.newFixedThreadPool(4);
            Thread thread = new Thread(new Runnable() {
                @Override
                public void run() {
                    AcceptLoop(app);
                }
            }, "jm-saf-io");
            thread.setDaemon(true);
            thread.start();
            Log.i(TAG, "saf io ready: port=" + server.getLocalPort());
        } catch (Exception es) {
            started = false;
            Log.w(TAG, "saf io start failed: " + es);
        }
    }

    private static void WritePort(Context context, int port) throws Exception {
        java.io.File dir = new java.io.File(context.getFilesDir(), "saf");
        dir.mkdirs();
        java.io.File tmp = new java.io.File(dir, "io.port.tmp");
        java.io.File out = new java.io.File(dir, "io.port");
        OutputStream stream = new java.io.FileOutputStream(tmp);
        try {
            stream.write((PortFileVersion + "\n" + port + "\n").getBytes("UTF-8"));
            stream.flush();
        } finally {
            stream.close();
        }
        if (!tmp.renameTo(out)) {
            out.delete();
            tmp.renameTo(out);
        }
    }

    private static void AcceptLoop(Context context) {
        while (true) {
            try {
                final Socket socket = server.accept();
                socket.setSoTimeout(120000);
                socket.setTcpNoDelay(true);
                if (pool != null) {
                    pool.execute(new Runnable() {
                        @Override
                        public void run() {
                            Handle(context, socket);
                        }
                    });
                } else {
                    socket.close();
                }
            } catch (Exception es) {
                Log.w(TAG, "accept: " + es);
                try {
                    Thread.sleep(200);
                } catch (InterruptedException ignore) {
                    break;
                }
            }
        }
    }

    private static void Handle(Context context, Socket socket) {
        try {
            BufferedInputStream in = new BufferedInputStream(socket.getInputStream(), 64 * 1024);
            OutputStream raw = socket.getOutputStream();
            BufferedOutputStream out = new BufferedOutputStream(raw, 64 * 1024);
            String line = ReadLine(in);
            if (line == null) {
                return;
            }
            JSONObject request = new JSONObject(line);
            String op = request.optString("op", "");
            Uri tree = Uri.parse(request.optString("uri", ""));
            String rel = request.optString("rel", "");
            JSONObject result;
            if ("ping".equals(op)) {
                result = new JSONObject();
                result.put("ok", true);
                result.put("pid", android.os.Process.myPid());
            } else if ("write".equals(op)) {
                long size = request.optLong("size", -1);
                long written = SafStore.WriteStream(context, tree, rel, in, size);
                result = new JSONObject();
                result.put("ok", written == size || size < 0);
                result.put("size", written);
            } else if ("read".equals(op)) {
                // 先把长度告诉对方，再灌数据(对方按长度读，不用等 EOF)
                java.io.ByteArrayOutputStream probe = new java.io.ByteArrayOutputStream();
                long size = SafStore.ReadStream(context, tree, rel, probe);
                if (size < 0) {
                    result = new JSONObject();
                    result.put("ok", false);
                    result.put("missing", true);
                } else {
                    result = new JSONObject();
                    result.put("ok", true);
                    result.put("size", size);
                    WriteLine(out, result);
                    out.write(probe.toByteArray());
                    out.flush();
                    return;
                }
            } else if ("stat".equals(op)) {
                SafStore.Doc doc = SafStore.FindRel(context, tree, rel);
                result = new JSONObject();
                result.put("ok", true);
                result.put("exists", doc != null);
                result.put("dir", doc != null && doc.dir);
                result.put("size", doc == null ? 0 : doc.size);
            } else if ("list".equals(op)) {
                result = new JSONObject();
                result.put("ok", true);
                result.put("items", SafStore.ListRel(context, tree, rel));
            } else if ("mkdirs".equals(op)) {
                SafStore.EnsureDirRel(context, tree, rel);
                result = new JSONObject();
                result.put("ok", true);
            } else if ("doc".equals(op)) {
                // 相对路径 -> document uri("打开目录"要用它把文件管理器直接定位进去)
                SafStore.Doc doc = SafStore.FindRel(context, tree, rel);
                if (doc == null) {
                    result = new JSONObject();
                    result.put("ok", false);
                    result.put("missing", true);
                } else {
                    result = new JSONObject();
                    result.put("ok", true);
                    result.put("uri", doc.uri.toString());
                }
            } else if ("delete".equals(op)) {
                result = SafStore.DeleteRel(context, tree, rel);
            } else {
                result = new JSONObject();
                result.put("ok", false);
                result.put("error", "unknown op: " + op);
            }
            WriteLine(out, result);
            out.flush();
        } catch (Exception es) {
            Log.w(TAG, "io handle: " + es);
        } finally {
            try {
                socket.close();
            } catch (Exception ignore) {
            }
        }
    }

    private static void WriteLine(OutputStream out, JSONObject obj) throws Exception {
        out.write(obj.toString().getBytes("UTF-8"));
        out.write('\n');
    }

    private static String ReadLine(InputStream in) throws Exception {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream(512);
        while (buffer.size() < MaxHeader) {
            int value = in.read();
            if (value < 0) {
                break;
            }
            if (value == '\n') {
                break;
            }
            buffer.write(value);
        }
        if (buffer.size() == 0) {
            return null;
        }
        return new String(buffer.toByteArray(), "UTF-8");
    }
}
