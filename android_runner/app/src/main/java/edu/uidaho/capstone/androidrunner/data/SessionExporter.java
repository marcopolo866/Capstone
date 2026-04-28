package edu.uidaho.capstone.androidrunner.data;

import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkDatapoint;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkSession;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkTrial;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.ManifestCodecSupport;

import org.json.JSONException;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.Locale;

public final class SessionExporter {
    private SessionExporter() {
    }

    public static void writeAll(BenchmarkSession session, File outputDir) throws IOException, JSONException {
        if (!outputDir.isDirectory() && !outputDir.mkdirs()) {
            throw new IOException("Unable to create output directory: " + outputDir);
        }
        writeText(new File(outputDir, "benchmark-session.json"), session.toJson().toString(2) + "\n");
        writeText(new File(outputDir, "benchmark-manifest.json"), ManifestCodecSupport.configToJson(session.config).toString(2) + "\n");
        writeDatapointsNdjson(session, new File(outputDir, "benchmark-datapoints.ndjson"));
        writeTrialsNdjson(session, new File(outputDir, "benchmark-trials.ndjson"));
        writeCsv(session, new File(outputDir, "benchmark-session.csv"));
    }

    private static void writeDatapointsNdjson(BenchmarkSession session, File path) throws IOException, JSONException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(path))) {
            for (BenchmarkDatapoint datapoint : session.datapoints) {
                writer.write(datapoint.toJson().toString());
                writer.write("\n");
            }
        }
    }

    private static void writeTrialsNdjson(BenchmarkSession session, File path) throws IOException, JSONException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(path))) {
            for (BenchmarkTrial trial : session.trials) {
                writer.write(trial.toJson().toString());
                writer.write("\n");
            }
        }
    }

    private static void writeCsv(BenchmarkSession session, File path) throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(path))) {
            writer.write("variant_id,variant_label,x_value,y_value,runtime_median_ms,runtime_stdev_ms,runtime_samples_n,memory_median_kb,memory_stdev_kb,memory_samples_n,completed_iterations,requested_iterations,answer_kind\n");
            for (BenchmarkDatapoint row : session.datapoints) {
                writer.write(csv(row.variantId));
                writer.write(",");
                writer.write(csv(row.variantLabel));
                writer.write(",");
                writer.write(format(row.xValue));
                writer.write(",");
                writer.write(row.yValue == null ? "" : format(row.yValue));
                writer.write(",");
                writer.write(row.runtimeMedianMs == null ? "" : format(row.runtimeMedianMs));
                writer.write(",");
                writer.write(format(row.runtimeStdevMs));
                writer.write(",");
                writer.write(Integer.toString(row.runtimeSamplesN));
                writer.write(",");
                writer.write(row.memoryMedianKb == null ? "" : format(row.memoryMedianKb));
                writer.write(",");
                writer.write(format(row.memoryStdevKb));
                writer.write(",");
                writer.write(Integer.toString(row.memorySamplesN));
                writer.write(",");
                writer.write(Integer.toString(row.completedIterations));
                writer.write(",");
                writer.write(Integer.toString(row.requestedIterations));
                writer.write(",");
                writer.write(csv(row.answerKind));
                writer.write("\n");
            }
        }
    }

    private static void writeText(File path, String text) throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(path))) {
            writer.write(text);
        }
    }

    private static String format(double value) {
        return String.format(Locale.US, "%.6f", value);
    }

    private static String csv(String value) {
        String raw = value == null ? "" : value;
        if (raw.contains(",") || raw.contains("\"") || raw.contains("\n")) {
            return "\"" + raw.replace("\"", "\"\"") + "\"";
        }
        return raw;
    }
}
