package edu.uidaho.capstone.androidrunner.engine;

import android.content.Context;

import edu.uidaho.capstone.androidrunner.data.SolverCatalog;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkConfig;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkDatapoint;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkSession;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkTrial;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.SolverVariant;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

public final class BenchmarkEngine {
    public interface Listener {
        void onLog(String message);
        void onProgress(int completed, int planned, String label);
        void onGraphInputs(GeneratedInputs inputs, int pointIndex, int iterationIndex, long seed);
        void onComplete(BenchmarkSession session, File outputDir);
        void onError(Exception error);
    }

    private final Context appContext;
    private final NativeSolverBridge solverBridge = new NativeSolverBridge();
    private final Object pauseLock = new Object();
    private volatile boolean abortRequested;
    private volatile boolean pauseRequested;
    private Thread workerThread;

    public BenchmarkEngine(Context context) {
        this.appContext = context.getApplicationContext();
    }

    public boolean isRunning() {
        Thread thread = workerThread;
        return thread != null && thread.isAlive();
    }

    public void start(BenchmarkConfig config, Listener listener) {
        if (isRunning()) {
            listener.onError(new IllegalStateException("A benchmark run is already active."));
            return;
        }
        abortRequested = false;
        pauseRequested = false;
        BenchmarkConfig runConfig = copyConfig(config);
        injectBaselines(runConfig);
        workerThread = new Thread(() -> execute(runConfig, listener), "android-benchmark-engine");
        workerThread.start();
    }

    public void requestAbort() {
        abortRequested = true;
        resume();
    }

    public void pause() {
        pauseRequested = true;
    }

    public void resume() {
        synchronized (pauseLock) {
            pauseRequested = false;
            pauseLock.notifyAll();
        }
    }

    private void execute(BenchmarkConfig config, Listener listener) {
        String started = utcNow();
        long startNs = System.nanoTime();
        File outputDir = new File(appContext.getExternalFilesDir(null), "benchmark_output_" + timestampForPath());
        File generatedRoot = new File(outputDir, "generated_inputs");
        if (!generatedRoot.mkdirs() && !generatedRoot.isDirectory()) {
            listener.onError(new IllegalStateException("Unable to create output directory: " + outputDir));
            return;
        }

        try {
            Map<String, SolverVariant> variantsById = variantsById();
            List<Point> points = buildPoints(config);
            int plannedTrials = points.size() * config.selectedVariants.size() * config.iterations;
            if ("timed".equals(config.runMode)) {
                plannedTrials = 0;
            }
            BenchmarkSession session = new BenchmarkSession();
            session.config = config;
            session.runStartedUtc = started;
            session.createdAtUtc = started;
            session.plannedTrials = plannedTrials;
            int completed = 0;
            long deadlineNs = "timed".equals(config.runMode)
                    ? startNs + Math.max(1, config.timeLimitMinutes) * 60L * 1_000_000_000L
                    : Long.MAX_VALUE;

            for (int pointIndex = 0; pointIndex < points.size(); pointIndex++) {
                if (abortRequested || System.nanoTime() >= deadlineNs) break;
                Point point = points.get(pointIndex);
                listener.onLog("Datapoint " + (pointIndex + 1) + "/" + points.size() + ": " + point.label);
                Map<String, List<BenchmarkTrial>> trialsByVariant = new LinkedHashMap<>();
                for (String variantId : config.selectedVariants) {
                    trialsByVariant.put(variantId, new ArrayList<>());
                }
                for (int iter = 0; iter < config.iterations; iter++) {
                    waitIfPaused();
                    if (abortRequested || System.nanoTime() >= deadlineNs) break;
                    long seed = Math.max(1L, (config.baseSeed + pointIndex + iter) % 2_147_483_647L);
                    File pointDir = new File(generatedRoot, String.format(Locale.US, "point_%05d/iter_%03d", pointIndex + 1, iter + 1));
                    GeneratedInputs inputs = generateForPoint(config, point, pointDir, seed);
                    inputs.n = point.n;
                    inputs.k = point.k;
                    inputs.density = point.density;
                    inputs.pointIndex = pointIndex;
                    inputs.iterationIndex = iter;
                    inputs.seed = seed;
                    listener.onGraphInputs(inputs, pointIndex, iter, seed);
                    for (String variantId : config.selectedVariants) {
                        waitIfPaused();
                        if (abortRequested || System.nanoTime() >= deadlineNs) break;
                        SolverVariant variant = variantsById.get(variantId);
                        if (variant == null) continue;
                        BenchmarkTrial trial = runWithRetries(config, variant, inputs, pointIndex, iter, seed);
                        trialsByVariant.get(variantId).add(trial);
                        session.trials.add(trial);
                        completed++;
                        listener.onProgress(completed, plannedTrials, variant.label);
                        if (!"ok".equals(trial.status)) {
                            listener.onLog(variant.label + " failed: " + trial.stderr);
                            if ("stop".equals(config.failurePolicy)) {
                                abortRequested = true;
                            }
                        }
                    }
                }
                session.datapoints.addAll(finalizePoint(config, point, trialsByVariant, variantsById));
            }
            session.completedTrials = completed;
            session.runEndedUtc = utcNow();
            session.runDurationMs = (System.nanoTime() - startNs) / 1_000_000.0;
            listener.onComplete(session, outputDir);
        } catch (Exception exc) {
            listener.onError(exc);
        }
    }

    private BenchmarkTrial runWithRetries(BenchmarkConfig config, SolverVariant variant, GeneratedInputs inputs, int pointIndex, int iter, long seed) {
        BenchmarkTrial last = null;
        int attempts = Math.max(1, config.retryFailedTrials + 1);
        for (int attempt = 0; attempt < attempts; attempt++) {
            last = solverBridge.run(variant, inputs, pointIndex, iter, seed);
            if ("ok".equals(last.status)) break;
        }
        return last;
    }

    private GeneratedInputs generateForPoint(BenchmarkConfig config, Point point, File dir, long seed) throws Exception {
        if ("shortest_path".equals(config.tabId)) {
            String family = "dijkstra";
            for (String id : config.selectedVariants) {
                if (id.startsWith("sp_via")) {
                    family = "sp_via";
                    break;
                }
            }
            return GraphGenerator.generateShortest(dir, family, point.n, point.density, seed, config.graphFamily);
        }
        return GraphGenerator.generateSubgraph(dir, point.n, point.k, point.density, seed, config.graphFamily);
    }

    private List<BenchmarkDatapoint> finalizePoint(
            BenchmarkConfig config,
            Point point,
            Map<String, List<BenchmarkTrial>> trialsByVariant,
            Map<String, SolverVariant> variantsById
    ) {
        List<BenchmarkDatapoint> rows = new ArrayList<>();
        for (String variantId : config.selectedVariants) {
            List<BenchmarkTrial> trials = trialsByVariant.get(variantId);
            SolverVariant variant = variantsById.get(variantId);
            BenchmarkDatapoint row = new BenchmarkDatapoint();
            row.variantId = variantId;
            row.variantLabel = variant == null ? variantId : variant.label;
            row.xValue = point.x;
            row.yValue = point.y;
            row.pointLabel = point.label;
            row.requestedIterations = config.iterations;
            for (BenchmarkTrial trial : trials) {
                row.seeds.add(trial.seed);
                if ("ok".equals(trial.status)) {
                    row.runtimeSamplesMs.add(trial.runtimeMs);
                    row.memorySamplesKb.add(trial.peakKb);
                    row.completedIterations++;
                    row.answerKind = trial.answerKind;
                }
            }
            row.runtimeMedianMs = Stats.median(row.runtimeSamplesMs);
            row.runtimeStdevMs = Stats.stdev(row.runtimeSamplesMs);
            row.runtimeSamplesN = row.runtimeSamplesMs.size();
            row.memoryMedianKb = Stats.median(row.memorySamplesKb);
            row.memoryStdevKb = Stats.stdev(row.memorySamplesKb);
            row.memorySamplesN = row.memorySamplesKb.size();
            rows.add(row);
        }
        return rows;
    }

    private static List<Point> buildPoints(BenchmarkConfig config) {
        List<Integer> ns = config.varyN ? intRange(config.nStart, config.nEnd, config.nStep) : single(config.nStart);
        List<Integer> ks = "subgraph".equals(config.tabId) && config.varyK ? intRange(config.kStart, config.kEnd, config.kStep) : single(config.kStart);
        List<Double> densities = config.varyDensity ? doubleRange(config.densityStart, config.densityEnd, config.densityStep) : single(config.densityStart);
        List<Point> points = new ArrayList<>();
        boolean percentK = "percent".equals(config.kMode);
        for (double density : densities) {
            for (int k : ks) {
                for (int n : ns) {
                    Point p = new Point();
                    p.n = Math.max("subgraph".equals(config.tabId) ? 3 : 2, n);
                    int kNodes = percentK ? (int) Math.round((Math.max(0.000001, Math.min(100.0, k)) / 100.0) * p.n) : k;
                    p.k = Math.max(2, Math.min(kNodes, p.n - 1));
                    p.density = Math.max(0.000001, Math.min(1.0, density));
                    double kAxis = percentK ? k : p.k;
                    p.x = config.varyN ? p.n : (config.varyK ? kAxis : p.density);
                    p.y = selectedVarCount(config) > 1 ? (config.varyDensity ? p.density : (config.varyK ? kAxis : null)) : null;
                    String kLabel = percentK ? ", k=" + p.k + " (" + k + "%)" : ", k=" + p.k;
                    p.label = "n=" + p.n + ("subgraph".equals(config.tabId) ? kLabel : "") + ", density=" + String.format(Locale.US, "%.4f", p.density);
                    points.add(p);
                }
            }
        }
        return points;
    }

    private static int selectedVarCount(BenchmarkConfig config) {
        int count = 0;
        if (config.varyN) count++;
        if (config.varyK) count++;
        if (config.varyDensity) count++;
        return count;
    }

    private static List<Integer> intRange(int start, int end, int step) {
        List<Integer> out = new ArrayList<>();
        int s = Math.max(1, step);
        if (end < start) end = start;
        for (int v = start; v <= end; v += s) out.add(v);
        return out;
    }

    private static List<Integer> single(int value) {
        List<Integer> out = new ArrayList<>();
        out.add(value);
        return out;
    }

    private static List<Double> doubleRange(double start, double end, double step) {
        List<Double> out = new ArrayList<>();
        double s = step <= 0.0 ? 0.01 : step;
        if (end < start) end = start;
        for (double v = start; v <= end + 1e-12; v += s) out.add(v);
        return out;
    }

    private static List<Double> single(double value) {
        List<Double> out = new ArrayList<>();
        out.add(value);
        return out;
    }

    private void waitIfPaused() throws InterruptedException {
        synchronized (pauseLock) {
            while (pauseRequested && !abortRequested) {
                pauseLock.wait(100L);
            }
        }
    }

    private static void injectBaselines(BenchmarkConfig config) {
        List<String> toAdd = new ArrayList<>();
        for (String id : config.selectedVariants) {
            if (id.startsWith("dijkstra") && !config.selectedVariants.contains("dijkstra_baseline")) toAdd.add("dijkstra_baseline");
            if (id.startsWith("sp_via") && !config.selectedVariants.contains("sp_via_baseline")) toAdd.add("sp_via_baseline");
            if (id.startsWith("vf3") && !config.selectedVariants.contains("vf3_baseline")) toAdd.add("vf3_baseline");
            if (id.startsWith("glasgow") && !config.selectedVariants.contains("glasgow_baseline")) toAdd.add("glasgow_baseline");
        }
        for (String id : toAdd) {
            if (!config.selectedVariants.contains(id)) config.selectedVariants.add(0, id);
        }
    }

    private static Map<String, SolverVariant> variantsById() {
        Map<String, SolverVariant> out = new LinkedHashMap<>();
        for (SolverVariant variant : SolverCatalog.all()) out.put(variant.variantId, variant);
        return out;
    }

    private static BenchmarkConfig copyConfig(BenchmarkConfig input) {
        BenchmarkConfig c = new BenchmarkConfig();
        c.tabId = input.tabId;
        c.inputMode = input.inputMode;
        c.graphFamily = input.graphFamily;
        c.selectedVariants.addAll(input.selectedVariants);
        c.selectedDatasets.addAll(input.selectedDatasets);
        c.iterations = input.iterations;
        c.baseSeed = input.randomSeed ? (System.currentTimeMillis() & 0x7fffffffL) : input.baseSeed;
        c.randomSeed = input.randomSeed;
        c.maxWorkers = input.maxWorkers;
        c.parallelRequested = input.parallelRequested;
        c.solverTimeoutSeconds = input.solverTimeoutSeconds;
        c.failurePolicy = input.failurePolicy;
        c.retryFailedTrials = input.retryFailedTrials;
        c.timeoutAsMissing = input.timeoutAsMissing;
        c.outlierFilter = input.outlierFilter;
        c.runMode = input.runMode;
        c.timeLimitMinutes = input.timeLimitMinutes;
        c.deleteGeneratedInputs = input.deleteGeneratedInputs;
        c.kMode = input.kMode;
        c.nStart = input.nStart;
        c.nEnd = input.nEnd;
        c.nStep = input.nStep;
        c.kStart = input.kStart;
        c.kEnd = input.kEnd;
        c.kStep = input.kStep;
        c.densityStart = input.densityStart;
        c.densityEnd = input.densityEnd;
        c.densityStep = input.densityStep;
        c.varyN = input.varyN;
        c.varyK = input.varyK;
        c.varyDensity = input.varyDensity;
        return c;
    }

    private static String utcNow() {
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
        return fmt.format(new Date());
    }

    private static String timestampForPath() {
        return new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date());
    }

    private static final class Point {
        int n;
        int k;
        double density;
        double x;
        Double y;
        String label;
    }
}
