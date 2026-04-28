package edu.uidaho.capstone.androidrunner.data;

import android.content.Context;

import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.DatasetSpec;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public final class DatasetManager {
    private DatasetManager() {
    }

    public interface Progress {
        void onMessage(String message);
    }

    public static File datasetRoot(Context context) {
        return new File(context.getExternalFilesDir(null), "datasets");
    }

    public static File rawFile(Context context, DatasetSpec spec) {
        return new File(datasetRoot(context), spec.relativePath);
    }

    public static boolean rawReady(Context context, DatasetSpec spec) {
        File file = rawFile(context, spec);
        return file.isFile() && file.length() > 0;
    }

    public static File downloadRaw(Context context, DatasetSpec spec, Progress progress) throws IOException {
        File target = rawFile(context, spec);
        File parent = target.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("Unable to create dataset directory: " + parent);
        }
        if (rawReady(context, spec)) {
            if (progress != null) progress.onMessage("Dataset already downloaded: " + spec.datasetId);
            return target;
        }
        if (progress != null) progress.onMessage("Downloading " + spec.name + "...");
        HttpURLConnection conn = (HttpURLConnection) new URL(spec.downloadUrl).openConnection();
        conn.setConnectTimeout(30_000);
        conn.setReadTimeout(60_000);
        conn.setRequestProperty("User-Agent", "capstone-android-benchmark-runner/0.1");
        conn.connect();
        int code = conn.getResponseCode();
        if (code < 200 || code >= 300) {
            throw new IOException("Dataset download failed with HTTP " + code + ": " + spec.downloadUrl);
        }
        File tmp = new File(target.getAbsolutePath() + ".part");
        long total = 0L;
        try (InputStream in = conn.getInputStream(); FileOutputStream out = new FileOutputStream(tmp)) {
            byte[] buffer = new byte[64 * 1024];
            int read;
            while ((read = in.read(buffer)) >= 0) {
                out.write(buffer, 0, read);
                total += read;
                if (progress != null && total % (4L * 1024L * 1024L) < buffer.length) {
                    progress.onMessage("Downloaded " + (total / (1024 * 1024)) + " MiB for " + spec.datasetId);
                }
            }
        } finally {
            conn.disconnect();
        }
        if (!tmp.renameTo(target)) {
            throw new IOException("Unable to publish downloaded dataset file: " + target);
        }
        if (progress != null) progress.onMessage("Downloaded dataset raw file: " + target.getAbsolutePath());
        return target;
    }
}
