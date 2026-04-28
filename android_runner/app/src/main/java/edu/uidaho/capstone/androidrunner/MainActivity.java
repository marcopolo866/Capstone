package edu.uidaho.capstone.androidrunner;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import edu.uidaho.capstone.androidrunner.data.DatasetCatalog;
import edu.uidaho.capstone.androidrunner.data.DatasetManager;
import edu.uidaho.capstone.androidrunner.data.ManifestCodec;
import edu.uidaho.capstone.androidrunner.data.SessionExporter;
import edu.uidaho.capstone.androidrunner.data.SolverCatalog;
import edu.uidaho.capstone.androidrunner.engine.BenchmarkEngine;
import edu.uidaho.capstone.androidrunner.engine.GeneratedInputs;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkConfig;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkDatapoint;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkSession;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.DatasetSpec;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.SolverVariant;
import edu.uidaho.capstone.androidrunner.ui.BenchmarkChartView;
import edu.uidaho.capstone.androidrunner.ui.GraphVisualizerView;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class MainActivity extends Activity {
    private static final int REQUEST_EXPORT_MANIFEST = 1001;
    private static final int REQUEST_IMPORT_MANIFEST = 1002;

    private BenchmarkEngine engine;
    private final Map<String, CheckBox> variantChecks = new LinkedHashMap<>();
    private final Map<String, CheckBox> datasetChecks = new LinkedHashMap<>();
    private final List<SolverVariant> solverVariants = SolverCatalog.all();
    private final List<DatasetSpec> datasetSpecs = DatasetCatalog.all();

    private FrameLayout content;
    private LinearLayout setupPage;
    private LinearLayout logPage;
    private LinearLayout chartsPage;
    private LinearLayout statsPage;
    private LinearLayout visualizerPage;
    private LinearLayout datasetsPage;
    private TextView logText;
    private TextView statsText;
    private TextView progressText;
    private ProgressBar progressBar;
    private BenchmarkChartView runtimeChart;
    private BenchmarkChartView memoryChart;
    private GraphVisualizerView graphVisualizer;
    private LinearLayout variantsWrap;
    private Button runButton;
    private Button pauseButton;
    private Button abortButton;

    private Spinner tabSpinner;
    private Spinner inputModeSpinner;
    private Spinner graphFamilySpinner;
    private Spinner runModeSpinner;
    private Spinner failurePolicySpinner;
    private Spinner outlierFilterSpinner;
    private EditText iterationsInput;
    private EditText seedInput;
    private EditText workersInput;
    private EditText solverTimeoutInput;
    private EditText retryInput;
    private EditText timeLimitInput;
    private EditText nStartInput;
    private EditText nEndInput;
    private EditText nStepInput;
    private EditText kStartInput;
    private EditText kEndInput;
    private EditText kStepInput;
    private EditText densityStartInput;
    private EditText densityEndInput;
    private EditText densityStepInput;
    private CheckBox varyNCheck;
    private CheckBox varyKCheck;
    private CheckBox varyDensityCheck;
    private CheckBox deleteInputsCheck;
    private CheckBox timeoutMissingCheck;

    private BenchmarkConfig pendingManifestExportConfig;
    private BenchmarkSession lastSession;
    private boolean paused;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        engine = new BenchmarkEngine(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFFF4F6F8);
        setContentView(root);

        TextView title = new TextView(this);
        title.setText("Capstone Benchmark Runner");
        title.setTextSize(22f);
        title.setTextColor(0xFF1F2933);
        title.setGravity(Gravity.CENTER_VERTICAL);
        title.setPadding(dp(12), dp(10), dp(12), dp(6));
        root.addView(title, new LinearLayout.LayoutParams(-1, -2));

        HorizontalScrollView navScroll = new HorizontalScrollView(this);
        LinearLayout nav = new LinearLayout(this);
        nav.setOrientation(LinearLayout.HORIZONTAL);
        navScroll.addView(nav);
        root.addView(navScroll, new LinearLayout.LayoutParams(-1, -2));

        content = new FrameLayout(this);
        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1f));

        setupPage = buildSetupPage();
        logPage = buildLogPage();
        chartsPage = buildChartsPage();
        statsPage = buildStatsPage();
        visualizerPage = buildVisualizerPage();
        datasetsPage = buildDatasetsPage();

        addNavButton(nav, "Setup", setupPage);
        addNavButton(nav, "Run Log", logPage);
        addNavButton(nav, "Charts", chartsPage);
        addNavButton(nav, "Statistics", statsPage);
        addNavButton(nav, "Visualizer", visualizerPage);
        addNavButton(nav, "Datasets", datasetsPage);
        showPage(setupPage);
        appendLog("Android runner ready. Synthetic benchmarks run on-device through the NDK core.");
    }

    private LinearLayout buildSetupPage() {
        LinearLayout wrap = pageContainer();
        wrap.addView(sectionTitle("Benchmark Settings"));

        tabSpinner = spinner(new String[]{"subgraph", "shortest_path"});
        tabSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                refreshVariantChecks();
            }
            @Override public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        wrap.addView(row("Algorithm Tab", tabSpinner));

        inputModeSpinner = spinner(new String[]{"independent", "datasets"});
        wrap.addView(row("Input Mode", inputModeSpinner));

        graphFamilySpinner = spinner(new String[]{"random_density", "erdos_renyi", "barabasi_albert", "grid"});
        wrap.addView(row("Graph Family", graphFamilySpinner));

        runModeSpinner = spinner(new String[]{"threshold", "timed"});
        wrap.addView(row("Stop Mode", runModeSpinner));

        iterationsInput = numberInput("1", false);
        seedInput = numberInput("424242", false);
        workersInput = numberInput("1", false);
        solverTimeoutInput = numberInput("0", false);
        retryInput = numberInput("0", false);
        timeLimitInput = numberInput("1", false);
        wrap.addView(row("Iterations per datapoint", iterationsInput));
        wrap.addView(row("Seed (blank = random)", seedInput));
        wrap.addView(row("Max Parallel Workers", workersInput));
        wrap.addView(row("Solver Timeout (sec, 0=off)", solverTimeoutInput));
        wrap.addView(row("Retry Failed Trials", retryInput));
        wrap.addView(row("Time Limit (minutes)", timeLimitInput));

        failurePolicySpinner = spinner(new String[]{"continue", "stop"});
        outlierFilterSpinner = spinner(new String[]{"none", "mad", "iqr"});
        wrap.addView(row("Failure Policy", failurePolicySpinner));
        wrap.addView(row("Outlier Filter", outlierFilterSpinner));

        timeoutMissingCheck = checkbox("Treat timeout as missing", true);
        deleteInputsCheck = checkbox("Delete generated inputs after datapoint", true);
        wrap.addView(timeoutMissingCheck);
        wrap.addView(deleteInputsCheck);

        wrap.addView(sectionTitle("Independent Variables"));
        varyNCheck = checkbox("Vary N", true);
        varyKCheck = checkbox("Vary K", false);
        varyDensityCheck = checkbox("Vary Density", false);
        wrap.addView(varyNCheck);
        wrap.addView(varyKCheck);
        wrap.addView(varyDensityCheck);
        nStartInput = numberInput("64", false);
        nEndInput = numberInput("64", false);
        nStepInput = numberInput("1", false);
        kStartInput = numberInput("10", false);
        kEndInput = numberInput("10", false);
        kStepInput = numberInput("1", false);
        densityStartInput = numberInput("0.05", true);
        densityEndInput = numberInput("0.05", true);
        densityStepInput = numberInput("0.01", true);
        wrap.addView(row("N start / end / step", triple(nStartInput, nEndInput, nStepInput)));
        wrap.addView(row("K start / end / step", triple(kStartInput, kEndInput, kStepInput)));
        wrap.addView(row("Density start / end / step", triple(densityStartInput, densityEndInput, densityStepInput)));

        wrap.addView(sectionTitle("Solver Variants"));
        variantsWrap = new LinearLayout(this);
        variantsWrap.setOrientation(LinearLayout.VERTICAL);
        wrap.addView(variantsWrap);
        refreshVariantChecksInto(variantsWrap);

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setPadding(0, dp(8), 0, dp(8));
        runButton = button("Run Benchmark");
        pauseButton = button("Pause");
        abortButton = button("Abort Test");
        pauseButton.setEnabled(false);
        abortButton.setEnabled(false);
        runButton.setOnClickListener(v -> startRun());
        pauseButton.setOnClickListener(v -> togglePause());
        abortButton.setOnClickListener(v -> {
            engine.requestAbort();
            appendLog("Abort requested.");
        });
        actions.addView(runButton);
        actions.addView(pauseButton);
        actions.addView(abortButton);
        wrap.addView(actions);

        LinearLayout manifestActions = new LinearLayout(this);
        manifestActions.setOrientation(LinearLayout.HORIZONTAL);
        Button exportManifest = button("Export Manifest");
        Button importManifest = button("Import Manifest");
        exportManifest.setOnClickListener(v -> exportManifest());
        importManifest.setOnClickListener(v -> importManifest());
        manifestActions.addView(exportManifest);
        manifestActions.addView(importManifest);
        wrap.addView(manifestActions);

        return scrollPage(wrap);
    }

    private LinearLayout buildLogPage() {
        LinearLayout page = pageContainer();
        progressText = new TextView(this);
        progressText.setText("No active run.");
        progressText.setTextSize(16f);
        progressText.setPadding(0, 0, 0, dp(8));
        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(1000);
        page.addView(progressText);
        page.addView(progressBar, new LinearLayout.LayoutParams(-1, -2));
        logText = new TextView(this);
        logText.setTextSize(14f);
        logText.setTextColor(0xFF1F2933);
        logText.setPadding(0, dp(12), 0, 0);
        page.addView(logText);
        Button clear = button("Clear Log");
        clear.setOnClickListener(v -> logText.setText(""));
        page.addView(clear);
        return scrollPage(page);
    }

    private LinearLayout buildChartsPage() {
        LinearLayout page = pageContainer();
        page.addView(sectionTitle("Runtime 2D"));
        runtimeChart = new BenchmarkChartView(this);
        page.addView(runtimeChart, new LinearLayout.LayoutParams(-1, dp(300)));
        page.addView(sectionTitle("Memory 2D"));
        memoryChart = new BenchmarkChartView(this);
        page.addView(memoryChart, new LinearLayout.LayoutParams(-1, dp(300)));
        TextView note = muted("3D desktop plots are represented as mobile scrollable 2D metric views in this native first pass.");
        page.addView(note);
        return scrollPage(page);
    }

    private LinearLayout buildStatsPage() {
        LinearLayout page = pageContainer();
        page.addView(sectionTitle("Runtime Statistical Tests"));
        statsText = new TextView(this);
        statsText.setText("Run a benchmark to populate statistical comparisons.");
        statsText.setTextSize(14f);
        statsText.setTextColor(0xFF1F2933);
        page.addView(statsText);
        return scrollPage(page);
    }

    private LinearLayout buildVisualizerPage() {
        LinearLayout page = pageContainer();
        page.addView(sectionTitle("Graph Visualizer"));
        graphVisualizer = new GraphVisualizerView(this);
        page.addView(graphVisualizer, new LinearLayout.LayoutParams(-1, dp(520)));
        return scrollPage(page);
    }

    private LinearLayout buildDatasetsPage() {
        LinearLayout page = pageContainer();
        page.addView(sectionTitle("Independent Variables / Datasets"));
        page.addView(muted("Dataset catalog rows match the desktop runner. Synthetic independent-variable runs are fully on-device; external dataset conversion is staged here for mobile parity."));
        for (DatasetSpec spec : datasetSpecs) {
            CheckBox cb = checkbox(spec.name + " (" + spec.tabId + ")", false);
            cb.setText(spec.name + "\n" + spec.source + " | " + spec.rawFormat + "\n" + spec.description);
            cb.setOnCheckedChangeListener((buttonView, isChecked) -> appendLog((isChecked ? "Selected dataset: " : "Deselected dataset: ") + spec.datasetId));
            datasetChecks.put(spec.datasetId, cb);
            page.addView(cb);
        }
        Button prepare = button("Prepare Selected Datasets");
        prepare.setOnClickListener(v -> prepareSelectedDatasets());
        page.addView(prepare);
        return scrollPage(page);
    }

    private void prepareSelectedDatasets() {
        List<DatasetSpec> selected = new ArrayList<>();
        for (DatasetSpec spec : datasetSpecs) {
            CheckBox cb = datasetChecks.get(spec.datasetId);
            if (cb != null && cb.isChecked()) selected.add(spec);
        }
        if (selected.isEmpty()) {
            toast("Select at least one dataset.");
            return;
        }
        appendLog("Preparing " + selected.size() + " dataset raw download(s).");
        new Thread(() -> {
            for (DatasetSpec spec : selected) {
                try {
                    DatasetManager.downloadRaw(this, spec, message -> runOnUiThread(() -> appendLog(message)));
                } catch (Exception exc) {
                    runOnUiThread(() -> appendLog("Dataset preparation failed for " + spec.datasetId + ": " + exc));
                }
            }
            runOnUiThread(() -> appendLog("Dataset raw preparation finished. Archive conversion parity is pending for Android dataset-mode runs."));
        }, "android-dataset-prepare").start();
    }

    private void startRun() {
        try {
            BenchmarkConfig config = buildConfigFromUi();
            if (config.selectedVariants.isEmpty()) {
                toast("Select at least one solver variant.");
                return;
            }
            paused = false;
            runButton.setEnabled(false);
            pauseButton.setEnabled(true);
            abortButton.setEnabled(true);
            showPage(logPage);
            appendLog("Starting run | tab=" + config.tabId + " | variants=" + config.selectedVariants.size() + " | iterations=" + config.iterations);
            engine.start(config, new BenchmarkEngine.Listener() {
                @Override public void onLog(String message) {
                    runOnUiThread(() -> appendLog(message));
                }

                @Override public void onProgress(int completed, int planned, String label) {
                    runOnUiThread(() -> {
                        int pct = planned <= 0 ? 0 : Math.min(1000, (int) Math.round((completed * 1000.0) / planned));
                        progressBar.setProgress(pct);
                        progressText.setText(planned <= 0 ? ("Completed " + completed + " trials | " + label) : ("Completed " + completed + "/" + planned + " trials | " + label));
                    });
                }

                @Override public void onGraphInputs(GeneratedInputs inputs) {
                    runOnUiThread(() -> graphVisualizer.setInputs(inputs));
                }

                @Override public void onComplete(BenchmarkSession session, File outputDir) {
                    runOnUiThread(() -> handleRunComplete(session, outputDir));
                }

                @Override public void onError(Exception error) {
                    runOnUiThread(() -> handleRunError(error));
                }
            });
        } catch (Exception exc) {
            toast(exc.getMessage() == null ? exc.toString() : exc.getMessage());
        }
    }

    private void handleRunComplete(BenchmarkSession session, File outputDir) {
        lastSession = session;
        try {
            SessionExporter.writeAll(session, outputDir);
            appendLog("Exports written to: " + outputDir.getAbsolutePath());
        } catch (Exception exc) {
            appendLog("Export failed: " + exc);
        }
        runtimeChart.setDatapoints(session.datapoints, "runtime");
        memoryChart.setDatapoints(session.datapoints, "memory");
        statsText.setText(buildStatsText(session));
        progressText.setText("Run complete. Completed " + session.completedTrials + " trials.");
        runButton.setEnabled(true);
        pauseButton.setEnabled(false);
        abortButton.setEnabled(false);
        showPage(chartsPage);
    }

    private void handleRunError(Exception error) {
        appendLog("Run failed: " + error);
        runButton.setEnabled(true);
        pauseButton.setEnabled(false);
        abortButton.setEnabled(false);
        showPage(logPage);
    }

    private void togglePause() {
        if (!paused) {
            paused = true;
            pauseButton.setText("Resume");
            engine.pause();
            appendLog("Run paused.");
        } else {
            paused = false;
            pauseButton.setText("Pause");
            engine.resume();
            appendLog("Run resumed.");
        }
    }

    private BenchmarkConfig buildConfigFromUi() {
        BenchmarkConfig config = new BenchmarkConfig();
        config.tabId = selected(tabSpinner);
        config.inputMode = selected(inputModeSpinner);
        config.graphFamily = selected(graphFamilySpinner);
        config.runMode = selected(runModeSpinner);
        config.iterations = positiveInt(iterationsInput, 1);
        String seedRaw = seedInput.getText().toString().trim();
        config.randomSeed = seedRaw.isEmpty();
        config.baseSeed = config.randomSeed ? 424242L : Long.parseLong(seedRaw);
        config.maxWorkers = positiveInt(workersInput, 1);
        config.parallelRequested = config.maxWorkers > 1;
        config.solverTimeoutSeconds = nonNegativeInt(solverTimeoutInput, 0);
        config.retryFailedTrials = nonNegativeInt(retryInput, 0);
        config.timeLimitMinutes = positiveInt(timeLimitInput, 1);
        config.failurePolicy = selected(failurePolicySpinner);
        config.outlierFilter = selected(outlierFilterSpinner);
        config.timeoutAsMissing = timeoutMissingCheck.isChecked();
        config.deleteGeneratedInputs = deleteInputsCheck.isChecked();
        config.varyN = varyNCheck.isChecked();
        config.varyK = varyKCheck.isChecked();
        config.varyDensity = varyDensityCheck.isChecked();
        config.nStart = positiveInt(nStartInput, 2);
        config.nEnd = positiveInt(nEndInput, config.nStart);
        config.nStep = positiveInt(nStepInput, 1);
        config.kStart = positiveInt(kStartInput, 2);
        config.kEnd = positiveInt(kEndInput, config.kStart);
        config.kStep = positiveInt(kStepInput, 1);
        config.densityStart = density(densityStartInput, 0.05);
        config.densityEnd = density(densityEndInput, config.densityStart);
        config.densityStep = density(densityStepInput, 0.01);
        for (Map.Entry<String, CheckBox> entry : variantChecks.entrySet()) {
            if (entry.getValue().isChecked()) config.selectedVariants.add(entry.getKey());
        }
        for (Map.Entry<String, CheckBox> entry : datasetChecks.entrySet()) {
            if (entry.getValue().isChecked()) config.selectedDatasets.add(entry.getKey());
        }
        return config;
    }

    private void applyConfigToUi(BenchmarkConfig config) {
        setSpinner(tabSpinner, config.tabId);
        setSpinner(inputModeSpinner, config.inputMode);
        setSpinner(graphFamilySpinner, config.graphFamily);
        setSpinner(runModeSpinner, config.runMode);
        iterationsInput.setText(Integer.toString(config.iterations));
        seedInput.setText(Long.toString(config.baseSeed));
        workersInput.setText(Integer.toString(config.maxWorkers));
        solverTimeoutInput.setText(Integer.toString(config.solverTimeoutSeconds));
        retryInput.setText(Integer.toString(config.retryFailedTrials));
        timeLimitInput.setText(Integer.toString(config.timeLimitMinutes));
        setSpinner(failurePolicySpinner, config.failurePolicy);
        setSpinner(outlierFilterSpinner, config.outlierFilter);
        timeoutMissingCheck.setChecked(config.timeoutAsMissing);
        deleteInputsCheck.setChecked(config.deleteGeneratedInputs);
        varyNCheck.setChecked(config.varyN);
        varyKCheck.setChecked(config.varyK);
        varyDensityCheck.setChecked(config.varyDensity);
        nStartInput.setText(Integer.toString(config.nStart));
        nEndInput.setText(Integer.toString(config.nEnd));
        nStepInput.setText(Integer.toString(config.nStep));
        kStartInput.setText(Integer.toString(config.kStart));
        kEndInput.setText(Integer.toString(config.kEnd));
        kStepInput.setText(Integer.toString(config.kStep));
        densityStartInput.setText(Double.toString(config.densityStart));
        densityEndInput.setText(Double.toString(config.densityEnd));
        densityStepInput.setText(Double.toString(config.densityStep));
        for (Map.Entry<String, CheckBox> entry : variantChecks.entrySet()) {
            entry.getValue().setChecked(config.selectedVariants.contains(entry.getKey()));
        }
        for (Map.Entry<String, CheckBox> entry : datasetChecks.entrySet()) {
            entry.getValue().setChecked(config.selectedDatasets.contains(entry.getKey()));
        }
    }

    private void exportManifest() {
        try {
            pendingManifestExportConfig = buildConfigFromUi();
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("application/json");
            intent.putExtra(Intent.EXTRA_TITLE, "benchmark-manifest.json");
            startActivityForResult(intent, REQUEST_EXPORT_MANIFEST);
        } catch (Exception exc) {
            toast(exc.getMessage() == null ? exc.toString() : exc.getMessage());
        }
    }

    private void importManifest() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/json");
        startActivityForResult(intent, REQUEST_IMPORT_MANIFEST);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        try {
            if (requestCode == REQUEST_EXPORT_MANIFEST) {
                String raw = ManifestCodec.write(pendingManifestExportConfig);
                try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                    if (out != null) out.write(raw.getBytes(StandardCharsets.UTF_8));
                }
                appendLog("Manifest exported.");
            } else if (requestCode == REQUEST_IMPORT_MANIFEST) {
                StringBuilder raw = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(getContentResolver().openInputStream(uri), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) raw.append(line).append('\n');
                }
                BenchmarkConfig config = ManifestCodec.read(raw.toString());
                applyConfigToUi(config);
                appendLog("Manifest imported.");
            }
        } catch (Exception exc) {
            toast(exc.getMessage() == null ? exc.toString() : exc.getMessage());
        }
    }

    private String buildStatsText(BenchmarkSession session) {
        StringBuilder out = new StringBuilder();
        out.append("Runtime summary by variant\n\n");
        for (BenchmarkDatapoint row : session.datapoints) {
            out.append(row.variantLabel)
                    .append(" | ").append(row.pointLabel)
                    .append(" | n=").append(row.runtimeSamplesN)
                    .append(" | median=").append(row.runtimeMedianMs == null ? "n/a" : String.format(Locale.US, "%.3f ms", row.runtimeMedianMs))
                    .append(" | sd=").append(String.format(Locale.US, "%.3f", row.runtimeStdevMs))
                    .append('\n');
        }
        return out.toString();
    }

    private void refreshVariantChecks() {
        if (variantsWrap != null) refreshVariantChecksInto(variantsWrap);
    }

    private void refreshVariantChecksInto(LinearLayout variantsWrap) {
        String tab = tabSpinner == null ? "subgraph" : selected(tabSpinner);
        variantsWrap.removeAllViews();
        variantChecks.clear();
        for (SolverVariant variant : solverVariants) {
            if (!tab.equals(variant.tabId)) continue;
            CheckBox cb = checkbox(variant.label, tab.equals("subgraph"));
            if ("shortest_path".equals(tab) && variant.isBaseline()) cb.setChecked(true);
            variantChecks.put(variant.variantId, cb);
            variantsWrap.addView(cb);
        }
    }

    private void addNavButton(LinearLayout nav, String label, LinearLayout page) {
        Button button = button(label);
        button.setOnClickListener(v -> showPage(page));
        nav.addView(button);
    }

    private void showPage(View page) {
        content.removeAllViews();
        content.addView(page, new FrameLayout.LayoutParams(-1, -1));
    }

    private LinearLayout scrollPage(LinearLayout inner) {
        ScrollView scroll = new ScrollView(this);
        scroll.addView(inner);
        LinearLayout host = new LinearLayout(this);
        host.setOrientation(LinearLayout.VERTICAL);
        host.addView(scroll, new LinearLayout.LayoutParams(-1, -1));
        return host;
    }

    private LinearLayout pageContainer() {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(12), dp(12), dp(12), dp(12));
        return page;
    }

    private TextView sectionTitle(String text) {
        TextView title = new TextView(this);
        title.setText(text);
        title.setTextSize(18f);
        title.setTextColor(0xFF1F2933);
        title.setPadding(0, dp(10), 0, dp(6));
        return title;
    }

    private TextView muted(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(0xFF5F6B76);
        view.setTextSize(14f);
        view.setPadding(0, dp(4), 0, dp(8));
        return view;
    }

    private LinearLayout row(String label, View control) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, dp(4), 0, dp(4));
        TextView text = new TextView(this);
        text.setText(label);
        text.setTextColor(0xFF1F2933);
        text.setTextSize(14f);
        row.addView(text);
        row.addView(control);
        return row;
    }

    private LinearLayout triple(EditText a, EditText b, EditText c) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.addView(a, new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(b, new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(c, new LinearLayout.LayoutParams(0, -2, 1f));
        return row;
    }

    private Spinner spinner(String[] values) {
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, values);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        return spinner;
    }

    private EditText numberInput(String value, boolean decimal) {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setText(value);
        input.setInputType(decimal ? (InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL) : InputType.TYPE_CLASS_NUMBER);
        return input;
    }

    private CheckBox checkbox(String text, boolean checked) {
        CheckBox cb = new CheckBox(this);
        cb.setText(text);
        cb.setTextColor(0xFF1F2933);
        cb.setTextSize(14f);
        cb.setChecked(checked);
        return cb;
    }

    private Button button(String text) {
        Button button = new Button(this);
        button.setText(text);
        return button;
    }

    private String selected(Spinner spinner) {
        Object item = spinner.getSelectedItem();
        return item == null ? "" : item.toString();
    }

    private void setSpinner(Spinner spinner, String value) {
        for (int i = 0; i < spinner.getCount(); i++) {
            if (String.valueOf(spinner.getItemAtPosition(i)).equals(value)) {
                spinner.setSelection(i);
                return;
            }
        }
    }

    private int positiveInt(EditText input, int fallback) {
        try {
            return Math.max(1, Integer.parseInt(input.getText().toString().trim()));
        } catch (Exception ignored) {
            return Math.max(1, fallback);
        }
    }

    private int nonNegativeInt(EditText input, int fallback) {
        try {
            return Math.max(0, Integer.parseInt(input.getText().toString().trim()));
        } catch (Exception ignored) {
            return Math.max(0, fallback);
        }
    }

    private double density(EditText input, double fallback) {
        try {
            return Math.max(0.000001, Math.min(1.0, Double.parseDouble(input.getText().toString().trim())));
        } catch (Exception ignored) {
            return Math.max(0.000001, Math.min(1.0, fallback));
        }
    }

    private void appendLog(String message) {
        if (logText == null) return;
        logText.append(message + "\n");
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }
}
