package edu.uidaho.capstone.androidrunner.data;

import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkConfig;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.ManifestCodecSupport;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

public final class ManifestCodec {
    private ManifestCodec() {
    }

    public static String write(BenchmarkConfig config) throws JSONException {
        return ManifestCodecSupport.configToJson(config).toString(2) + "\n";
    }

    public static BenchmarkConfig read(String rawJson) throws JSONException {
        JSONObject root = new JSONObject(rawJson);
        BenchmarkConfig config = new BenchmarkConfig();
        config.tabId = root.optString("tab_id", config.tabId);
        config.inputMode = root.optString("input_mode", config.inputMode);
        config.graphFamily = root.optString("graph_family", config.graphFamily);
        config.iterations = Math.max(1, root.optInt("iterations", config.iterations));
        config.baseSeed = root.optLong("base_seed", config.baseSeed);
        config.parallelRequested = root.optBoolean("parallel_requested", config.parallelRequested);
        config.maxWorkers = Math.max(1, root.optInt("requested_workers", config.maxWorkers));
        config.solverTimeoutSeconds = root.optInt("solver_timeout_seconds", config.solverTimeoutSeconds);
        config.failurePolicy = root.optString("failure_policy", config.failurePolicy);
        config.retryFailedTrials = Math.max(0, root.optInt("retry_failed_trials", config.retryFailedTrials));
        config.timeoutAsMissing = root.optBoolean("timeout_as_missing", config.timeoutAsMissing);
        config.outlierFilter = root.optString("outlier_filter", config.outlierFilter);
        config.runMode = root.optString("run_mode", config.runMode);
        config.timeLimitMinutes = Math.max(1, root.optInt("time_limit_minutes", config.timeLimitMinutes));
        config.deleteGeneratedInputs = root.optBoolean("delete_generated_inputs", config.deleteGeneratedInputs);
        config.kMode = root.optString("k_mode", config.kMode);
        config.varyN = root.optBoolean("vary_n", config.varyN);
        config.varyK = root.optBoolean("vary_k", config.varyK);
        config.varyDensity = root.optBoolean("vary_density", config.varyDensity);

        readIntTriple(root.optJSONArray("n_values"), value -> {
            config.nStart = value[0];
            config.nEnd = value[1];
            config.nStep = value[2];
        });
        readIntTriple(root.optJSONArray("k_values"), value -> {
            config.kStart = value[0];
            config.kEnd = value[1];
            config.kStep = value[2];
        });
        JSONArray density = root.optJSONArray("density_values");
        if (density != null && density.length() >= 3) {
            config.densityStart = density.optDouble(0, config.densityStart);
            config.densityEnd = density.optDouble(1, config.densityEnd);
            config.densityStep = density.optDouble(2, config.densityStep);
        }

        config.selectedVariants.clear();
        JSONArray variants = root.optJSONArray("selected_variants");
        if (variants != null) {
            for (int i = 0; i < variants.length(); i++) {
                String value = variants.optString(i, "");
                if (!value.isEmpty()) config.selectedVariants.add(value);
            }
        }
        config.selectedDatasets.clear();
        JSONArray datasets = root.optJSONArray("selected_datasets");
        if (datasets != null) {
            for (int i = 0; i < datasets.length(); i++) {
                String value = datasets.optString(i, "");
                if (!value.isEmpty()) config.selectedDatasets.add(value);
            }
        }
        return config;
    }

    private interface IntTripleConsumer {
        void accept(int[] value);
    }

    private static void readIntTriple(JSONArray array, IntTripleConsumer consumer) {
        if (array == null || array.length() < 3) {
            return;
        }
        consumer.accept(new int[]{
                array.optInt(0),
                array.optInt(1),
                Math.max(1, array.optInt(2, 1))
        });
    }
}
