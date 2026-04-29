package edu.uidaho.capstone.androidrunner.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.View;

import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkDatapoint;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class BenchmarkChartView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<BenchmarkDatapoint> datapoints = new ArrayList<>();
    private final List<ChartPoint> renderedPoints = new ArrayList<>();
    private final List<ChartSegment> renderedSegments = new ArrayList<>();
    private final List<LegendHit> legendHits = new ArrayList<>();
    private final RectF plot = new RectF();
    private String metric = "runtime";
    private ChartPoint selectedPoint;
    private String activeVariantLabel;
    private boolean showErrorBars;

    private final int[] seriesColors = {
            Color.rgb(0, 114, 178),
            Color.rgb(0, 158, 115),
            Color.rgb(230, 159, 0),
            Color.rgb(213, 94, 0),
            Color.rgb(204, 121, 167),
            Color.rgb(86, 180, 233),
            Color.rgb(90, 74, 148),
            Color.rgb(0, 121, 120)
    };

    public BenchmarkChartView(Context context) {
        super(context);
        init();
    }

    public BenchmarkChartView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    private void init() {
        setFocusable(true);
        setContentDescription("Benchmark chart. Run a benchmark to populate data.");
    }

    public void setDatapoints(List<BenchmarkDatapoint> rows, String metric) {
        datapoints.clear();
        if (rows != null) datapoints.addAll(rows);
        this.metric = metric == null ? "runtime" : metric;
        selectedPoint = null;
        activeVariantLabel = null;
        updateContentDescription();
        invalidate();
    }

    public void setShowErrorBars(boolean showErrorBars) {
        if (this.showErrorBars == showErrorBars) return;
        this.showErrorBars = showErrorBars;
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.WHITE);
        int w = getWidth();
        int h = getHeight();
        if (w <= 0 || h <= 0) return;

        int left = dp(58);
        int top = dp(44);
        int right = Math.max(left + 1, w - dp(18));
        int bottom = Math.max(top + 1, h - dp(76));
        plot.set(left, top, right, bottom);

        drawTitle(canvas);
        drawPlotFrame(canvas);

        if (datapoints.isEmpty()) {
            drawEmptyState(canvas);
            return;
        }

        Bounds bounds = computeBounds();
        renderedPoints.clear();
        renderedSegments.clear();
        legendHits.clear();
        drawGrid(canvas, bounds);
        drawSeries(canvas, bounds);
        drawLegend(canvas);
        drawSelection(canvas);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_MOVE) {
            getParent().requestDisallowInterceptTouchEvent(true);
            ChartPoint nearest = nearestPoint(event.getX(), event.getY());
            String nearestVariant = nearestLegendVariant(event.getX(), event.getY());
            if (nearestVariant == null) nearestVariant = nearestVariant(event.getX(), event.getY(), nearest);
            if (activeVariantLabel == null) activeVariantLabel = nearestVariant;
            selectedPoint = nearest != null && activeVariantLabel != null
                    && activeVariantLabel.equals(nearest.row.variantLabel) ? nearest : null;
            if (activeVariantLabel != null) {
                String valueText = selectedPoint == null
                        ? activeVariantLabel
                        : selectedPoint.row.variantLabel + ", " + selectedPoint.row.pointLabel + ", "
                        + metricLabel() + " " + formatValue(selectedPoint.value);
                setContentDescription(valueText);
            }
            invalidate();
            return true;
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            getParent().requestDisallowInterceptTouchEvent(false);
            selectedPoint = null;
            activeVariantLabel = null;
            updateContentDescription();
            invalidate();
            return true;
        }
        return true;
    }

    private void drawTitle(Canvas canvas) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(24, 33, 43));
        paint.setTextSize(dp(16));
        paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        canvas.drawText(metricTitle(), dp(16), dp(24), paint);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(11));
        paint.setColor(Color.rgb(93, 104, 117));
        canvas.drawText("Press and hold a line or legend name to isolate it", dp(16), dp(40), paint);
    }

    private void drawPlotFrame(Canvas canvas) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(247, 248, 250));
        canvas.drawRoundRect(plot, dp(8), dp(8), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(1));
        paint.setColor(Color.rgb(188, 199, 211));
        canvas.drawRoundRect(plot, dp(8), dp(8), paint);
    }

    private void drawEmptyState(Canvas canvas) {
        paint.setStyle(Paint.Style.FILL);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(14));
        paint.setColor(Color.rgb(93, 104, 117));
        canvas.drawText("Run a benchmark to populate this chart.", plot.left + dp(16), plot.top + dp(46), paint);
    }

    private void drawGrid(Canvas canvas, Bounds bounds) {
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(10));
        paint.setStrokeWidth(dp(1));
        for (int i = 0; i <= 4; i++) {
            float y = plot.bottom - (plot.height() * i / 4f);
            paint.setStyle(Paint.Style.STROKE);
            paint.setColor(i == 0 ? Color.rgb(140, 151, 164) : Color.rgb(225, 230, 236));
            canvas.drawLine(plot.left, y, plot.right, y, paint);
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(93, 104, 117));
            double value = bounds.maxY * i / 4.0;
            canvas.drawText(formatAxis(value), dp(6), y + dp(4), paint);
        }
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(93, 104, 117));
        canvas.drawText(formatAxis(bounds.minX), plot.left, plot.bottom + dp(20), paint);
        String max = formatAxis(bounds.maxX);
        canvas.drawText(max, plot.right - paint.measureText(max), plot.bottom + dp(20), paint);
    }

    private void drawSeries(Canvas canvas, Bounds bounds) {
        Map<String, List<BenchmarkDatapoint>> byVariant = new LinkedHashMap<>();
        for (BenchmarkDatapoint row : datapoints) {
            byVariant.computeIfAbsent(row.variantLabel, ignored -> new ArrayList<>()).add(row);
        }
        int colorIdx = 0;
        for (Map.Entry<String, List<BenchmarkDatapoint>> entry : byVariant.entrySet()) {
            int color = seriesColors[colorIdx % seriesColors.length];
            if (activeVariantLabel != null && !activeVariantLabel.equals(entry.getKey())) {
                colorIdx++;
                continue;
            }
            List<BenchmarkDatapoint> rows = entry.getValue();
            rows.sort((a, b) -> Double.compare(a.xValue, b.xValue));
            float lastX = Float.NaN;
            float lastY = Float.NaN;
            paint.setStrokeWidth(dp(2));
            paint.setColor(color);
            for (BenchmarkDatapoint row : rows) {
                Double value = valueFor(row);
                if (value == null) continue;
                float x = xFor(row.xValue, bounds);
                float y = yFor(value, bounds);
                if (!Float.isNaN(lastX)) {
                    paint.setStyle(Paint.Style.STROKE);
                    canvas.drawLine(lastX, lastY, x, y, paint);
                    renderedSegments.add(new ChartSegment(row.variantLabel, lastX, lastY, x, y));
                }
                if (showErrorBars) drawErrorBar(canvas, row, x, bounds, color);
                renderedPoints.add(new ChartPoint(row, value, x, y, color));
                lastX = x;
                lastY = y;
            }
            colorIdx++;
        }
    }

    private void drawErrorBar(Canvas canvas, BenchmarkDatapoint row, float x, Bounds bounds, int color) {
        Double value = valueFor(row);
        double stdev = stdevFor(row);
        if (value == null || !Double.isFinite(stdev) || stdev <= 0.0) return;
        float yHigh = yFor(value + stdev, bounds);
        float yLow = yFor(Math.max(0.0, value - stdev), bounds);
        float cap = dp(4);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(1));
        paint.setColor(color);
        canvas.drawLine(x, yHigh, x, yLow, paint);
        canvas.drawLine(x - cap, yHigh, x + cap, yHigh, paint);
        canvas.drawLine(x - cap, yLow, x + cap, yLow, paint);
    }

    private void drawLegend(Canvas canvas) {
        Map<String, Integer> colorsByVariant = new LinkedHashMap<>();
        int colorIdx = 0;
        for (BenchmarkDatapoint row : datapoints) {
            if (!colorsByVariant.containsKey(row.variantLabel)) {
                colorsByVariant.put(row.variantLabel, seriesColors[colorIdx % seriesColors.length]);
                colorIdx++;
            }
        }
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(10));
        float x = dp(16);
        float y = getHeight() - dp(38);
        for (Map.Entry<String, Integer> entry : colorsByVariant.entrySet()) {
            String label = shortLegend(entry.getKey());
            float width = paint.measureText(label) + dp(28);
            if (x + width > getWidth() - dp(16)) {
                x = dp(16);
                y += dp(18);
            }
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(entry.getValue());
            canvas.drawCircle(x + dp(7), y - dp(4), dp(4), paint);
            paint.setColor(Color.rgb(24, 33, 43));
            canvas.drawText(label, x + dp(16), y, paint);
            legendHits.add(new LegendHit(entry.getKey(), new RectF(x, y - dp(16), x + width, y + dp(6))));
            x += width + dp(10);
        }
    }

    private void drawSelection(Canvas canvas) {
        if (selectedPoint == null) return;
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.WHITE);
        canvas.drawCircle(selectedPoint.x, selectedPoint.y, dp(8), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(2));
        paint.setColor(selectedPoint.color);
        canvas.drawCircle(selectedPoint.x, selectedPoint.y, dp(8), paint);

        String label = selectedPoint.row.variantLabel + " | " + formatValue(selectedPoint.value);
        paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        paint.setTextSize(dp(11));
        float width = Math.min(getWidth() - dp(24), paint.measureText(label) + dp(20));
        float left = Math.max(dp(12), Math.min(selectedPoint.x - width / 2f, getWidth() - width - dp(12)));
        float top = Math.max(dp(48), selectedPoint.y - dp(46));
        RectF bubble = new RectF(left, top, left + width, top + dp(30));
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(24, 33, 43));
        canvas.drawRoundRect(bubble, dp(8), dp(8), paint);
        paint.setColor(Color.WHITE);
        canvas.drawText(label, bubble.left + dp(10), bubble.top + dp(20), paint);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
    }

    private Bounds computeBounds() {
        Bounds bounds = new Bounds();
        for (BenchmarkDatapoint row : datapoints) {
            bounds.minX = Math.min(bounds.minX, row.xValue);
            bounds.maxX = Math.max(bounds.maxX, row.xValue);
            Double y = valueFor(row);
            if (y != null) {
                double high = y + (showErrorBars ? Math.max(0.0, stdevFor(row)) : 0.0);
                bounds.maxY = Math.max(bounds.maxY, high);
            }
        }
        if (!Double.isFinite(bounds.minX) || !Double.isFinite(bounds.maxX) || bounds.maxX <= bounds.minX) {
            bounds.minX = 0.0;
            bounds.maxX = 1.0;
        }
        if (bounds.maxY <= 0.0) bounds.maxY = 1.0;
        return bounds;
    }

    private ChartPoint nearestPoint(float x, float y) {
        ChartPoint nearest = null;
        float best = dp(36) * dp(36);
        for (ChartPoint point : renderedPoints) {
            float dx = point.x - x;
            float dy = point.y - y;
            float dist = dx * dx + dy * dy;
            if (dist < best) {
                best = dist;
                nearest = point;
            }
        }
        return nearest;
    }

    private String nearestVariant(float x, float y, ChartPoint nearestPoint) {
        String nearest = nearestPoint == null ? null : nearestPoint.row.variantLabel;
        float best = nearestPoint == null ? dp(42) * dp(42) : distanceSquared(x, y, nearestPoint.x, nearestPoint.y);
        for (ChartSegment segment : renderedSegments) {
            float dist = segment.distanceSquaredTo(x, y);
            if (dist < best) {
                best = dist;
                nearest = segment.variantLabel;
            }
        }
        return best <= dp(42) * dp(42) ? nearest : null;
    }

    private String nearestLegendVariant(float x, float y) {
        for (LegendHit hit : legendHits) {
            if (hit.bounds.contains(x, y)) return hit.variantLabel;
        }
        return null;
    }

    private float distanceSquared(float ax, float ay, float bx, float by) {
        float dx = ax - bx;
        float dy = ay - by;
        return dx * dx + dy * dy;
    }

    private float xFor(double value, Bounds bounds) {
        return (float) (plot.left + ((value - bounds.minX) / (bounds.maxX - bounds.minX)) * plot.width());
    }

    private float yFor(double value, Bounds bounds) {
        return (float) (plot.bottom - (value / bounds.maxY) * plot.height());
    }

    private Double valueFor(BenchmarkDatapoint row) {
        return "runtime".equals(metric) ? row.runtimeMedianMs : row.memoryMedianKb;
    }

    private double stdevFor(BenchmarkDatapoint row) {
        return "runtime".equals(metric) ? row.runtimeStdevMs : row.memoryStdevKb;
    }

    private String metricTitle() {
        return "runtime".equals(metric) ? "Runtime by variant" : "Memory by variant";
    }

    private String metricLabel() {
        return "runtime".equals(metric) ? "runtime" : "memory";
    }

    private String formatValue(double value) {
        return "runtime".equals(metric)
                ? String.format(Locale.US, "%.3f ms", value)
                : String.format(Locale.US, "%.1f kB", value);
    }

    private String formatAxis(double value) {
        if (Math.abs(value) >= 1000.0) return String.format(Locale.US, "%.0f", value);
        if (Math.abs(value) >= 10.0) return String.format(Locale.US, "%.1f", value);
        return String.format(Locale.US, "%.2f", value);
    }

    private String shortLegend(String label) {
        if (label.length() <= 22) return label;
        return label.substring(0, 19) + "...";
    }

    private void updateContentDescription() {
        if (datapoints.isEmpty()) {
            setContentDescription("Benchmark chart. No datapoints.");
            return;
        }
        setContentDescription(metricTitle() + " with " + datapoints.size() + " datapoints.");
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private static final class Bounds {
        double minX = Double.POSITIVE_INFINITY;
        double maxX = Double.NEGATIVE_INFINITY;
        double maxY = 0.0;
    }

    private static final class ChartPoint {
        final BenchmarkDatapoint row;
        final double value;
        final float x;
        final float y;
        final int color;

        ChartPoint(BenchmarkDatapoint row, double value, float x, float y, int color) {
            this.row = row;
            this.value = value;
            this.x = x;
            this.y = y;
            this.color = color;
        }
    }

    private static final class ChartSegment {
        final String variantLabel;
        final float x1;
        final float y1;
        final float x2;
        final float y2;

        ChartSegment(String variantLabel, float x1, float y1, float x2, float y2) {
            this.variantLabel = variantLabel;
            this.x1 = x1;
            this.y1 = y1;
            this.x2 = x2;
            this.y2 = y2;
        }

        float distanceSquaredTo(float x, float y) {
            float dx = x2 - x1;
            float dy = y2 - y1;
            float lengthSquared = dx * dx + dy * dy;
            if (lengthSquared <= 0f) {
                float ex = x - x1;
                float ey = y - y1;
                return ex * ex + ey * ey;
            }
            float t = ((x - x1) * dx + (y - y1) * dy) / lengthSquared;
            t = Math.max(0f, Math.min(1f, t));
            float px = x1 + t * dx;
            float py = y1 + t * dy;
            float ex = x - px;
            float ey = y - py;
            return ex * ex + ey * ey;
        }
    }

    private static final class LegendHit {
        final String variantLabel;
        final RectF bounds;

        LegendHit(String variantLabel, RectF bounds) {
            this.variantLabel = variantLabel;
            this.bounds = bounds;
        }
    }
}
