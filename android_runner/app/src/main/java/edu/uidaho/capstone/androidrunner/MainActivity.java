package edu.uidaho.capstone.androidrunner;

import android.app.Activity;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
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
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Space;
import android.widget.TextView;
import android.widget.Toast;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.bottomnavigation.BottomNavigationView;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.card.MaterialCardView;
import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.navigation.NavigationBarView;
import com.google.android.material.navigationrail.NavigationRailView;
import com.google.android.material.progressindicator.LinearProgressIndicator;
import com.google.android.material.switchmaterial.SwitchMaterial;
import com.google.android.material.textfield.MaterialAutoCompleteTextView;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

import edu.uidaho.capstone.androidrunner.data.ManifestCodec;
import edu.uidaho.capstone.androidrunner.data.SessionExporter;
import edu.uidaho.capstone.androidrunner.data.SolverCatalog;
import edu.uidaho.capstone.androidrunner.engine.BenchmarkEngine;
import edu.uidaho.capstone.androidrunner.engine.GeneratedInputs;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkConfig;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkDatapoint;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkSession;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkTrial;
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

    private static final int ALGO_SUBGRAPH = 3001;
    private static final int ALGO_SHORTEST_PATH = 3002;
    private static final int RUN_THRESHOLD = 3021;
    private static final int RUN_TIMED = 3022;
    private static final int K_ABSOLUTE = 3031;
    private static final int K_PERCENT = 3032;

    private static final String[] GRAPH_FAMILIES = {"random_density", "erdos_renyi", "barabasi_albert", "grid"};
    private static final String[] FAILURE_POLICIES = {"continue", "stop"};
    private static final String[] OUTLIER_FILTERS = {"none", "mad", "iqr"};

    private final Map<String, Chip> variantChips = new LinkedHashMap<>();
    private final List<SolverVariant> solverVariants = SolverCatalog.all();
    private final int maxAppThreads = Math.max(1, Runtime.getRuntime().availableProcessors());

    private BenchmarkEngine engine;
    private FrameLayout content;
    private MaterialToolbar toolbar;
    private NavigationBarView navigationView;

    private View setupPage;
    private View runPage;
    private View resultsPage;
    private View visualizerPage;

    private MaterialButtonToggleGroup algorithmToggle;
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
    private LinearLayout variantsWrap;
    private TextView plannedTrialsText;

    private TextView logText;
    private TextView runSummaryTitle;
    private TextView runSummaryMeta;
    private TextView progressText;
    private LinearProgressIndicator progressBar;
    private BenchmarkChartView runtimeChart;
    private BenchmarkChartView memoryChart;
    private GraphVisualizerView graphVisualizer;
    private LinearLayout statsTableWrap;
    private SwitchMaterial errorBarsSwitch;
    private TextView trialsMetric;
    private TextView runtimeMetric;
    private TextView memoryMetric;
    private TextView failuresMetric;
    private TextView resultsMeta;
    private SwitchMaterial graphLabelsSwitch;
    private TextView visualizerStatusText;
    private ProgressBar visualizerLoading;
    private final Map<String, List<MaterialButton>> visualizerNavButtons = new LinkedHashMap<>();
    private final Map<String, TextView> visualizerNavLabels = new LinkedHashMap<>();
    private final List<GeneratedInputs> visualizerInputs = new ArrayList<>();
    private int visualizerIndex = -1;
    private int visualizerRequestSerial;

    private MaterialButton runButton;
    private MaterialButton pauseButton;
    private MaterialButton abortButton;
    private TextView pauseActionLabel;

    private BenchmarkConfig pendingManifestExportConfig;
    private BenchmarkSession lastSession;
    private boolean paused;
    private boolean suppressNavigationCallback;
    private boolean errorBarsEnabled;
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
            configureNavigationView(rail);
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
            configureNavigationView(bottom);
            root.addView(bottom, new LinearLayout.LayoutParams(-1, -2));
        }
        setupPage = buildSetupPage();
        runPage = buildRunPage();
        resultsPage = buildResultsPage();
        visualizerPage = buildVisualizerPage();

        navigationView.setOnItemSelectedListener(item -> {
            if (suppressNavigationCallback) return true;
            try {
                showPage(item.getItemId());
                return true;
            } catch (RuntimeException exc) {
                toast("Unable to open page: " + readableError(exc));
                return false;
            }
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
        menu.add(0, NAV_GRAPH, 3, "Graph").setIcon(android.R.drawable.ic_menu_gallery);
    }

    private void configureNavigationView(NavigationBarView view) {
        view.setLabelVisibilityMode(NavigationBarView.LABEL_VISIBILITY_LABELED);
        if (view instanceof BottomNavigationView) {
            ((BottomNavigationView) view).setItemHorizontalTranslationEnabled(false);
        }
        ColorStateList navText = new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{Color.WHITE, color(R.color.runner_text)}
        );
        ColorStateList navIcon = new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{Color.WHITE, color(R.color.runner_muted)}
        );
        view.setItemTextColor(navText);
        view.setItemIconTintList(navIcon);
        view.setItemActiveIndicatorColor(ColorStateList.valueOf(color(R.color.runner_primary)));
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
        seedInput = numberInput("", false);
        workersInput = numberInput("1", false);
        timeLimitInput = numberInput("1", false);
        benchmark.addView(twoColumnRow(
                textField("Seed", seedInput, "Blank uses a random seed."),
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
                new int[]{K_ABSOLUTE, K_PERCENT},
                new String[]{"Absolute", "Percent"},
                K_ABSOLUTE
        );
        kModeToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (isChecked) updateRunEstimate();
        });
        variables.addView(labeledBlock("K Mode", kModeToggle));
        variables.addView(rangeRow("K", kStartInput, kEndInput, kStepInput));
        variables.addView(rangeRow("Density", densityStartInput, densityEndInput, densityStepInput));

        LinearLayout variants = addSection(page, "Solver Variants", "Select the solver families to include in the run.");
        variantsWrap = new LinearLayout(this);
        variantsWrap.setOrientation(LinearLayout.VERTICAL);
        variants.addView(variantsWrap, new LinearLayout.LayoutParams(-1, -2));
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
                textField("Iterations per datapoint", iterationsInput, null),
                textField("Max Parallel Workers (max app threads: " + maxAppThreads + ")", workersInput, null)
        ));
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
        pauseButton = iconOnlyButton(android.R.drawable.ic_media_pause, "Pause");
        abortButton = iconOnlyButton(android.R.drawable.ic_menu_close_clear_cancel, "Abort");
        pauseButton.setIconResource(android.R.drawable.ic_media_pause);
        abortButton.setIconResource(android.R.drawable.ic_menu_close_clear_cancel);
        pauseButton.setEnabled(false);
        abortButton.setEnabled(false);
        pauseButton.setOnClickListener(v -> togglePause());
        abortButton.setOnClickListener(v -> {
            engine.requestAbort();
            appendLog("Abort requested.");
        });
        runActions.addView(iconAction(pauseButton, "Pause"), new LinearLayout.LayoutParams(0, dp(76), 1f));
        runActions.addView(space(dp(8), 1));
        runActions.addView(iconAction(abortButton, "Abort"), new LinearLayout.LayoutParams(0, dp(76), 1f));
        status.addView(runActions);

        MaterialCardView logCard = shellCard();
        LinearLayout log = new LinearLayout(this);
        log.setOrientation(LinearLayout.VERTICAL);
        log.setPadding(dp(16), dp(14), dp(16), dp(16));
        LinearLayout logHeader = new LinearLayout(this);
        logHeader.setOrientation(LinearLayout.HORIZONTAL);
        logHeader.setGravity(Gravity.CENTER_VERTICAL);
        TextView logTitle = titleText("Run Log");
        MaterialButton clear = outlinedButton("Clear Log");
        clear.setIconResource(android.R.drawable.ic_menu_delete);
        clear.setOnClickListener(v -> logText.setText(""));
        logHeader.addView(logTitle, new LinearLayout.LayoutParams(0, -2, 1f));
        logHeader.addView(clear, new LinearLayout.LayoutParams(dp(176), dp(44)));
        log.addView(logHeader);
        logText = new TextView(this);
        logText.setTextSize(13f);
        logText.setTextColor(color(R.color.runner_text));
        logText.setTypeface(Typeface.MONOSPACE);
        logText.setLineSpacing(0f, 1.08f);
        log.addView(logText, new LinearLayout.LayoutParams(-1, -2));
        logCard.addView(log);
        LinearLayout.LayoutParams logParams = new LinearLayout.LayoutParams(-1, -2);
        logParams.setMargins(0, 0, 0, dp(12));
        page.addView(logCard, logParams);

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
        errorBarsSwitch = switchControl("Error Bars", false);
        errorBarsSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> {
            errorBarsEnabled = isChecked;
            applyResultChartOptions();
        });
        overview.addView(errorBarsSwitch, new LinearLayout.LayoutParams(-1, dp(52)));

        LinearLayout runtime = addSection(page, "Runtime", "Median runtime by variant and datapoint.");
        runtimeChart = new BenchmarkChartView(this);
        runtimeChart.setShowErrorBars(errorBarsEnabled);
        runtime.addView(runtimeChart, new LinearLayout.LayoutParams(-1, dp(320)));

        LinearLayout memory = addSection(page, "Memory", "Median peak memory by variant and datapoint.");
        memoryChart = new BenchmarkChartView(this);
        memoryChart.setShowErrorBars(errorBarsEnabled);
        memory.addView(memoryChart, new LinearLayout.LayoutParams(-1, dp(320)));

        LinearLayout stats = addSection(page, "Statistics", "Runtime deltas are variant - baseline. Negative mean delta means faster.");
        statsTableWrap = new LinearLayout(this);
        statsTableWrap.setOrientation(LinearLayout.VERTICAL);
        stats.addView(statsTableWrap, new LinearLayout.LayoutParams(-1, -2));
        renderStatsTable(null);

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

        visualizerNavButtons.clear();
        visualizerNavLabels.clear();
        visualizerStatusText = muted("Run a generated-input benchmark to populate solutions.");
        visualizerLoading = new ProgressBar(this);
        visualizerLoading.setIndeterminate(true);
        visualizerLoading.setVisibility(View.GONE);
        host.addView(visualizerNavRow("N", "n", new int[]{-10, -5, -1, 1, 5, 10}));
        host.addView(visualizerNavRow("k", "k", new int[]{-10, -5, -1, 1, 5, 10}));
        host.addView(visualizerNavRow("Density", "density", new int[]{-10, -5, -1, 1, 5, 10}));
        host.addView(visualizerNavRow("Iteration", "iteration", new int[]{-10, -5, -1, 1, 5, 10}));
        host.addView(visualizerNavRow("Solution", "solution", new int[]{-10, -5, -1, 1, 5, 10}));
        LinearLayout statusRow = new LinearLayout(this);
        statusRow.setOrientation(LinearLayout.HORIZONTAL);
        statusRow.setGravity(Gravity.CENTER_VERTICAL);
        statusRow.addView(visualizerStatusText, new LinearLayout.LayoutParams(0, -2, 1f));
        statusRow.addView(visualizerLoading, new LinearLayout.LayoutParams(dp(42), dp(42)));
        host.addView(statusRow, new LinearLayout.LayoutParams(-1, -2));

        graphVisualizer = new GraphVisualizerView(this);
        graphVisualizer.setShowLabels(true);
        host.addView(graphVisualizer, new LinearLayout.LayoutParams(-1, dp(1280)));
        updateVisualizerNavState();
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(false);
        scroll.addView(host, new ScrollView.LayoutParams(-1, -2));
        return scroll;
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
            visualizerInputs.clear();
            visualizerIndex = -1;
            updateVisualizerNavState();
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
                                ? ("Completed " + completed + " trials")
                                : ("Completed " + completed + "/" + planned + " trials"));
                    });
                }

                @Override public void onGraphInputs(GeneratedInputs inputs, int pointIndex, int iterationIndex, long seed) {
                    runOnUiThread(() -> {
                        boolean firstInput = visualizerInputs.isEmpty();
                        visualizerInputs.add(inputs);
                        if (firstInput || visualizerIndex < 0) {
                            showVisualizerInput(0, false);
                        } else {
                            updateVisualizerNavState();
                        }
                    });
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
        applyResultChartOptions();
        renderStatsTable(session);
        progressBar.setIndeterminate(false);
        progressBar.setProgressCompat(1000, true);
        progressText.setText("Run complete. Completed " + session.completedTrials + " trials.");
        runSummaryTitle.setText("Run complete");
        runSummaryMeta.setText("Exports: " + outputDir.getAbsolutePath());
        setRunningState(false);
        updateResultDashboard(session, outputDir);
        showPage(NAV_RESULTS);
    }

    private void applyResultChartOptions() {
        if (runtimeChart != null) runtimeChart.setShowErrorBars(errorBarsEnabled);
        if (memoryChart != null) memoryChart.setShowErrorBars(errorBarsEnabled);
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
            pauseButton.setText("");
            if (pauseActionLabel != null) pauseActionLabel.setText("Resume");
            pauseButton.setIconResource(android.R.drawable.ic_media_play);
            pauseButton.setContentDescription("Resume");
            engine.pause();
            appendLog("Run paused.");
        } else {
            paused = false;
            pauseButton.setText("");
            if (pauseActionLabel != null) pauseActionLabel.setText("Pause");
            pauseButton.setIconResource(android.R.drawable.ic_media_pause);
            pauseButton.setContentDescription("Pause");
            engine.resume();
            appendLog("Run resumed.");
        }
    }

    private void setRunningState(boolean running) {
        if (runButton != null) runButton.setEnabled(!running);
        if (pauseButton != null) {
            pauseButton.setEnabled(running);
            pauseButton.setText("");
            if (pauseActionLabel != null) pauseActionLabel.setText("Pause");
            pauseButton.setIconResource(android.R.drawable.ic_media_pause);
            pauseButton.setContentDescription("Pause");
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
        return config;
    }

    private void applyConfigToUi(BenchmarkConfig config) {
        algorithmToggle.check("shortest_path".equals(config.tabId) ? ALGO_SHORTEST_PATH : ALGO_SUBGRAPH);
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
        kModeToggle.check("percent".equals(config.kMode) ? K_PERCENT : K_ABSOLUTE);
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
        if (variantsWrap == null) return;
        List<String> previous = selectedVariantIds();
        boolean hadPrevious = !variantChips.isEmpty();
        String tab = selectedAlgorithm();
        variantsWrap.removeAllViews();
        variantChips.clear();
        LinearLayout columns = new LinearLayout(this);
        columns.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout left = variantColumn(columnTitleFor(tab, true));
        View divider = new View(this);
        divider.setBackgroundColor(Color.BLACK);
        LinearLayout right = variantColumn(columnTitleFor(tab, false));
        for (SolverVariant variant : solverVariants) {
            if (!tab.equals(variant.tabId)) continue;
            Chip chip = variantChip(variant);
            boolean defaultChecked = variant.isBaseline();
            chip.setChecked(hadPrevious ? previous.contains(variant.variantId) : defaultChecked);
            chip.setOnCheckedChangeListener((buttonView, isChecked) -> updateRunEstimate());
            variantChips.put(variant.variantId, chip);
            if (isLeftVariantColumn(tab, variant)) {
                left.addView(chip, new LinearLayout.LayoutParams(-1, dp(46)));
            } else {
                right.addView(chip, new LinearLayout.LayoutParams(-1, dp(46)));
            }
        }
        columns.addView(left, new LinearLayout.LayoutParams(0, -2, 1f));
        LinearLayout.LayoutParams dividerParams = new LinearLayout.LayoutParams(dp(1), -1);
        dividerParams.setMargins(dp(10), 0, dp(10), 0);
        columns.addView(divider, dividerParams);
        columns.addView(right, new LinearLayout.LayoutParams(0, -2, 1f));
        variantsWrap.addView(columns);
        updateRunEstimate();
    }

    private LinearLayout variantColumn(String title) {
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        TextView label = new TextView(this);
        label.setText(title);
        label.setTextColor(color(R.color.runner_text));
        label.setTextSize(14f);
        label.setTypeface(Typeface.DEFAULT_BOLD);
        label.setPadding(0, 0, 0, dp(8));
        column.addView(label);
        return column;
    }

    private Chip variantChip(SolverVariant variant) {
        Chip chip = new Chip(this);
        chip.setText(shortVariantLabel(variant));
        chip.setCheckable(true);
        chip.setCheckedIconVisible(true);
        chip.setEnsureMinTouchTargetSize(true);
        chip.setContentDescription("Solver variant " + variant.label);
        chip.setChipBackgroundColor(variantChipColors());
        chip.setChipStrokeColor(variantChipStrokeColors());
        chip.setChipStrokeWidth(dp(1));
        chip.setTextColor(variantChipTextColors());
        chip.setCheckedIconTint(variantChipTextColors());
        return chip;
    }

    private boolean isLeftVariantColumn(String tab, SolverVariant variant) {
        if ("subgraph".equals(tab)) return "vf3".equals(variant.family);
        return "dijkstra".equals(variant.family);
    }

    private String columnTitleFor(String tab, boolean left) {
        if ("subgraph".equals(tab)) return left ? "VF3" : "Glasgow";
        return left ? "Dijkstra" : "Via";
    }

    private String shortVariantLabel(SolverVariant variant) {
        String label = variant.label;
        if ("vf3".equals(variant.family) && label.startsWith("VF3 ")) return label.substring(4);
        if ("glasgow".equals(variant.family) && label.startsWith("Glasgow ")) return label.substring(8);
        if ("dijkstra".equals(variant.family) && label.startsWith("Dijkstra ")) return label.substring(9);
        if ("sp_via".equals(variant.family) && label.startsWith("With Intermediate ")) return label.substring(18);
        return label;
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
        if ("subgraph".equals(config.tabId)) detail += " | K " + config.kMode;
        plannedTrialsText.setText("Estimated run: " + estimate + " | " + detail);
    }

    private int estimatePointCount(BenchmarkConfig config) {
        int n = config.varyN ? countIntRange(config.nStart, config.nEnd, config.nStep) : 1;
        int k = "subgraph".equals(config.tabId) && config.varyK ? countIntRange(config.kStart, config.kEnd, config.kStep) : 1;
        int d = config.varyDensity ? countDoubleRange(config.densityStart, config.densityEnd, config.densityStep) : 1;
        return Math.max(1, n * k * d);
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

    private void shiftVisualizer(int delta) {
        if (visualizerInputs.isEmpty()) return;
        int next = Math.max(0, Math.min(visualizerInputs.size() - 1, visualizerIndex + delta));
        showVisualizerInput(next, true);
    }

    private void shiftVisualizer(String kind, int delta) {
        if (visualizerInputs.isEmpty()) return;
        if ("solution".equals(kind)) {
            shiftVisualizer(delta);
            return;
        }
        GeneratedInputs current = visualizerIndex >= 0 && visualizerIndex < visualizerInputs.size()
                ? visualizerInputs.get(visualizerIndex)
                : visualizerInputs.get(0);
        int next = visualizerIndex;
        if ("iteration".equals(kind)) {
            next = findVisualizerByIteration(current, delta);
        } else {
            next = findVisualizerByVariable(kind, current, delta);
        }
        if (next < 0) next = Math.max(0, Math.min(visualizerInputs.size() - 1, visualizerIndex + delta));
        showVisualizerInput(next, true);
    }

    private View visualizerNavRow(String label, String kind, int[] deltas) {
        LinearLayout block = new LinearLayout(this);
        block.setOrientation(LinearLayout.VERTICAL);
        block.setPadding(0, 0, 0, dp(8));
        TextView title = new TextView(this);
        title.setText(label);
        title.setTextColor(color(R.color.runner_text));
        title.setTextSize(13f);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        visualizerNavLabels.put(kind, title);
        block.addView(title, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        List<MaterialButton> buttons = new ArrayList<>();
        visualizerNavButtons.put(kind, buttons);
        for (int delta : deltas) {
            MaterialButton button = compactNavButton(navDeltaLabel(delta));
            button.setOnClickListener(v -> shiftVisualizer(kind, delta));
            buttons.add(button);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(40), 1f);
            params.setMargins(dp(2), 0, dp(2), 0);
            row.addView(button, params);
        }
        block.addView(row, new LinearLayout.LayoutParams(-1, dp(40)));
        return block;
    }

    private int findVisualizerByIteration(GeneratedInputs current, int delta) {
        List<Integer> iterations = new ArrayList<>();
        for (GeneratedInputs inputs : visualizerInputs) {
            if (inputs.pointIndex == current.pointIndex && !iterations.contains(inputs.iterationIndex)) {
                iterations.add(inputs.iterationIndex);
            }
        }
        Collections.sort(iterations);
        int pos = Math.max(0, iterations.indexOf(current.iterationIndex));
        int targetIteration = iterations.get(Math.max(0, Math.min(iterations.size() - 1, pos + delta)));
        for (int i = 0; i < visualizerInputs.size(); i++) {
            GeneratedInputs inputs = visualizerInputs.get(i);
            if (inputs.pointIndex == current.pointIndex && inputs.iterationIndex == targetIteration) return i;
        }
        return -1;
    }

    private int findVisualizerByVariable(String kind, GeneratedInputs current, int delta) {
        List<Double> values = new ArrayList<>();
        for (GeneratedInputs inputs : visualizerInputs) {
            double value = visualizerVariableValue(kind, inputs);
            if (!containsClose(values, value)) values.add(value);
        }
        Collections.sort(values);
        double currentValue = visualizerVariableValue(kind, current);
        int pos = 0;
        for (int i = 0; i < values.size(); i++) {
            if (Math.abs(values.get(i) - currentValue) < 1e-9) {
                pos = i;
                break;
            }
        }
        double target = values.get(Math.max(0, Math.min(values.size() - 1, pos + delta)));
        int bestIndex = -1;
        double bestScore = Double.POSITIVE_INFINITY;
        for (int i = 0; i < visualizerInputs.size(); i++) {
            GeneratedInputs candidate = visualizerInputs.get(i);
            if (Math.abs(visualizerVariableValue(kind, candidate) - target) > 1e-9) continue;
            double score = Math.abs(candidate.iterationIndex - current.iterationIndex) * 1000.0
                    + Math.abs(candidate.pointIndex - current.pointIndex);
            if (score < bestScore) {
                bestScore = score;
                bestIndex = i;
            }
        }
        return bestIndex;
    }

    private boolean containsClose(List<Double> values, double value) {
        for (Double existing : values) {
            if (Math.abs(existing - value) < 1e-9) return true;
        }
        return false;
    }

    private double visualizerVariableValue(String kind, GeneratedInputs inputs) {
        if ("k".equals(kind)) return inputs.k;
        if ("density".equals(kind)) return inputs.density;
        return inputs.n;
    }

    private String navDeltaLabel(int delta) {
        return String.format(Locale.US, "%+d", delta);
    }

    private void showVisualizerInput(int index, boolean async) {
        if (graphVisualizer == null || index < 0 || index >= visualizerInputs.size()) {
            updateVisualizerNavState();
            return;
        }
        visualizerIndex = index;
        int serial = ++visualizerRequestSerial;
        GeneratedInputs inputs = visualizerInputs.get(index);
        if (visualizerStatusText != null) {
            visualizerStatusText.setText(String.format(
                    Locale.US,
                    "Input %d/%d | n=%d, k=%d, density=%.4f | iteration=%d | seed=%d",
                    index + 1,
                    visualizerInputs.size(),
                    inputs.n,
                    inputs.k,
                    inputs.density,
                    inputs.iterationIndex + 1,
                    inputs.seed
            ));
        }
        if (visualizerLoading != null) {
            visualizerLoading.setTag(Boolean.TRUE);
            visualizerLoading.setVisibility(View.GONE);
            visualizerLoading.postDelayed(() -> {
                if (serial == visualizerRequestSerial && visualizerLoading != null && Boolean.TRUE.equals(visualizerLoading.getTag())) {
                    visualizerLoading.setVisibility(View.VISIBLE);
                    if (visualizerStatusText != null) visualizerStatusText.setText("Fetching Solution...");
                }
            }, 500L);
        }
        Runnable apply = () -> {
            if (serial != visualizerRequestSerial) return;
            graphVisualizer.setInputs(inputs);
            if (visualizerLoading != null) {
                visualizerLoading.setTag(Boolean.FALSE);
                visualizerLoading.setVisibility(View.GONE);
            }
            updateVisualizerNavState();
        };
        if (async) {
            new Thread(() -> runOnUiThread(apply), "android-visualizer-load").start();
        } else {
            apply.run();
        }
    }

    private void updateVisualizerNavState() {
        boolean hasInputs = !visualizerInputs.isEmpty() && visualizerIndex >= 0;
        GeneratedInputs current = hasInputs ? visualizerInputs.get(visualizerIndex) : null;
        for (Map.Entry<String, List<MaterialButton>> entry : visualizerNavButtons.entrySet()) {
            String kind = entry.getKey();
            int optionCount = visualizerOptionCount(kind, current);
            boolean enabled = hasInputs && optionCount > 1;
            for (MaterialButton button : entry.getValue()) button.setEnabled(enabled);
            TextView label = visualizerNavLabels.get(kind);
            if (label != null) {
                label.setText(visualizerNavLabel(kind, current, optionCount));
                label.setEnabled(enabled);
                label.setAlpha(enabled ? 1f : 0.45f);
            }
        }
        if (visualizerStatusText != null && !hasInputs) {
            visualizerStatusText.setText("Run a generated-input benchmark to populate solutions.");
        }
    }

    private int visualizerOptionCount(String kind, GeneratedInputs current) {
        if (visualizerInputs.isEmpty()) return 0;
        if ("solution".equals(kind)) return visualizerInputs.size();
        if ("iteration".equals(kind)) {
            List<Integer> iterations = new ArrayList<>();
            int pointIndex = current == null ? -1 : current.pointIndex;
            for (GeneratedInputs inputs : visualizerInputs) {
                if (inputs.pointIndex == pointIndex && !iterations.contains(inputs.iterationIndex)) {
                    iterations.add(inputs.iterationIndex);
                }
            }
            return iterations.size();
        }
        List<Double> values = new ArrayList<>();
        for (GeneratedInputs inputs : visualizerInputs) {
            double value = visualizerVariableValue(kind, inputs);
            if (!containsClose(values, value)) values.add(value);
        }
        return values.size();
    }

    private String visualizerNavLabel(String kind, GeneratedInputs current, int optionCount) {
        String title;
        if ("n".equals(kind)) title = "N";
        else if ("k".equals(kind)) title = "k";
        else if ("density".equals(kind)) title = "Density";
        else if ("iteration".equals(kind)) title = "Iteration";
        else title = "Solution";
        if (current == null || optionCount <= 0) return title;
        int position = visualizerOptionPosition(kind, current);
        return title + " " + position + "/" + optionCount;
    }

    private int visualizerOptionPosition(String kind, GeneratedInputs current) {
        if ("solution".equals(kind)) return Math.max(1, visualizerIndex + 1);
        if ("iteration".equals(kind)) {
            List<Integer> iterations = new ArrayList<>();
            for (GeneratedInputs inputs : visualizerInputs) {
                if (inputs.pointIndex == current.pointIndex && !iterations.contains(inputs.iterationIndex)) {
                    iterations.add(inputs.iterationIndex);
                }
            }
            Collections.sort(iterations);
            return Math.max(1, iterations.indexOf(current.iterationIndex) + 1);
        }
        List<Double> values = new ArrayList<>();
        for (GeneratedInputs inputs : visualizerInputs) {
            double value = visualizerVariableValue(kind, inputs);
            if (!containsClose(values, value)) values.add(value);
        }
        Collections.sort(values);
        double currentValue = visualizerVariableValue(kind, current);
        for (int i = 0; i < values.size(); i++) {
            if (Math.abs(values.get(i) - currentValue) < 1e-9) return i + 1;
        }
        return 1;
    }

    private void renderStatsTable(BenchmarkSession session) {
        if (statsTableWrap == null) return;
        statsTableWrap.removeAllViews();
        List<RuntimeStatsRow> rows = (session == null || session.trials.isEmpty())
                ? new ArrayList<>()
                : buildRuntimeStatsRows(session);
        String emptyMessage = (session == null || session.trials.isEmpty())
                ? "Run a benchmark to populate runtime statistical comparisons."
                : "No baseline-comparable statistical rows are available.";

        LinearLayout table = new LinearLayout(this);
        table.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout sticky = new LinearLayout(this);
        sticky.setOrientation(LinearLayout.VERTICAL);
        sticky.addView(tableCell("Variant", dp(190), true, Color.WHITE, Color.BLACK));

        HorizontalScrollView scroll = new HorizontalScrollView(this);
        LinearLayout right = new LinearLayout(this);
        right.setOrientation(LinearLayout.VERTICAL);
        LinearLayout header = new LinearLayout(this);
        String[] headings = {"Baseline", "N", "p-value", "Direction", "Mean Delta (ms)", "95% CI (ms)", "Hedges g", "Cliff's Delta", "Mode"};
        int[] widths = {190, 58, 100, 102, 132, 168, 104, 118, 84};
        for (int i = 0; i < headings.length; i++) {
            header.addView(tableCell(headings[i], dp(widths[i]), true, Color.WHITE, Color.BLACK));
        }
        right.addView(header);

        for (RuntimeStatsRow row : rows) {
            int bg = row.n <= 0 ? color(R.color.runner_tertiary_container)
                    : (row.significant ? color(R.color.runner_secondary_container) : color(R.color.runner_surface));
            sticky.addView(tableCell(row.variantLabel, dp(190), false, bg, Color.BLACK));
            LinearLayout line = new LinearLayout(this);
            line.setOrientation(LinearLayout.HORIZONTAL);
            String[] values = {
                    row.baselineLabel,
                    Integer.toString(row.n),
                    formatStats(row.pValue, 6),
                    row.direction,
                    formatStats(row.meanDelta, 3),
                    row.ciText,
                    formatStats(row.hedgesG, 4),
                    formatStats(row.cliffsDelta, 4),
                    row.mode
            };
            for (int i = 0; i < values.length; i++) {
                line.addView(tableCell(values[i], dp(widths[i]), false, bg, Color.BLACK));
            }
            right.addView(line);
        }
        if (rows.isEmpty()) {
            int bg = color(R.color.runner_surface);
            sticky.addView(tableCell("No comparisons", dp(190), false, bg, Color.BLACK));
            LinearLayout line = new LinearLayout(this);
            line.setOrientation(LinearLayout.HORIZONTAL);
            line.addView(tableCell(emptyMessage, dp(widths[0]), false, bg, Color.BLACK));
            for (int i = 1; i < widths.length; i++) {
                line.addView(tableCell("", dp(widths[i]), false, bg, Color.BLACK));
            }
            right.addView(line);
        }
        scroll.addView(right);
        table.addView(sticky, new LinearLayout.LayoutParams(dp(190), -2));
        table.addView(scroll, new LinearLayout.LayoutParams(0, -2, 1f));
        statsTableWrap.addView(table, new LinearLayout.LayoutParams(-1, -2));
    }

    private TextView tableCell(String text, int widthPx, boolean header, int bgColor, int textColor) {
        TextView cell = new TextView(this);
        cell.setText(text);
        cell.setTextSize(header ? 12f : 11f);
        cell.setTextColor(textColor);
        cell.setTypeface(header ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        cell.setGravity(Gravity.CENTER_VERTICAL);
        cell.setSingleLine(false);
        cell.setPadding(dp(8), dp(6), dp(8), dp(6));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(bgColor);
        bg.setStroke(1, Color.BLACK);
        cell.setBackground(bg);
        cell.setMinHeight(dp(44));
        cell.setWidth(widthPx);
        return cell;
    }

    private List<RuntimeStatsRow> buildRuntimeStatsRows(BenchmarkSession session) {
        Map<String, SolverVariant> variants = new LinkedHashMap<>();
        for (SolverVariant variant : solverVariants) variants.put(variant.variantId, variant);
        Map<String, Map<String, Double>> runtimesByKey = new LinkedHashMap<>();
        for (BenchmarkTrial trial : session.trials) {
            if (!"ok".equals(trial.status) || !Double.isFinite(trial.runtimeMs)) continue;
            String key = trial.pointIndex + ":" + trial.iterationIndex;
            runtimesByKey.computeIfAbsent(key, ignored -> new LinkedHashMap<>()).put(trial.variantId, trial.runtimeMs);
        }
        List<RuntimeStatsRow> rows = new ArrayList<>();
        for (SolverVariant variant : solverVariants) {
            if (variant.isBaseline() || !session.config.selectedVariants.contains(variant.variantId)) continue;
            String baselineId = baselineForFamily(variant.family);
            if (baselineId == null || !session.config.selectedVariants.contains(baselineId)) continue;
            List<Double> variantSamples = new ArrayList<>();
            List<Double> baselineSamples = new ArrayList<>();
            List<Double> deltas = new ArrayList<>();
            for (Map<String, Double> byVariant : runtimesByKey.values()) {
                Double v = byVariant.get(variant.variantId);
                Double b = byVariant.get(baselineId);
                if (v != null && b != null) {
                    variantSamples.add(v);
                    baselineSamples.add(b);
                    deltas.add(v - b);
                }
            }
            rows.add(runtimeStatsRow(variant, variants.get(baselineId), variantSamples, baselineSamples, deltas));
        }
        return rows;
    }

    private RuntimeStatsRow runtimeStatsRow(SolverVariant variant, SolverVariant baseline, List<Double> variantSamples, List<Double> baselineSamples, List<Double> deltas) {
        RuntimeStatsRow row = new RuntimeStatsRow();
        row.variantLabel = variant.label;
        row.baselineLabel = baseline == null ? baselineForFamily(variant.family) : baseline.label;
        row.n = deltas.size();
        row.mode = "paired";
        if (row.n <= 0) {
            row.direction = "insufficient";
            row.ciText = "[n/a, n/a]";
            return row;
        }
        row.meanDelta = mean(deltas);
        double sd = stdev(deltas);
        double se = row.n < 2 ? 0.0 : sd / Math.sqrt(row.n);
        double margin = row.n < 2 ? 0.0 : 1.96 * se;
        row.ciText = "[" + formatStats(row.meanDelta - margin, 3) + ", " + formatStats(row.meanDelta + margin, 3) + "]";
        row.direction = row.meanDelta < 0.0 ? "faster" : (row.meanDelta > 0.0 ? "slower" : "same");
        row.pValue = row.n < 2 || se <= 0.0 ? null : normalTwoSidedP(Math.abs(row.meanDelta / se));
        row.hedgesG = sd <= 0.0 ? null : row.meanDelta / sd;
        row.cliffsDelta = cliffsDelta(variantSamples, baselineSamples);
        row.significant = row.pValue != null && row.pValue < 0.05;
        return row;
    }

    private String baselineForFamily(String family) {
        if ("vf3".equals(family)) return "vf3_baseline";
        if ("glasgow".equals(family)) return "glasgow_baseline";
        if ("dijkstra".equals(family)) return "dijkstra_baseline";
        if ("sp_via".equals(family)) return "sp_via_baseline";
        return null;
    }

    private double mean(List<Double> values) {
        double sum = 0.0;
        for (double value : values) sum += value;
        return values.isEmpty() ? 0.0 : sum / values.size();
    }

    private double stdev(List<Double> values) {
        if (values.size() < 2) return 0.0;
        double mean = mean(values);
        double sum = 0.0;
        for (double value : values) {
            double d = value - mean;
            sum += d * d;
        }
        return Math.sqrt(sum / (values.size() - 1));
    }

    private Double cliffsDelta(List<Double> left, List<Double> right) {
        if (left.isEmpty() || right.isEmpty()) return null;
        long greater = 0;
        long less = 0;
        for (double a : left) {
            for (double b : right) {
                if (a > b) greater++;
                if (a < b) less++;
            }
        }
        return (greater - less) / (double) (left.size() * right.size());
    }

    private Double normalTwoSidedP(double z) {
        if (!Double.isFinite(z)) return 0.0;
        double cdf = 0.5 * (1.0 + erf(z / Math.sqrt(2.0)));
        return Math.max(0.0, Math.min(1.0, 2.0 * (1.0 - cdf)));
    }

    private double erf(double x) {
        double sign = x < 0 ? -1.0 : 1.0;
        x = Math.abs(x);
        double t = 1.0 / (1.0 + 0.3275911 * x);
        double y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
        return sign * y;
    }

    private String formatStats(Double value, int decimals) {
        if (value == null || !Double.isFinite(value)) return "n/a";
        return String.format(Locale.US, "%." + decimals + "f", value);
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
            suppressNavigationCallback = true;
            try {
                navigationView.setSelectedItemId(navId);
            } finally {
                suppressNavigationCallback = false;
            }
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
        input.setTextColor(Color.BLACK);
        input.setHintTextColor(color(R.color.runner_muted));
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
        view.setTextColor(Color.BLACK);
        view.setHintTextColor(color(R.color.runner_muted));
        view.setInputType(InputType.TYPE_NULL);
        view.setText(selected, false);
        view.setOnItemClickListener((parent, view1, position, id) -> updateRunEstimate());
        return view;
    }

    private TextInputLayout textField(String label, TextView editText, String helper) {
        TextInputLayout layout = new TextInputLayout(this);
        layout.setHint(label);
        layout.setBoxBackgroundMode(TextInputLayout.BOX_BACKGROUND_OUTLINE);
        layout.setBoxBackgroundColor(color(R.color.runner_surface));
        layout.setBoxStrokeColor(Color.BLACK);
        layout.setHintTextColor(ColorStateList.valueOf(Color.BLACK));
        layout.setDefaultHintTextColor(ColorStateList.valueOf(color(R.color.runner_muted)));
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

    private MaterialButton compactNavButton(String text) {
        MaterialButton button = new MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
        button.setText(text);
        button.setTextSize(12f);
        button.setTextColor(navButtonTextColors());
        button.setAllCaps(false);
        button.setMinWidth(0);
        button.setMinimumWidth(0);
        button.setMinHeight(dp(40));
        button.setMinimumHeight(dp(40));
        button.setInsetTop(0);
        button.setInsetBottom(0);
        button.setIcon(null);
        button.setGravity(Gravity.CENTER);
        button.setPadding(0, 0, 0, 0);
        return button;
    }

    private MaterialButton iconOnlyButton(int iconRes, String description) {
        MaterialButton button = new MaterialButton(this, null, com.google.android.material.R.attr.materialIconButtonStyle);
        button.setIconResource(iconRes);
        button.setText("");
        button.setContentDescription(description);
        button.setMinWidth(dp(48));
        button.setMinHeight(dp(48));
        return button;
    }

    private View iconAction(MaterialButton button, String label) {
        LinearLayout wrap = new LinearLayout(this);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.setGravity(Gravity.CENTER);
        TextView text = new TextView(this);
        text.setText(label);
        text.setTextColor(color(R.color.runner_text));
        text.setTextSize(12f);
        text.setGravity(Gravity.CENTER);
        if ("Pause".equals(label)) pauseActionLabel = text;
        wrap.addView(button, new LinearLayout.LayoutParams(dp(52), dp(48)));
        wrap.addView(text, new LinearLayout.LayoutParams(-1, -2));
        return wrap;
    }

    private Space space(int width, int height) {
        Space space = new Space(this);
        space.setMinimumWidth(width);
        space.setMinimumHeight(height);
        return space;
    }

    private ColorStateList variantChipColors() {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{color(R.color.runner_secondary_container), color(R.color.runner_surface)}
        );
    }

    private ColorStateList variantChipStrokeColors() {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{color(R.color.runner_secondary), Color.BLACK}
        );
    }

    private ColorStateList variantChipTextColors() {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{Color.BLACK, Color.BLACK}
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

    private ColorStateList navButtonTextColors() {
        return new ColorStateList(
                new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}},
                new int[]{color(R.color.runner_muted), color(R.color.runner_primary)}
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
        return "independent";
    }

    private String selectedRunMode() {
        return runModeToggle != null && runModeToggle.getCheckedButtonId() == RUN_TIMED ? "timed" : "threshold";
    }

    private String selectedKMode() {
        return kModeToggle != null && kModeToggle.getCheckedButtonId() == K_PERCENT ? "percent" : "absolute";
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

    private String readableError(Throwable error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty() ? error.getClass().getSimpleName() : message;
    }

    private int color(int resId) {
        return getColor(resId);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private static final class RuntimeStatsRow {
        String variantLabel = "";
        String baselineLabel = "";
        int n;
        Double pValue;
        String direction = "";
        double meanDelta;
        String ciText = "";
        Double hedgesG;
        Double cliffsDelta;
        String mode = "";
        boolean significant;
    }
}
