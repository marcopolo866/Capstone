package edu.uidaho.capstone.androidrunner.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.AttributeSet;
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
    private String metric = "runtime";

    public BenchmarkChartView(Context context) {
        super(context);
    }

    public BenchmarkChartView(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    public void setDatapoints(List<BenchmarkDatapoint> rows, String metric) {
        datapoints.clear();
        if (rows != null) datapoints.addAll(rows);
        this.metric = metric == null ? "runtime" : metric;
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.WHITE);
        int w = getWidth();
        int h = getHeight();
        int left = 64;
        int top = 28;
        int right = Math.max(left + 1, w - 24);
        int bottom = Math.max(top + 1, h - 48);
        paint.setColor(Color.rgb(214, 220, 227));
        paint.setStyle(Paint.Style.STROKE);
        canvas.drawRect(new RectF(left, top, right, bottom), paint);
        paint.setTextSize(28f);
        paint.setColor(Color.rgb(31, 41, 51));
        canvas.drawText("runtime".equals(metric) ? "Runtime (ms)" : "Memory (kB)", left, 24, paint);
        if (datapoints.isEmpty()) {
            paint.setTextSize(32f);
            paint.setColor(Color.rgb(95, 107, 118));
            canvas.drawText("Run a benchmark to populate this chart.", left + 20, top + 80, paint);
            return;
        }

        double minX = Double.POSITIVE_INFINITY;
        double maxX = Double.NEGATIVE_INFINITY;
        double maxY = 0.0;
        Map<String, List<BenchmarkDatapoint>> byVariant = new LinkedHashMap<>();
        for (BenchmarkDatapoint row : datapoints) {
            byVariant.computeIfAbsent(row.variantLabel, ignored -> new ArrayList<>()).add(row);
            minX = Math.min(minX, row.xValue);
            maxX = Math.max(maxX, row.xValue);
            Double y = "runtime".equals(metric) ? row.runtimeMedianMs : row.memoryMedianKb;
            if (y != null) maxY = Math.max(maxY, y);
        }
        if (!Double.isFinite(minX) || !Double.isFinite(maxX) || maxX <= minX) {
            minX = 0.0;
            maxX = 1.0;
        }
        if (maxY <= 0.0) maxY = 1.0;

        int[] colors = {
                Color.rgb(11, 92, 173),
                Color.rgb(10, 125, 50),
                Color.rgb(154, 103, 0),
                Color.rgb(176, 0, 32),
                Color.rgb(72, 61, 139),
                Color.rgb(0, 120, 120)
        };
        int colorIdx = 0;
        for (Map.Entry<String, List<BenchmarkDatapoint>> entry : byVariant.entrySet()) {
            paint.setColor(colors[colorIdx % colors.length]);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(4f);
            List<BenchmarkDatapoint> rows = entry.getValue();
            rows.sort((a, b) -> Double.compare(a.xValue, b.xValue));
            float lastX = Float.NaN;
            float lastY = Float.NaN;
            for (BenchmarkDatapoint row : rows) {
                Double yValue = "runtime".equals(metric) ? row.runtimeMedianMs : row.memoryMedianKb;
                if (yValue == null) continue;
                float x = (float) (left + ((row.xValue - minX) / (maxX - minX)) * (right - left));
                float y = (float) (bottom - (yValue / maxY) * (bottom - top));
                if (!Float.isNaN(lastX)) canvas.drawLine(lastX, lastY, x, y, paint);
                paint.setStyle(Paint.Style.FILL);
                canvas.drawCircle(x, y, 6f, paint);
                paint.setStyle(Paint.Style.STROKE);
                lastX = x;
                lastY = y;
            }
            paint.setStyle(Paint.Style.FILL);
            paint.setTextSize(22f);
            canvas.drawText(entry.getKey(), left + 12, bottom + 28 + (colorIdx * 24), paint);
            colorIdx++;
        }

        paint.setColor(Color.rgb(95, 107, 118));
        paint.setTextSize(22f);
        canvas.drawText(String.format(Locale.US, "%.2f", minX), left, bottom + 24, paint);
        canvas.drawText(String.format(Locale.US, "%.2f", maxX), right - 60, bottom + 24, paint);
        canvas.drawText(String.format(Locale.US, "%.2f", maxY), 8, top + 8, paint);
    }
}
