package edu.uidaho.capstone.androidrunner.model;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public final class BenchmarkModels {
    private BenchmarkModels() {
    }

    public static final class SolverVariant {
        public final String variantId;
        public final String label;
        public final String tabId;
        public final String family;
        public final String role;

        public SolverVariant(String variantId, String label, String tabId, String family, String role) {
            this.variantId = variantId;
            this.label = label;
            this.tabId = tabId;
            this.family = family;
            this.role = role;
        }

        public boolean isBaseline() {
            return "baseline".equals(role);
        }
    }

    public static final class DatasetSpec {
        public final String datasetId;
        public final String name;
        public final String tabId;
        public final String source;
        public final String sourceUrl;
        public final String rawFormat;
        public final String description;
        public final long estimatedSizeBytes;
        public final String downloadUrl;
        public final String relativePath;

        public DatasetSpec(
                String datasetId,
                String name,
                String tabId,
                String source,
                String sourceUrl,
                String rawFormat,
                String description,
                long estimatedSizeBytes,
                String downloadUrl,
                String relativePath
        ) {
            this.datasetId = datasetId;
            this.name = name;
            this.tabId = tabId;
            this.source = source;
            this.sourceUrl = sourceUrl;
            this.rawFormat = rawFormat;
            this.description = description;
            this.estimatedSizeBytes = estimatedSizeBytes;
            this.downloadUrl = downloadUrl;
            this.relativePath = relativePath;
        }
    }

    public static final class BenchmarkConfig {
        public String tabId = "subgraph";
        public String inputMode = "independent";
        public String graphFamily = "random_density";
        public final List<String> selectedVariants = new ArrayList<>();
        public final List<String> selectedDatasets = new ArrayList<>();
        public int iterations = 1;
        public long baseSeed = 424242L;
        public boolean randomSeed = true;
        public int maxWorkers = 1;
        public boolean parallelRequested = false;
        public int solverTimeoutSeconds = 0;
        public String failurePolicy = "continue";
        public int retryFailedTrials = 0;
        public boolean timeoutAsMissing = true;
        public String outlierFilter = "none";
        public String runMode = "threshold";
        public int timeLimitMinutes = 1;
        public boolean deleteGeneratedInputs = true;
        public String kMode = "absolute";
        public int nStart = 10;
        public int nEnd = 10;
        public int nStep = 1;
        public int kStart = 5;
        public int kEnd = 5;
        public int kStep = 1;
        public double densityStart = 0.01;
        public double densityEnd = 0.01;
        public double densityStep = 0.01;
        public boolean varyN = true;
        public boolean varyK = false;
        public boolean varyDensity = false;
    }

    public static final class BenchmarkTrial {
        public String status = "ok";
        public int pointIndex;
        public int iterationIndex;
        public long seed;
        public String variantId = "";
        public String family = "";
        public double runtimeMs;
        public double peakKb;
        public int returnCode;
        public String stdout = "";
        public String stderr = "";
        public String answerKind = "";
        public String answerValue = "";
        public long solutionCount = -1;
        public String distance = "";
        public int pathLength = -1;

        public JSONObject toJson() throws JSONException {
            JSONObject normalized = new JSONObject()
                    .put("answer_kind", answerKind)
                    .put("answer_value", answerValue)
                    .put("solution_count", solutionCount >= 0 ? solutionCount : JSONObject.NULL)
                    .put("distance", distance)
                    .put("path_length", pathLength >= 0 ? pathLength : JSONObject.NULL);
            return new JSONObject()
                    .put("schema_version", "android-benchmark-trial-v1")
                    .put("status", status)
                    .put("point_index", pointIndex)
                    .put("iteration_index", iterationIndex)
                    .put("seed", seed)
                    .put("variant_id", variantId)
                    .put("family", family)
                    .put("runtime_ms", runtimeMs)
                    .put("peak_kb", peakKb)
                    .put("return_code", returnCode)
                    .put("stdout", stdout)
                    .put("stderr", stderr)
                    .put("normalized_result", normalized);
        }
    }

    public static final class BenchmarkDatapoint {
        public String variantId = "";
        public String variantLabel = "";
        public double xValue;
        public Double yValue;
        public String pointLabel = "";
        public Double runtimeMedianMs;
        public double runtimeStdevMs;
        public int runtimeSamplesN;
        public Double memoryMedianKb;
        public double memoryStdevKb;
        public int memorySamplesN;
        public int completedIterations;
        public int requestedIterations;
        public String answerKind = "";
        public Double pathLengthMedian;
        public final List<Long> seeds = new ArrayList<>();
        public final List<Double> runtimeSamplesMs = new ArrayList<>();
        public final List<Double> memorySamplesKb = new ArrayList<>();

        public JSONObject toJson() throws JSONException {
            JSONArray seedArray = new JSONArray();
            for (Long seed : seeds) seedArray.put(seed);
            JSONArray runtimeArray = new JSONArray();
            for (Double value : runtimeSamplesMs) runtimeArray.put(value);
            JSONArray memoryArray = new JSONArray();
            for (Double value : memorySamplesKb) memoryArray.put(value);
            return new JSONObject()
                    .put("variant_id", variantId)
                    .put("variant_label", variantLabel)
                    .put("dataset_id", JSONObject.NULL)
                    .put("dataset_name", JSONObject.NULL)
                    .put("x_value", xValue)
                    .put("y_value", yValue == null ? JSONObject.NULL : yValue)
                    .put("point_label", pointLabel)
                    .put("runtime_median_ms", runtimeMedianMs == null ? JSONObject.NULL : runtimeMedianMs)
                    .put("runtime_stdev_ms", runtimeStdevMs)
                    .put("runtime_samples_n", runtimeSamplesN)
                    .put("memory_median_kb", memoryMedianKb == null ? JSONObject.NULL : memoryMedianKb)
                    .put("memory_stdev_kb", memoryStdevKb)
                    .put("memory_samples_n", memorySamplesN)
                    .put("completed_iterations", completedIterations)
                    .put("requested_iterations", requestedIterations)
                    .put("seeds", seedArray)
                    .put("runtime_samples_ms", runtimeArray)
                    .put("memory_samples_kb", memoryArray)
                    .put("answer_kind", answerKind)
                    .put("path_length_median", pathLengthMedian == null ? JSONObject.NULL : pathLengthMedian);
        }
    }

    public static final class BenchmarkSession {
        public String createdAtUtc = "";
        public String runStartedUtc = "";
        public String runEndedUtc = "";
        public double runDurationMs;
        public int completedTrials;
        public int plannedTrials;
        public BenchmarkConfig config;
        public final List<BenchmarkDatapoint> datapoints = new ArrayList<>();
        public final List<BenchmarkTrial> trials = new ArrayList<>();

        public JSONObject toJson() throws JSONException {
            JSONArray points = new JSONArray();
            for (BenchmarkDatapoint datapoint : datapoints) points.put(datapoint.toJson());
            JSONArray trialRows = new JSONArray();
            for (BenchmarkTrial trial : trials) trialRows.put(trial.toJson());
            return new JSONObject()
                    .put("schema_version", "android-benchmark-v1")
                    .put("created_at_utc", createdAtUtc)
                    .put("run_started_utc", runStartedUtc)
                    .put("run_ended_utc", runEndedUtc)
                    .put("run_duration_ms", runDurationMs)
                    .put("completed_trials", completedTrials)
                    .put("planned_trials", plannedTrials)
                    .put("run_config", ManifestCodecSupport.configToJson(config))
                    .put("datapoints", points)
                    .put("trials", trialRows);
        }
    }

    public static final class ManifestCodecSupport {
        private ManifestCodecSupport() {
        }

        public static JSONObject configToJson(BenchmarkConfig config) throws JSONException {
            JSONArray variants = new JSONArray();
            for (String variant : config.selectedVariants) variants.put(variant);
            JSONArray datasets = new JSONArray();
            for (String dataset : config.selectedDatasets) datasets.put(dataset);
            return new JSONObject()
                    .put("schema_version", "capstone-benchmark-manifest-v1")
                    .put("platform", "android")
                    .put("tab_id", config.tabId)
                    .put("input_mode", config.inputMode)
                    .put("graph_family", config.graphFamily)
                    .put("selected_variants", variants)
                    .put("selected_datasets", datasets)
                    .put("iterations", config.iterations)
                    .put("base_seed", config.baseSeed)
                    .put("parallel_requested", config.parallelRequested)
                    .put("requested_workers", config.maxWorkers)
                    .put("solver_timeout_seconds", config.solverTimeoutSeconds <= 0 ? JSONObject.NULL : config.solverTimeoutSeconds)
                    .put("failure_policy", config.failurePolicy)
                    .put("retry_failed_trials", config.retryFailedTrials)
                    .put("timeout_as_missing", config.timeoutAsMissing)
                    .put("outlier_filter", config.outlierFilter)
                    .put("run_mode", config.runMode)
                    .put("time_limit_minutes", config.timeLimitMinutes)
                    .put("delete_generated_inputs", config.deleteGeneratedInputs)
                    .put("k_mode", config.kMode)
                    .put("n_values", new JSONArray().put(config.nStart).put(config.nEnd).put(config.nStep))
                    .put("k_values", new JSONArray().put(config.kStart).put(config.kEnd).put(config.kStep))
                    .put("density_values", new JSONArray().put(config.densityStart).put(config.densityEnd).put(config.densityStep))
                    .put("vary_n", config.varyN)
                    .put("vary_k", config.varyK)
                    .put("vary_density", config.varyDensity);
        }
    }
}
