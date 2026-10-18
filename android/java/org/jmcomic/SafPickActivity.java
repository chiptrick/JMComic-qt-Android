package org.jmcomic;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;

import org.json.JSONObject;

import java.io.File;

/**
 * 一个**看不见的**中转 Activity：替 SafService 弹出系统 SAF 选择器并接回结果。
 *
 * 为什么必须有自己的 Activity：
 *   * SAF 的 ACTION_OPEN_DOCUMENT / ACTION_OPEN_DOCUMENT_TREE 只认
 *     startActivityForResult，结果只回到**调用它的那个 Activity** 的 onActivityResult；
 *     Service 收不到回调。
 *   * 所以 Service 拉起本 Activity，本 Activity 转手拉起 SAF，拿到结果后写进
 *     文件信箱(SafStore.WriteResult)再 finish()。
 *
 * 主题是 Theme.Translucent.NoTitleBar + noHistory + excludeFromRecents + taskAffinity=""：
 * 用户完全看不到这一层，屏幕上就是"主界面 -> 系统文件选择器 -> 主界面"。
 */
public class SafPickActivity extends Activity {

    private static final String TAG = "JmSaf";
    private static final int RequestCode = 0x4A4D;

    private String reqId = "";
    private String kind = "file";
    private String copyTo = "";
    private boolean finished = false;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Intent intent = getIntent();
        if (intent == null) {
            Finish(SafStore.Cancel());
            return;
        }
        reqId = Safe(intent.getStringExtra("reqId"));
        kind = Safe(intent.getStringExtra("kind"));
        copyTo = Safe(intent.getStringExtra("copyTo"));
        String mime = Safe(intent.getStringExtra("mime"));
        String defaultName = Safe(intent.getStringExtra("defaultName"));
        if (mime.length() == 0) {
            mime = "*/*";
        }
        try {
            Intent picker;
            if ("tree".equals(kind)) {
                picker = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
                picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                        | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
            } else if ("save".equals(kind)) {
                picker = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                picker.addCategory(Intent.CATEGORY_OPENABLE);
                picker.setType(mime);
                picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
                if (defaultName.length() > 0) {
                    picker.putExtra(Intent.EXTRA_TITLE, defaultName);
                }
            } else {
                picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                picker.addCategory(Intent.CATEGORY_OPENABLE);
                picker.setType(mime);
                picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
            }
            startActivityForResult(picker, RequestCode);
        } catch (Exception es) {
            Log.w(TAG, "start saf picker failed: " + es);
            JSONObject out = SafStore.Fail(es);
            try {
                out.put("reason", "no_picker");
            } catch (Exception ignore) {
            }
            Finish(out);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != RequestCode) {
            return;
        }
        Uri uri = data == null ? null : data.getData();
        if (resultCode != RESULT_OK || uri == null) {
            Finish(SafStore.Cancel());
            return;
        }
        try {
            // 长期授权：否则重启后 tree uri 就失效了(下载目录要一直写)
            int flags = data.getFlags()
                    & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            try {
                getContentResolver().takePersistableUriPermission(uri, flags);
            } catch (Exception es) {
                Log.w(TAG, "takePersistableUriPermission failed: " + es);
            }
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("uri", uri.toString());
            out.put("name", SafStore.DisplayName(this, uri));
            if (copyTo.length() > 0 && !"tree".equals(kind)) {
                // 单文件选择：直接把内容拷到应用可读的目录，返回本地路径
                File target = SafStore.CopyToDir(this, uri, new File(copyTo),
                        SafStore.DisplayName(this, uri));
                if (target != null) {
                    out.put("path", target.getAbsolutePath());
                }
            }
            Finish(out);
        } catch (Exception es) {
            Log.w(TAG, "saf pick failed: " + es);
            Finish(SafStore.Fail(es));
        }
    }

    @Override
    protected void onDestroy() {
        // 用户在选择器里按返回、或系统把这一层回收掉：调用方不能一直等下去
        if (!finished) {
            Finish(SafStore.Cancel());
        }
        super.onDestroy();
    }

    private void Finish(JSONObject result) {
        if (finished) {
            return;
        }
        finished = true;
        try {
            SafStore.WriteResult(this, reqId, result);
        } catch (Exception ignore) {
        }
        try {
            finish();
        } catch (Exception ignore) {
        }
    }

    private static String Safe(String value) {
        return value == null ? "" : value;
    }
}
