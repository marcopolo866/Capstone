package edu.uidaho.capstone.androidrunner;

import android.app.Activity;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Space;
import android.widget.TextView;
import android.widget.Toast;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.bottomnavigation.BottomNavigationView;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.card.MaterialCardView;
import com.google.android.material.checkbox.MaterialCheckBox;
import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.navigation.NavigationBarView;
import com.google.android.material.navigationrail.NavigationRailView;
import com.google.android.material.progressindicator.LinearProgressIndicator;
import com.google.android.material.switchmaterial.SwitchMaterial;
import com.google.android.material.textfield.MaterialAutoCompleteTextView;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

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
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkTrial;
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
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class MainActivity extends Activity {
    private static final int REQUEST_EXPORT_MANIFEST = 1001;
    private static final int REQUEST_IMPORT_MANIFEST = 1002;

    private static final int NAV_SETUP = 2001;
    private static final int NAV_RUN = 2002;
    private static final int NAV_RESULTS = 2003;
    private static final int NAV_GRAPH = 2004;
    private static final int NAV_DATASETS = 2005;

    private static final int ALGO_SUBGRAPH = 3001;
    private static final int ALGO_SHORTEST_PATH = 3002;
    private static final int INPUT_INDEPENDENT = 3011;
    private static final int INPUT_DATASETS = 3012;
    private static final int RUN_THRESHOLD = 3021;
    private static final int RUN_TIMED = 3022;

    private static final String[] GRAPH_FAMILIES = {"random_density", "erdos_renyi", "barabasi_albert", "grid"};
    private static final String[] FAILURE_POLICIES = {"continue", "stop"};
    private static final String[] OUTLIER_FILTERS = {"none", "mad", "iqr"};

    private final Map<String, Chip> variantChips = new LinkedHashMap<>();
    private final Map<String, MaterialCheckBox> datasetChecks = new LinkedHashMap<>();
    private final Map<String, TextView> datasetStatusLabels = new LinkedHashMap<>();
    private final List<SolverVariant> solverVariants = SolverCatalog.all();
    private final List<DatasetSpec> datasetSpecs = DatasetCatalog.all();
    private final int maxAppThreads = Math.max(1, Runtime.getRuntime().availableProcessors());

    private BenchmarkEngine engine;
    private FrameLayout content;
    private MaterialToolbar toolbar;
    private NavigationBarView navigationView;

    private View setupPage;
    private View runPage;
    private View resultsPage;
    private View visualizerPage;
    private View datasetsPage;

    private MaterialButtonToggleGroup algorithmToggle;
    private MaterialButtonToggleGroup inputModeToggle;
    private MaterialButtonToggleGroup runModeToggle;
    private MaterialButtonToggleGroup kModeToggle;
    private MaterialAutoCompleteTextView graphFamilyInput;
    private MaterialAutoCompleteTextView failurePolicyInput;
    private MaterialAutoCompleteTextView outlierFilterInput;
    private TextInputEditText iterationsInput;
    private TextInputEditText seedInput;
    private TextInputEditText workersInput;
    private TextInputEditText solverTimeoutInput;
    private TextInputEditText retryInput;
    private TextInputEditText timeLimitInput;
    private TextInputEditText nStartInput;
    private TextInputEditText nEndInput;
    private TextInputEditText nStepInput;
    private TextInputEditText kStartInput;
    private TextInputEditText kEndInput;
    private TextInputEditText kStepInput;
    private TextInputEditText densityStartInput;
    private TextInputEditText densityEndInput;
    private TextInputEditText densityStepInput;
    private SwitchMaterial varyNCheck;
    private SwitchMaterial varyKCheck;
    private SwitchMaterial varyDensityCheck;
    private SwitchMaterial deleteInputsCheck;
    private SwitchMaterial timeoutMissingCheck;
    private ChipGroup variantsGroup;
    private TextView plannedTrialsText;

    private TextView logText;
    private TextView runSummaryTitle;
    private TextView runSummaryMeta;
    private TextView progressText;
    private LinearProgressIndicator progressBar;
    private BenchmarkChartView runtimeChart;
    private BenchmarkChartView memoryChart;
    private GraphVisualizerView graphVisualizer;
    private TextView statsText;
    private TextView trialsMetric;
    private TextView runtimeMetric;
    private TextView memoryMetric;
    private TextView failuresMetric;
    private TextView resultsMeta;
    private SwitchMaterial graphLabelsSwitch;

    private MaterialButton runButton;
    private MaterialButton pauseButton;
    private MaterialButton abortButton;

    private BenchmarkConfig pendingManifestExportConfig;
    private BenchmarkSession lastSession;
    private boolean paused;
    private int currentNavId = NAV_SETUP;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        engine = new BenchmarkEngine(this);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(color(R.color.runner_bg));
        setContentView(root);

        toolbar = new MaterialToolbar(this);
        toolbar.setTitle("Benchmark Runner");
        toolbar.setTitleTextColor(color(R.color.runner_text));
        toolbar.setBackgroundColor(color(R.color.runner_bg));
        buildToolbarMenu(toolbar.getMenu());
        toolbar.setOnMenuItemClickListener(this::onToolbarItemSelected);
        root.addView(toolbar, new LinearLayout.LayoutParams(-1, dp(56)));

        boolean useRail = shouldUseNavigationRail();
        if (useRail) {
            LinearLayout body = new LinearLayout(this);
            body.setOrientation(LinearLayout.HORIZONTAL);
            root.addView(body, new LinearLayout.LayoutParams(-1, 0, 1f));
            NavigationRailView rail = new NavigationRailView(this);
            navigationView = rail;
            buildNavigationMenu(rail.getMenu());
            body.addView(rail, new LinearLayout.LayoutParams(dp(88), -1));
            content = new FrameLayout(this);
            body.addView(content, new LinearLayout.LayoutParams(0, -1, 1f));
        } else {
            content = new FrameLayout(this);
            root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1f));
            BottomNavigationView bottom = new BottomNavigationView(this);
            navigationView = bottom;
            bottom.setLabelVisibilityMode(NavigationBarView.LABEL_VISIBILITY_LABELED);
            buildNavigationMenu(bottom.getMenu());
            root.addView(bottom, new LinearLayout.LayoutParams(-1, -2));
        }
        setupPage = buildSetupPage();
        runPage = buildRunPage();
        resultsPage = buildResultsPage();
        visualizerPage = buildVisualizerPage();
        datasetsPage = buildDatasetsPage();

        navigationView.setOnItemSelectedListener(item -> {
            showPage(item.getItemId());
            return true;
        });
        showPage(NAV_SETUP);
        updateRunEstimate();
        appendLog("Android runner ready. Synthetic benchmarks run on-device through the NDK core.");
    }

    private void buildToolbarMenu(Menu menu) {
        menu.add(0, REQUEST_IMPORT_MANIFEST, 0, "Import")
                .setIcon(android.R.drawable.ic_menu_revert)
                .setShowAsAction(MenuItem.SHOW_AS_ACTION_IF_ROOM);
        menu.add(0, REQUEST_EXPORT_MANIFEST, 1, "Export")
                .setIcon(android.R.drawable.ic_menu_save)
                .setShowAsAction(MenuItem.SHOW_AS_ACTION_IF_ROOM);
    }

    private boolean onToolbarItemSelected(MenuItem item) {
        if (item.getItemId() == REQUEST_IMPORT_MANIFEST) {
            importManifest();
            return true;
        }
        if (item.getItemId() == REQUEST_EXPORT_MANIFEST) {
            exportManifest();
            return true;
        }
        return false;
    }

    private void buildNavigationMenu(Menu menu) {
        menu.add(0, NAV_SETUP, 0, "Setup").setIcon(android.R.drawable.ic_menu_manage);
        menu.add(0, NAV_RUN, 1, "Run").setIcon(android.R.drawable.ic_media_play);
        menu.add(0, NAV_RESULTS, 2, "Results").setIcon(android.R.drawable.ic_menu_sort_by_size);
        menu.add(0, NAV_GRAPH, 3, "Graph").setIcon(android.R.drawable.ic_menu_share);
        menu.add(0, NAV_DATASETS, 4, "Data").setIcon(android.R.drawable.ic_menu_agenda);
    }

    private View buildSetupPage() {
        LinearLayout host = new LinearLayout(this);
        host.setOrientation(LinearLayout.VERTICAL);

        LinearLayout page = pageContainer();

        LinearLayout benchmark = addSection(page, "Benchmark", "Choose the workload and how the app should generate inputs.");
        algorithmToggle = toggleGroup(
                new int[]{ALGO_SUBGRAPH, ALGO_SHORTEST_PATH},
                new String[]{"Subgraph", "Shortest path"},
                ALGO_SUBGRAPH
        );
        algorithmToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (!isChecked) return;
            refreshVariantChips();
            updateVariableAvailability();
            updateRunEstimate();
        });
        benchmark.addView(labeledBlock("Algorithm", algorithmToggle));

        inputModeToggle = toggleGroup(
                new int[]{INPUT_INDEPENDENT, INPUT_DATASETS},
                new String[]{"Independent", "Datasets"},
                INPUT_INDEPENDENT
        );
        inputModeToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (isChecked) updateRunEstimate();
        });
        benchmark.addView(labeledBlock("Input source", inputModeToggle));

        graphFamilyInput = dropdown(GRAPH_FAMILIES, "random_density");
        benchmark.addView(textField("Graph Family", graphFamilyInput, null));

        runModeToggle = toggleGroup(
                new int[]{RUN_THRESHOLD, RUN_TIMED},
                new String[]{"Threshold", "Timed"},
                RUN_THRESHOLD
        );
        runModeToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (isChecked) updateRunEstimate();
        });
        benchmark.addView(labeledBlock("Stop mode", runModeToggle));

        iterationsInput = numberInput("1", false);
        seedInput = numberInput("424242", false);
        workersInput = numberInput("1", false);
        timeLimitInput = numberInput("1", false);
        benchmark.addView(twoColumnRow(
                textField("Iterations per datapoint", iterationsInput, null),
                textField("Seed", seedInput, "Blank uses a random seed.")
        ));
        benchmark.addView(twoColumnRow(
                textField("Max Parallel Workers (max app threads: " + maxAppThreads + ")", workersInput, null),
                textField("Time Limit (minutes)", timeLimitInput, null)
        ));

        LinearLayout variables = addSection(page, "Independent Variables", "Set ranges for generated benchmark datapoints.");
        varyNCheck = switchControl("Vary N", true);
        varyKCheck = switchControl("Vary K", false);
        varyDensityCheck = switchControl("Vary Density", false);
        variables.addView(switchRow(varyNCheck, varyKCheck, varyDensityCheck));
        nStartInput = numberInput("10", false);
        nEndInput = numberInput("10", false);
        nStepInput = numberInput("1", false);
        kStartInput = numberInput("5", false);
        kEndInput = numberInput("5", false);
        kStepInput = numberInput("1", false);
        densityStartInput = numberInput("0.01", true);
        densityEndInput = numberInput("0.01", true);
        densityStepInput = numberInput("0.01", true);
        variables.addView(rangeRow("N", nStartInput, nEndInput, nStepInput));
        kModeToggle = toggleGroup(
                new int[]{3031, 3032},
                new String[]{"Absolute", "Percent"},
                3031
        );
        kModeToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (isChecked) updateRunEstimate();
        });
        variables.addView(labeledBlock("K Mode", kModeToggle));
        variables.addView(rangeRow("K", kStartInput, kEndInput, kStepInput));
        variables.addView(rangeRow("Density", densityStartInput, densityEndInput, densityStepInput));

        LinearLayout variants = addSection(page, "Solver Variants", "Select the solver families to include in the run.");
        variantsGroup = new ChipGroup(this);
        variantsGroup.setSingleLine(false);
        variantsGroup.setChipSpacingHorizontal(dp(8));
        variantsGroup.setChipSpacingVertical(dp(8));
        variants.addView(variantsGroup, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout variantActions = new LinearLayout(this);
        variantActions.setOrientation(LinearLayout.HORIZONTAL);
        MaterialButton selectAll = outlinedButton("Select all");
        MaterialButton clearAll = outlinedButton("Clear");
        selectAll.setOnClickListener(v -> {
            for (Chip chip : variantChips.values()) chip.setChecked(true);
            updateRunEstimate();
        });
        clearAll.setOnClickListener(v -> {
            for (Chip chip : variantChips.values()) chip.setChecked(false);
            updateRunEstimate();
        });
        variantActions.addView(selectAll, new LinearLayout.LayoutParams(0, dp(48), 1f));
        variantActions.addView(space(dp(8), 1));
        variantActions.addView(clearAll, new LinearLayout.LayoutParams(0, dp(48), 1f));
        variants.addView(variantActions);

        LinearLayout policy = addSection(page, "Run Policy", "Configure failure handling, cleanup, and statistical filtering.");
        failurePolicyInput = dropdown(FAILURE_POLICIES, "continue");
        outlierFilterInput = dropdown(OUTLIER_FILTERS, "none");
        solverTimeoutInput = numberInput("0", false);
        retryInput = numberInput("0", false);
        policy.addView(twoColumnRow(
                textField("Failure Policy", failurePolicyInput, null),
                textField("Outlier Filter", outlierFilterInput, null)
        ));
        policy.addView(twoColumnRow(
                textField("Solver Timeout (sec, 0=off)", solverTimeoutInput, null),
                textField("Retry Failed Trials", retryInput, null)
        ));
        timeoutMissingCheck = switchControl("Treat timeout as missing", true);
        deleteInputsCheck = switchControl("Delete generated inputs after datapoint", true);
        policy.addView(switchRow(timeoutMissingCheck, deleteInputsCheck));

        plannedTrialsText = muted("Estimated run: 1 datapoint, 1 iteration, selected variants determine trial count.");
        plannedTrialsText.setPadding(0, dp(8), 0, 0);
        policy.addView(plannedTrialsText);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(page);
        host.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));
        host.addView(buildSetupActions(), new LinearLayout.LayoutParams(-1, -2));

        refreshVariantChips();
        updateVariableAvailability();
        trackEstimateInputs();
        return host;
    }

    private View buildSetupActions() {
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.VERTICAL);
        actions.setPadding(dp(16), dp(10), dp(16), dp(12));
        actions.setBackgroundColor(color(R.color.runner_bg));

        runButton = filledButton("Run Benchmark");
        runButton.setIconResource(android.R.drawable.ic_media_play);
        runButton.setOnClickListener(v -> startRun());
        actions.addView(runButton, new LinearLayout.LayoutParams(-1, dp(52)));

        LinearLayout manifestActions = new LinearLayout(this);
        manifestActions.setOrientation(LinearLayout.HORIZONTAL);
        manifestActions.setPadding(0, dp(8), 0, 0);
        MaterialButton importButton = outlinedButton("Import");
        MaterialButton exportButton = outlinedButton("Export");
        importButton.setIconResource(android.R.drawable.ic_menu_revert);
        exportButton.setIconResource(android.R.drawable.ic_menu_save);
        importButton.setOnClickListener(v -> importManifest());
        exportButton.setOnClickListener(v -> exportManifest());
        manifestActions.addView(importButton, new LinearLayout.LayoutParams(0, dp(48), 1f));
        manifestActions.addView(space(dp(8), 1));
        manifestActions.addView(exportButton, new LinearLayout.LayoutParams(0, dp(48), 1f));
        actions.addView(manifestActions);
        return actions;
    }

    private View buildRunPage() {
        LinearLayout page = pageContainer();

        LinearLayout status = addSection(page, "Run Status", null);
        runSummaryTitle = titleText("No active run.");
        runSummaryMeta = muted("Configure a benchmark from Setup and start it when ready.");
        progressText = muted("No progress yet.");
        progressBar = new LinearProgressIndicator(this);
        progressBar.setMax(1000);
        progressBar.setProgressCompat(0, false);
        progressBar.setIndeterminate(false);
        status.addView(runSummaryTitle);
        status.addView(runSummaryMeta);
        status.addView(progressText);
        status.addView(progressBar, new LinearLayout.LayoutParams(-1, dp(8)));

        LinearLayout runActions = new LinearLayout(this);
        runActions.setOrientation(LinearLayout.HORIZONTAL);
        runActions.setPadding(0, dp(12), 0, 0);
        pauseButton = outlinedButton("Pause");
        abortButton = outlinedButton("Abort");
        MaterialButton clear = outlinedButton("Clear Log");
        pauseButton.setIconResource(android.R.drawable.ic_media_pause);
        abortButton.setIconResource(android.R.drawable.ic_menu_close_clear_cancel);
        clear.setIconResource(android.R.drawable.ic_menu_delete);
        pauseButton.setEnabled(false);
        abortButton.setEnabled(false);
        pauseButton.setOnClickListener(v -> togglePause());
        abortButton.setOnClickListener(v -> {
            engine.requestAbort();
            appendLog("Abort requested.");
        });
        clear.setOnClickListener(v -> logText.setText(""));
        runActions.addView(pauseButton, new LinearLayout.LayoutParams(0, dp(48), 1f));
        runActions.addView(space(dp(8), 1));
        runActions.addView(abortButton, new LinearLayout.LayoutParams(0, dp(48), 1f));
        runActions.addView(space(dp(8), 1));
        runActions.addView(clear, new LinearLayout.LayoutParams(0, dp(48), 1f));
        status.addView(runActions);

        LinearLayout log = addSection(page, "Run Log", null);
        logText = new TextView(this);
        logText.setTextSize(13f);
        logText.setTextColor(color(R.color.runner_text));
        logText.setTypeface(Typeface.MONOSPACE);
        logText.setLineSpacing(0f, 1.08f);
        log.addView(logText, new LinearLayout.LayoutParams(-1, -2));

        return scrollPage(page);
    }

    private View buildResultsPage() {
        LinearLayout page = pageContainer();

        LinearLayout overview = addSection(page, "Results Dashboard", null);
        resultsMeta = muted("Run a benchmark to populate results.");
        overview.addView(resultsMeta);
        HorizontalScrollView metricsScroll = new HorizontalScrollView(this);
        metricsScroll.setHorizontalScrollBarEnabled(false);
        LinearLayout metrics = new LinearLayout(this);
        metrics.setOrientation(LinearLayout.HORIZONTAL);
        trialsMetric = metricCard(metrics, "Trials", "0");
        runtimeMetric = metricCard(metrics, "Median runtime", "n/a");
        memoryMetric = metricCard(metrics, "Median memory", "n/a");
        failuresMetric = metricCard(metrics, "Failures", "0");
        metricsScroll.addView(metrics);
        overview.addView(metricsScroll, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout runtime = addSection(page, "Runtime", "Median runtime by variant and datapoint.");
        runtimeChart = new BenchmarkChartView(this);
        runtime.addView(runtimeChart, new LinearLayout.LayoutParams(-1, dp(320)));

        LinearLayout memory = addSection(page, "Memory", "Median peak memory by variant and datapoint.");
        memoryChart = new BenchmarkChartView(this);
        memory.addView(memoryChart, new LinearLayout.LayoutParams(-1, dp(320)));

        LinearLayout stats = addSection(page, "Statistics", null);
        statsText = new TextView(this);
        statsText.setText("Run a benchmark to populate statistical comparisons.");
        statsText.setTextSize(14f);
        statsText.setTextColor(color(R.color.runner_text));
        statsText.setTypeface(Typeface.MONOSPACE);
        stats.addView(statsText);

        return scrollPage(page);
    }

    private View buildVisualizerPage() {
        LinearLayout host = new LinearLayout(this);
        host.setOrientation(LinearLayout.VERTICAL);
        host.setPadding(dp(16), dp(12), dp(16), dp(16));

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.HORIZONTAL);
        controls.setGravity(Gravity.CENTER_VERTICAL);
        controls.setPadding(0, 0, 0, dp(10));
        graphLabelsSwitch = switchControl("Labels", true);
        MaterialButton reset = outlinedButton("Reset View");
        reset.setIconResource(android.R.drawable.ic_menu_revert);
        reset.setOnClickListener(v -> graphVisualizer.resetViewport());
        graphLabelsSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> graphVisualizer.setShowLabels(isChecked));
        controls.addView(graphLabelsSwitch, new LinearLayout.LayoutParams(0, dp(48), 1f));
        controls.addView(space(dp(8), 1));
        controls.addView(reset, new LinearLayout.LayoutParams(0, dp(48), 1f));
        host.addView(controls, new LinearLayout.LayoutParams(-1, -2));

        graphVisualizer = new GraphVisualizerView(this);
        graphVisualizer.setShowLabels(true);
        host.addView(graphVisualizer, new LinearLayout.LayoutParams(-1, 0, 1f));
        return host;
    }

    private View buildDatasetsPage() {
        LinearLayout host = new LinearLayout(this);
        host.setOrientation(LinearLayout.VERTICAL);

        LinearLayout page = pageContainer();
        LinearLayout header = addSection(page, "Dataset Library", "Select raw benchmark archives to prepare in app storage.");
        TextView root = muted("Storage: " + DatasetManager.datasetRoot(this).getAbsolutePath());
        header.addView(root);

        for (DatasetSpec spec : datasetSpecs) {
            page.addView(datasetCard(spec));
        }

        ScrollView scroll = new ScrollView(this);
        scroll.addView(page);
        host.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setPadding(dp(16), dp(10), dp(16), dp(12));
        actions.setBackgroundColor(color(R.color.runner_bg));
        MaterialButton prepare = filledButton("Prepare Selected");
        prepare.setIconResource(android.R.drawable.ic_menu_save);
        prepare.setOnClickListener(v -> prepareSelectedDatasets());
        MaterialButton refresh = outlinedButton("Refresh");
        refresh.setIconResource(android.R.drawable.ic_menu_rotate);
        refresh.setOnClickListener(v -> updateDatasetStatuses());
        actions.addView(prepare, new LinearLayout.LayoutParams(0, dp(52), 1f));
        actions.addView(space(dp(8), 1));
        actions.addView(refresh, new LinearLayout.LayoutParams(0, dp(52), 1f));
        host.addView(actions);

        updateDatasetStatuses();
        return host;
    }

    private View datasetCard(DatasetSpec spec) {
        MaterialCardView card = shellCard();
        card.setClickable(true);
        card.setCheckable(true);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(16), dp(14), dp(16), dp(14));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        MaterialCheckBox check = new MaterialCheckBox(this);
        check.setContentDescription("Select " + spec.name);
        TextView title = titleText(spec.name);
        top.addView(check, new LinearLayout.LayoutParams(dp(48), dp(48)));
        top.addView(title, new LinearLayout.LayoutParams(0, -2, 1f));
        top.addView(badge(spec.tabId));
        body.addView(top);

        TextView meta = muted(spec.source + " | " + spec.rawFormat + " | " + formatBytes(spec.estimatedSizeBytes));
        TextView desc = bodyText(spec.description);
        TextView status = muted("Not prepared");
        status.setTypeface(Typeface.DEFAULT_BOLD);
        body.addView(meta);
        body.addView(desc);
        body.addView(status);
        card.addView(body);

        card.setOnClickListener(v -> check.setChecked(!check.isChecked()));
        check.setOnCheckedChangeListener((buttonView, isChecked) -> {
            card.setChecked(isChecked);
            updateRunEstimate();
            appendLog((isChecked ? "Selected dataset: " : "Deselected dataset: ") + spec.datasetId);
        });
        datasetChecks.put(spec.datasetId, check);
        datasetStatusLabels.put(spec.datasetId, status);
        return card;
    }

    private void prepareSelectedDatasets() {
        List<DatasetSpec> selected = new ArrayList<>();
        for (DatasetSpec spec : datasetSpecs) {
            MaterialCheckBox cb = datasetChecks.get(spec.datasetId);
            if (cb != null && cb.isChecked()) selected.add(spec);
        }
        if (selected.isEmpty()) {
            toast("Select at least one dataset.");
            return;
        }
        showPage(NAV_RUN);
        appendLog("Preparing " + selected.size() + " dataset raw download(s).");
        new Thread(() -> {
            for (DatasetSpec spec : selected) {
                try {
                    DatasetManager.downloadRaw(this, spec, message -> runOnUiThread(() -> appendLog(message)));
                } catch (Exception exc) {
                    runOnUiThread(() -> appendLog("Dataset preparation failed for " + spec.datasetId + ": " + exc));
                }
            }
            runOnUiThread(() -> {
                updateDatasetStatuses();
                appendLog("Dataset raw preparation finished. Archive conversion parity is pending for Android dataset-mode runs.");
            });
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
            setRunningState(true);
            showPage(NAV_RUN);
            progressBar.setProgressCompat(0, false);
            runSummaryTitle.setText("Run in progress");
            runSummaryMeta.setText(summaryLine(config));
            progressText.setText("Starting...");
            appendLog("Starting run | " + summaryLine(config));
            appendLog("Phone reports " + maxAppThreads + " processor thread(s) available to this app.");
            engine.start(config, new BenchmarkEngine.Listener() {
                @Override public void onLog(String message) {
                    runOnUiThread(() -> appendLog(message));
                }

                @Override public void onProgress(int completed, int planned, String label) {
                    runOnUiThread(() -> {
                        int pct = planned <= 0 ? 0 : Math.min(1000, (int) Math.round((completed * 1000.0) / planned));
                        progressBar.setIndeterminate(planned <= 0);
                        if (planned > 0) progressBar.setProgressCompat(pct, true);
                        progressText.setText(planned <= 0
                                ? ("Completed " + completed + " trials | " + label)
                                : ("Completed " + completed + "/" + planned + " trials | " + label));
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
        progressBar.setIndeterminate(false);
        progressBar.setProgressCompat(1000, true);
        progressText.setText("Run complete. Completed " + session.completedTrials + " trials.");
        runSummaryTitle.setText("Run complete");
        runSummaryMeta.setText("Exports: " + outputDir.getAbsolutePath());
        setRunningState(false);
        updateResultDashboard(session, outputDir);
        showPage(NAV_RESULTS);
    }

    private void handleRunError(Exception error) {
        appendLog("Run failed: " + error);
        progressBar.setIndeterminate(false);
        progressText.setText("Run failed.");
        runSummaryTitle.setText("Run failed");
        runSummaryMeta.setText(error.getMessage() == null ? error.toString() : error.getMessage());
        setRunningState(false);
        showPage(NAV_RUN);
    }

    private void togglePause() {
        if (!paused) {
            paused = true;
            pauseButton.setText("Resume");
            pauseButton.setIconResource(android.R.drawable.ic_media_play);
            engine.pause();
            appendLog("Run paused.");
        } else {
            paused = false;
            pauseButton.setText("Pause");
            pauseButton.setIconResource(android.R.drawable.ic_media_pause);
            engine.resume();
            appendLog("Run resumed.");
        }
    }

    private void setRunningState(boolean running) {
        if (runButton != null) runButton.setEnabled(!running);
        if (pauseButton != null) {
            pauseButton.setEnabled(running);
            pauseButton.setText("Pause");
            pauseButton.setIconResource(android.R.drawable.ic_media_pause);
        }
        if (abortButton != null) abortButton.setEnabled(running);
        if (!running) paused = false;
    }

    private BenchmarkConfig buildConfigFromUi() {
        BenchmarkConfig config = new BenchmarkConfig();
        config.tabId = selectedAlgorithm();
        config.inputMode = selectedInputMode();
        config.graphFamily = dropdownValue(graphFamilyInput, "random_density");
        config.runMode = selectedRunMode();
        config.iterations = positiveInt(iterationsInput, 1);
        String seedRaw = text(seedInput).trim();
        config.randomSeed = seedRaw.isEmpty();
        config.baseSeed = config.randomSeed ? 424242L : Long.parseLong(seedRaw);
        config.maxWorkers = positiveInt(workersInput, 1);
        config.parallelRequested = config.maxWorkers > 1;
        config.solverTimeoutSeconds = nonNegativeInt(solverTimeoutInput, 0);
        config.retryFailedTrials = nonNegativeInt(retryInput, 0);
        config.timeLimitMinutes = positiveInt(timeLimitInput, 1);
        config.failurePolicy = dropdownValue(failurePolicyInput, "continue");
        config.outlierFilter = dropdownValue(outlierFilterInput, "none");
        config.timeoutAsMissing = timeoutMissingCheck.isChecked();
        config.deleteGeneratedInputs = deleteInputsCheck.isChecked();
        config.kMode = selectedKMode();
        config.varyN = varyNCheck.isChecked();
        config.varyK = varyKCheck.isChecked();
        config.varyDensity = varyDensityCheck.isChecked();
        config.nStart = positiveInt(nStartInput, 2);
        config.nEnd = positiveInt(nEndInput, config.nStart);
        config.nStep = positiveInt(nStepInput, 1);
        config.kStart = positiveInt(kStartInput, 2);
        config.kEnd = positiveInt(kEndInput, config.kStart);
        config.kStep = positiveInt(kStepInput, 1);
        config.densityStart = density(densityStartInput, 0.01);
        config.densityEnd = density(densityEndInput, config.densityStart);
        config.densityStep = density(densityStepInput, 0.01);
        for (Map.Entry<String, Chip> entry : variantChips.entrySet()) {
            if (entry.getValue().isChecked()) config.selectedVariants.add(entry.getKey());
        }
        for (Map.Entry<String, MaterialCheckBox> entry : datasetChecks.entrySet()) {
            if (entry.getValue().isChecked()) config.selectedDatasets.add(entry.getKey());
        }
        return config;
    }

    private void applyConfigToUi(BenchmarkConfig config) {
        algorithmToggle.check("shortest_path".equals(config.tabId) ? ALGO_SHORTEST_PATH : ALGO_SUBGRAPH);
        inputModeToggle.check("datasets".equals(config.inputMode) ? INPUT_DATASETS : INPUT_INDEPENDENT);
        setDropdown(graphFamilyInput, config.graphFamily);
        runModeToggle.check("timed".equals(config.runMode) ? RUN_TIMED : RUN_THRESHOLD);
        iterationsInput.setText(Integer.toString(config.iterations));
        seedInput.setText(config.randomSeed ? "" : Long.toString(config.baseSeed));
        workersInput.setText(Integer.toString(config.maxWorkers));
        solverTimeoutInput.setText(Integer.toString(config.solverTimeoutSeconds));
        retryInput.setText(Integer.toString(config.retryFailedTrials));
        timeLimitInput.setText(Integer.toString(config.timeLimitMinutes));
        setDropdown(failurePolicyInput, config.failurePolicy);
        setDropdown(outlierFilterInput, config.outlierFilter);
        timeoutMissingCheck.setChecked(config.timeoutAsMissing);
        deleteInputsCheck.setChecked(config.deleteGeneratedInputs);
        kModeToggle.check("percent".equals(config.kMode) ? 3032 : 3031);
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
        refreshVariantChips();
        for (Map.Entry<String, Chip> entry : variantChips.entrySet()) {
            entry.getValue().setChecked(config.selectedVariants.contains(entry.getKey()));
        }
        for (Map.Entry<String, MaterialCheckBox> entry : datasetChecks.entrySet()) {
            entry.getValue().setChecked(config.selectedDatasets.contains(entry.getKey()));
        }
        updateVariableAvailability();
        updateRunEstimate();
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

    private void refreshVariantChips() {
        if (variantsGroup == null) return;
        List<String> previous = selectedVariantIds();
        boolean hadPrevious = !variantChips.isEmpty();
        String tab = selectedAlgorithm();
        variantsGroup.removeAllViews();
        variantChips.clear();
        for (SolverVariant variant : solverVariants) {
            if (!tab.equals(variant.tabId)) continue;
            Chip chip = new Chip(this);
            chip.setText(variant.label);
            chip.setCheckable(true);
            chip.setEnsureMinTouchTargetSize(true);
            chip.setContentDescription("Solver variant " + variant.label);
            chip.setChipBackgroundColor(chipColors());
            chip.setTextColor(textChipColors());
            boolean defaultChecked = "subgraph".equals(tab) || ("shortest_path".equals(tab) && variant.isBaseline());
            chip.setChecked(hadPrevious ? previous.contains(variant.variantId) : defaultChecked);
            chip.setOnCheckedChangeListener((buttonView, isChecked) -> updateRunEstimate());
            variantChips.put(variant.variantId, chip);
            variantsGroup.addView(chip);
        }
        updateRunEstimate();
    }

    private List<String> selectedVariantIds() {
        List<String> selected = new ArrayList<>();
        for (Map.Entry<String, Chip> entry : variantChips.entrySet()) {
            if (entry.getValue().isChecked()) selected.add(entry.getKey());
        }
        return selected;
    }

    private void updateVariableAvailability() {
        boolean subgraph = "subgraph".equals(selectedAlgorithm());
        varyKCheck.setEnabled(subgraph);
        kModeToggle.setEnabled(subgraph);
        kStartInput.setEnabled(subgraph);
        kEndInput.setEnabled(subgraph);
        kStepInput.setEnabled(subgraph);
        if (!subgraph) varyKCheck.setChecked(false);
    }

    private void updateRunEstimate() {
        if (plannedTrialsText == null) return;
        BenchmarkConfig config;
        try {
            config = buildConfigFromUi();
        } catch (Exception ignored) {
            return;
        }
        int points = estimatePointCount(config);
        int variants = config.selectedVariants.size();
        int datasets = config.selectedDatasets.size();
        String estimate;
        if ("timed".equals(config.runMode)) {
            estimate = "Timed run | " + config.timeLimitMinutes + " min";
        } else {
            int planned = Math.max(0, points * Math.max(variants, 0) * config.iterations);
            estimate = planned + " planned trial" + (planned == 1 ? "" : "s");
        }
        String detail = points + " datapoint" + (points == 1 ? "" : "s")
                + " | " + variants + " variant" + (variants == 1 ? "" : "s")
                + " | " + config.iterations + " iteration" + (config.iterations == 1 ? "" : "s");
        if (datasets > 0) detail += " | " + datasets + " dataset" + (datasets == 1 ? "" : "s");
        if ("subgraph".equals(config.tabId)) detail += " | K " + config.kMode;
        plannedTrialsText.setText("Estimated run: " + estimate + " | " + detail);
    }

    private int estimatePointCount(BenchmarkConfig config) {
        int n = config.varyN ? countIntRange(config.nStart, config.nEnd, config.nStep) : 1;
        int k = "subgraph".equals(config.tabId) && config.varyK ? countIntRange(config.kStart, config.kEnd, config.kStep) : 1;
        int d = config.varyDensity ? countDoubleRange(config.densityStart, config.densityEnd, config.densityStep) : 1;
        return Math.max(1, n * k * d);
    }

    private void updateDatasetStatuses() {
        for (DatasetSpec spec : datasetSpecs) {
            TextView label = datasetStatusLabels.get(spec.datasetId);
            if (label == null) continue;
            if (DatasetManager.rawReady(this, spec)) {
                File raw = DatasetManager.rawFile(this, spec);
                label.setText("Prepared | " + formatBytes(raw.length()));
                label.setTextColor(color(R.color.runner_secondary));
            } else {
                label.setText("Not prepared");
                label.setTextColor(color(R.color.runner_muted));
            }
        }
    }

    private void updateResultDashboard(BenchmarkSession session, File outputDir) {
        int failed = 0;
        List<Double> runtimeValues = new ArrayList<>();
        List<Double> memoryValues = new ArrayList<>();
        for (BenchmarkTrial trial : session.trials) {
            if (!"ok".equals(trial.status)) failed++;
        }
        for (BenchmarkDatapoint row : session.datapoints) {
            if (row.runtimeMedianMs != null) runtimeValues.add(row.runtimeMedianMs);
            if (row.memoryMedianKb != null) memoryValues.add(row.memoryMedianKb);
        }
        trialsMetric.setText(session.completedTrials + "/" + (session.plannedTrials <= 0 ? "timed" : session.plannedTrials));
        Double runtime = median(runtimeValues);
        Double memory = median(memoryValues);
        runtimeMetric.setText(runtime == null ? "n/a" : String.format(Locale.US, "%.3f ms", runtime));
        memoryMetric.setText(memory == null ? "n/a" : String.format(Locale.US, "%.1f kB", memory));
        failuresMetric.setText(Integer.toString(failed));
        resultsMeta.setText("Completed in " + String.format(Locale.US, "%.2f s", session.runDurationMs / 1000.0)
                + " | Exports: " + outputDir.getAbsolutePath());
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

    private void showPage(int navId) {
        currentNavId = navId;
        if (content == null) return;
        content.removeAllViews();
        View page;
        String title;
        if (navId == NAV_RUN) {
            if (runPage == null) runPage = buildRunPage();
            page = runPage;
            title = "Run";
        } else if (navId == NAV_RESULTS) {
            if (resultsPage == null) resultsPage = buildResultsPage();
            page = resultsPage;
            title = "Results";
        } else if (navId == NAV_GRAPH) {
            if (visualizerPage == null) visualizerPage = buildVisualizerPage();
            page = visualizerPage;
            title = "Graph";
        } else if (navId == NAV_DATASETS) {
            if (datasetsPage == null) datasetsPage = buildDatasetsPage();
            page = datasetsPage;
            title = "Data";
            updateDatasetStatuses();
        } else {
            if (setupPage == null) setupPage = buildSetupPage();
            page = setupPage;
            title = "Setup";
        }
        toolbar.setTitle(title);
        toolbar.setSubtitle(null);
        if (page.getParent() instanceof ViewGroup) {
            ((ViewGroup) page.getParent()).removeView(page);
        }
        content.addView(page, new FrameLayout.LayoutParams(-1, -1));
        if (navigationView != null && navigationView.getSelectedItemId() != navId) {
            navigationView.setSelectedItemId(navId);
        }
    }

    private LinearLayout pageContainer() {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(16), dp(12), dp(16), dp(16));
        return page;
    }

    private View scrollPage(LinearLayout inner) {
        ScrollView scroll = new ScrollView(this);
        scroll.addView(inner);
        return scroll;
    }

    private LinearLayout addSection(LinearLayout page, String title, String subtitle) {
        MaterialCardView card = shellCard();
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(16), dp(14), dp(16), dp(16));
        body.addView(titleText(title));
        if (subtitle != null && !subtitle.isEmpty()) body.addView(muted(subtitle));
        card.addView(body);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.setMargins(0, 0, 0, dp(12));
        page.addView(card, params);
        return body;
    }

    private MaterialCardView shellCard() {
        MaterialCardView card = new MaterialCardView(this);
        card.setRadius(dp(8));
        card.setCardElevation(dp(1));
        card.setStrokeWidth(dp(1));
        card.setStrokeColor(color(R.color.runner_outline));
        card.setCardBackgroundColor(color(R.color.runner_surface));
        return card;
    }

    private TextView titleText(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(color(R.color.runner_text));
        view.setTextSize(18f);
        view.setTypeface(Typeface.DEFAULT_BOLD);
        view.setPadding(0, 0, 0, dp(4));
        return view;
    }

    private TextView bodyText(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(color(R.color.runner_text));
        view.setTextSize(14f);
        view.setPadding(0, dp(4), 0, dp(4));
        return view;
    }

    private TextView muted(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(color(R.color.runner_muted));
        view.setTextSize(13f);
        view.setPadding(0, dp(2), 0, dp(8));
        return view;
    }

    private TextView badge(String text) {
        TextView badge = new TextView(this);
        badge.setText(titleCase(text));
        badge.setTextColor(color(R.color.runner_on_primary_container));
        badge.setTextSize(12f);
        badge.setTypeface(Typeface.DEFAULT_BOLD);
        badge.setGravity(Gravity.CENTER);
        GradientDrawable background = new GradientDrawable();
        background.setColor(color(R.color.runner_primary_container));
        background.setCornerRadius(dp(999));
        badge.setBackground(background);
        badge.setPadding(dp(8), dp(4), dp(8), dp(4));
        return badge;
    }

    private TextView metricCard(LinearLayout parent, String label, String value) {
        MaterialCardView card = shellCard();
        card.setStrokeWidth(0);
        card.setCardBackgroundColor(color(R.color.runner_surface_variant));
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(14), dp(12), dp(14), dp(12));
        TextView labelView = muted(label);
        labelView.setPadding(0, 0, 0, dp(4));
        TextView valueView = titleText(value);
        valueView.setTextSize(20f);
        body.addView(labelView);
        body.addView(valueView);
        card.addView(body);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(176), -2);
        params.setMargins(0, dp(8), dp(10), dp(4));
        parent.addView(card, params);
        return valueView;
    }

    private MaterialButtonToggleGroup toggleGroup(int[] ids, String[] labels, int checkedId) {
        MaterialButtonToggleGroup group = new MaterialButtonToggleGroup(this);
        group.setSingleSelection(true);
        group.setSelectionRequired(true);
        group.setPadding(0, dp(4), 0, dp(8));
        for (int i = 0; i < ids.length; i++) {
            MaterialButton button = new MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
            button.setId(ids[i]);
            button.setText(labels[i]);
            button.setCheckable(true);
            button.setTextColor(toggleTextColors());
            button.setBackgroundTintList(toggleBackgroundColors());
            button.setMinHeight(dp(48));
            button.setInsetTop(0);
            button.setInsetBottom(0);
            group.addView(button, new LinearLayout.LayoutParams(0, dp(48), 1f));
        }
        group.check(checkedId);
        return group;
    }

    private TextInputEditText numberInput(String value, boolean decimal) {
        TextInputEditText input = new TextInputEditText(this);
        input.setSingleLine(true);
        input.setText(value);
        input.setSelectAllOnFocus(true);
        input.setInputType(decimal
                ? (InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL)
                : InputType.TYPE_CLASS_NUMBER);
        return input;
    }

    private MaterialAutoCompleteTextView dropdown(String[] values, String selected) {
        MaterialAutoCompleteTextView view = new MaterialAutoCompleteTextView(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_list_item_1, values);
        view.setAdapter(adapter);
        view.setSingleLine(true);
        view.setInputType(InputType.TYPE_NULL);
        view.setText(selected, false);
        view.setOnItemClickListener((parent, view1, position, id) -> updateRunEstimate());
        return view;
    }

    private TextInputLayout textField(String label, TextView editText, String helper) {
        TextInputLayout layout = new TextInputLayout(this);
        layout.setHint(label);
        layout.setBoxBackgroundMode(TextInputLayout.BOX_BACKGROUND_OUTLINE);
        layout.setEndIconMode(editText instanceof MaterialAutoCompleteTextView ? TextInputLayout.END_ICON_DROPDOWN_MENU : TextInputLayout.END_ICON_NONE);
        if (helper != null) layout.setHelperText(helper);
        layout.setPadding(0, dp(6), 0, dp(6));
        layout.addView(editText, new LinearLayout.LayoutParams(-1, -2));
        return layout;
    }

    private View labeledBlock(String label, View control) {
        LinearLayout block = new LinearLayout(this);
        block.setOrientation(LinearLayout.VERTICAL);
        block.setPadding(0, dp(6), 0, dp(6));
        TextView text = new TextView(this);
        text.setText(label);
        text.setTextColor(color(R.color.runner_muted));
        text.setTextSize(13f);
        block.addView(text);
        block.addView(control, new LinearLayout.LayoutParams(-1, -2));
        return block;
    }

    private View twoColumnRow(View left, View right) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(shouldUseTwoColumns() ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        row.addView(left, new LinearLayout.LayoutParams(0, -2, shouldUseTwoColumns() ? 1f : 0f));
        if (shouldUseTwoColumns()) row.addView(space(dp(10), 1));
        row.addView(right, new LinearLayout.LayoutParams(0, -2, shouldUseTwoColumns() ? 1f : 0f));
        if (!shouldUseTwoColumns()) {
            left.getLayoutParams().width = -1;
            right.getLayoutParams().width = -1;
        }
        return row;
    }

    private View rangeRow(String label, TextInputEditText start, TextInputEditText end, TextInputEditText step) {
        LinearLayout block = new LinearLayout(this);
        block.setOrientation(LinearLayout.VERTICAL);
        block.setPadding(0, dp(6), 0, dp(4));
        TextView title = new TextView(this);
        title.setText(label);
        title.setTextSize(13f);
        title.setTextColor(color(R.color.runner_muted));
        block.addView(title);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.addView(textField("Start", start, null), new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(space(dp(8), 1));
        row.addView(textField("End", end, null), new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(space(dp(8), 1));
        row.addView(textField("Step", step, null), new LinearLayout.LayoutParams(0, -2, 1f));
        block.addView(row);
        return block;
    }

    private SwitchMaterial switchControl(String text, boolean checked) {
        SwitchMaterial sw = new SwitchMaterial(this);
        sw.setText(text);
        sw.setTextColor(color(R.color.runner_text));
        sw.setTextSize(14f);
        sw.setChecked(checked);
        sw.setMinHeight(dp(48));
        sw.setGravity(Gravity.CENTER_VERTICAL);
        sw.setOnCheckedChangeListener((buttonView, isChecked) -> updateRunEstimate());
        return sw;
    }

    private View switchRow(SwitchMaterial... switches) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(shouldUseTwoColumns() ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        for (int i = 0; i < switches.length; i++) {
            row.addView(switches[i], new LinearLayout.LayoutParams(0, dp(52), shouldUseTwoColumns() ? 1f : 0f));
            if (!shouldUseTwoColumns()) switches[i].getLayoutParams().width = -1;
            if (shouldUseTwoColumns() && i < switches.length - 1) row.addView(space(dp(8), 1));
        }
        return row;
    }

    private MaterialButton filledButton(String text) {
        MaterialButton button = new MaterialButton(this);
        button.setText(text);
        button.setMinHeight(dp(48));
        button.setIconGravity(MaterialButton.ICON_GRAVITY_TEXT_START);
        return button;
    }

    private MaterialButton outlinedButton(String text) {
        MaterialButton button = new MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
        button.setText(text);
        button.setMinHeight(dp(48));
        button.setIconGravity(MaterialButton.ICON_GRAVITY_TEXT_START);
        return button;
    }

    private Space space(int width, int height) {
        Space space = new Space(this);
        space.setMinimumWidth(width);
        space.setMinimumHeight(height);
        return space;
    }

    private ColorStateList chipColors() {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{color(R.color.runner_primary_container), color(R.color.runner_surface_variant)}
        );
    }

    private ColorStateList textChipColors() {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{color(R.color.runner_on_primary_container), color(R.color.runner_text)}
        );
    }

    private ColorStateList toggleTextColors() {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{color(R.color.runner_on_primary), color(R.color.runner_primary)}
        );
    }

    private ColorStateList toggleBackgroundColors() {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{color(R.color.runner_primary), color(R.color.runner_surface)}
        );
    }

    private void trackEstimateInputs() {
        TextWatcher watcher = new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                updateRunEstimate();
            }

            @Override public void afterTextChanged(Editable s) {
            }
        };
        for (TextInputEditText input : new TextInputEditText[]{
                iterationsInput, seedInput, workersInput, solverTimeoutInput, retryInput, timeLimitInput,
                nStartInput, nEndInput, nStepInput, kStartInput, kEndInput, kStepInput,
                densityStartInput, densityEndInput, densityStepInput
        }) {
            input.addTextChangedListener(watcher);
        }
    }

    private String selectedAlgorithm() {
        return algorithmToggle != null && algorithmToggle.getCheckedButtonId() == ALGO_SHORTEST_PATH ? "shortest_path" : "subgraph";
    }

    private String selectedInputMode() {
        return inputModeToggle != null && inputModeToggle.getCheckedButtonId() == INPUT_DATASETS ? "datasets" : "independent";
    }

    private String selectedRunMode() {
        return runModeToggle != null && runModeToggle.getCheckedButtonId() == RUN_TIMED ? "timed" : "threshold";
    }

    private String selectedKMode() {
        return kModeToggle != null && kModeToggle.getCheckedButtonId() == 3032 ? "percent" : "absolute";
    }

    private String dropdownValue(MaterialAutoCompleteTextView input, String fallback) {
        String value = input == null ? "" : String.valueOf(input.getText()).trim();
        return value.isEmpty() ? fallback : value;
    }

    private void setDropdown(MaterialAutoCompleteTextView input, String value) {
        if (input != null && value != null && !value.isEmpty()) input.setText(value, false);
    }

    private int positiveInt(TextInputEditText input, int fallback) {
        try {
            return Math.max(1, Integer.parseInt(text(input).trim()));
        } catch (Exception ignored) {
            return Math.max(1, fallback);
        }
    }

    private int nonNegativeInt(TextInputEditText input, int fallback) {
        try {
            return Math.max(0, Integer.parseInt(text(input).trim()));
        } catch (Exception ignored) {
            return Math.max(0, fallback);
        }
    }

    private double density(TextInputEditText input, double fallback) {
        try {
            return Math.max(0.000001, Math.min(1.0, Double.parseDouble(text(input).trim())));
        } catch (Exception ignored) {
            return Math.max(0.000001, Math.min(1.0, fallback));
        }
    }

    private String text(TextInputEditText input) {
        return input == null || input.getText() == null ? "" : input.getText().toString();
    }

    private int countIntRange(int start, int end, int step) {
        if (end < start) end = start;
        return ((end - start) / Math.max(1, step)) + 1;
    }

    private int countDoubleRange(double start, double end, double step) {
        if (end < start) end = start;
        double safeStep = step <= 0.0 ? 0.01 : step;
        return Math.max(1, (int) Math.floor(((end - start) / safeStep) + 1.000000001));
    }

    private String summaryLine(BenchmarkConfig config) {
        return "tab=" + config.tabId
                + " | mode=" + config.inputMode
                + " | variants=" + config.selectedVariants.size()
                + " | iterations=" + config.iterations
                + " | workers=" + config.maxWorkers + "/" + maxAppThreads;
    }

    private Double median(List<Double> values) {
        if (values.isEmpty()) return null;
        List<Double> copy = new ArrayList<>(values);
        Collections.sort(copy);
        int mid = copy.size() / 2;
        if (copy.size() % 2 == 1) return copy.get(mid);
        return (copy.get(mid - 1) + copy.get(mid)) / 2.0;
    }

    private String formatBytes(long bytes) {
        if (bytes >= 1024L * 1024L * 1024L) return String.format(Locale.US, "%.1f GiB", bytes / (1024.0 * 1024.0 * 1024.0));
        if (bytes >= 1024L * 1024L) return String.format(Locale.US, "%.1f MiB", bytes / (1024.0 * 1024.0));
        if (bytes >= 1024L) return String.format(Locale.US, "%.1f KiB", bytes / 1024.0);
        return bytes + " B";
    }

    private String titleCase(String raw) {
        if (raw == null || raw.isEmpty()) return "";
        String normalized = raw.replace('_', ' ');
        return normalized.substring(0, 1).toUpperCase(Locale.US) + normalized.substring(1);
    }

    private boolean shouldUseNavigationRail() {
        Configuration config = getResources().getConfiguration();
        return config.smallestScreenWidthDp >= 600;
    }

    private boolean shouldUseTwoColumns() {
        return getResources().getConfiguration().screenWidthDp >= 600;
    }

    private void appendLog(String message) {
        if (logText == null) return;
        logText.append(message + "\n");
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
    }

    private int color(int resId) {
        return getColor(resId);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }
}
