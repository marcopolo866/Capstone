package edu.uidaho.capstone.androidrunner.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;

import edu.uidaho.capstone.androidrunner.engine.GeneratedInputs;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class GraphVisualizerView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<int[]> targetEdges = new ArrayList<>();
    private final List<int[]> patternEdges = new ArrayList<>();
    private final List<Integer> solutionNodes = new ArrayList<>();
    private final RectF graphArea = new RectF();
    private final RectF patternBounds = new RectF();
    private final RectF targetBounds = new RectF();
    private ScaleGestureDetector scaleDetector;
    private int targetNodeCount = 0;
    private int patternNodeCount = 0;
    private String caption = "No graph loaded";
    private boolean showLabels = true;
    private float scale = 1f;
    private float offsetX = 0f;
    private float offsetY = 0f;
    private float lastX;
    private float lastY;
    private boolean dragging;

    public GraphVisualizerView(Context context) {
        super(context);
        init(context);
    }

    public GraphVisualizerView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init(context);
    }

    private void init(Context context) {
        setFocusable(true);
        setContentDescription("Graph visualizer. No graph loaded.");
        scaleDetector = new ScaleGestureDetector(context, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override
            public boolean onScale(ScaleGestureDetector detector) {
                float next = scale * detector.getScaleFactor();
                scale = Math.max(0.55f, Math.min(4.0f, next));
                invalidate();
                return true;
            }
        });
    }

    public void setInputs(GeneratedInputs inputs) {
        targetEdges.clear();
        patternEdges.clear();
        solutionNodes.clear();
        if (inputs == null) {
            targetNodeCount = 0;
            patternNodeCount = 0;
            caption = "No graph loaded";
            setContentDescription("Graph visualizer. No graph loaded.");
        } else {
            targetNodeCount = inputs.targetNodeCount;
            patternNodeCount = inputs.patternNodeCount;
            targetEdges.addAll(inputs.targetEdges);
            patternEdges.addAll(inputs.patternEdges);
            solutionNodes.addAll(inputs.solutionNodes);
            caption = "Seed " + inputs.seed + ": subgraph " + patternNodeCount
                    + " nodes, supergraph " + targetNodeCount + " nodes";
            setContentDescription(caption);
        }
        resetViewport();
    }

    public void setShowLabels(boolean showLabels) {
        this.showLabels = showLabels;
        invalidate();
    }

    public void resetViewport() {
        scale = 1f;
        offsetX = 0f;
        offsetY = 0f;
        invalidate();
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (targetNodeCount <= 0 && patternNodeCount <= 0) return true;
        if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(true);
        scaleDetector.onTouchEvent(event);
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                lastX = event.getX();
                lastY = event.getY();
                dragging = true;
                return true;
            case MotionEvent.ACTION_MOVE:
                if (dragging && !scaleDetector.isInProgress() && event.getPointerCount() == 1) {
                    float x = event.getX();
                    float y = event.getY();
                    offsetX += x - lastX;
                    offsetY += y - lastY;
                    lastX = x;
                    lastY = y;
                    invalidate();
                }
                return true;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                dragging = false;
                if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
                return true;
            default:
                return true;
        }
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.rgb(247, 248, 250));
        drawHeader(canvas);
        layoutPanels();

        if (targetNodeCount <= 0 && patternNodeCount <= 0) {
            drawEmptyState(canvas);
            return;
        }

        canvas.save();
        float cx = graphArea.centerX();
        float cy = graphArea.centerY();
        canvas.translate(offsetX, offsetY);
        canvas.scale(scale, scale, cx, cy);
        if (patternNodeCount > 0) {
            drawGraph(canvas, patternBounds, "Subgraph", patternNodeCount, patternEdges, allHighlighted(patternNodeCount), true);
        }
        if (targetNodeCount > 0) {
            drawGraph(canvas, targetBounds, "Supergraph", targetNodeCount, targetEdges, targetHighlights(), false);
        }
        canvas.restore();

        drawScaleBadge(canvas);
    }

    private void layoutPanels() {
        graphArea.set(dp(8), dp(54), getWidth() - dp(8), getHeight() - dp(8));
        if (patternNodeCount > 0 && targetNodeCount > 0) {
            float mid = graphArea.top + graphArea.height() * 0.42f;
            patternBounds.set(graphArea.left, graphArea.top, graphArea.right, mid - dp(4));
            targetBounds.set(graphArea.left, mid + dp(4), graphArea.right, graphArea.bottom);
        } else if (patternNodeCount > 0) {
            patternBounds.set(graphArea);
            targetBounds.setEmpty();
        } else {
            targetBounds.set(graphArea);
            patternBounds.setEmpty();
        }
    }

    private void drawHeader(Canvas canvas) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(24, 33, 43));
        paint.setTextSize(dp(16));
        paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        canvas.drawText(caption, dp(12), dp(24), paint);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(11));
        paint.setColor(Color.rgb(93, 104, 117));
        String meta = targetNodeCount <= 0 ? "Generated graphs appear after a run starts."
                : String.format(Locale.US, "Scale %.0f%% | labels %s | highlighted nodes %d",
                scale * 100f, showLabels ? "on" : "off", solutionNodes.size());
        canvas.drawText(meta, dp(12), dp(42), paint);
    }

    private void drawGraph(
            Canvas canvas,
            RectF bounds,
            String title,
            int nodeCount,
            List<int[]> edges,
            boolean[] highlighted,
            boolean pattern
    ) {
        drawPanel(canvas, bounds);
        paint.setStyle(Paint.Style.FILL);
        paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        paint.setTextSize(dp(13));
        paint.setColor(Color.rgb(24, 33, 43));
        canvas.drawText(title, bounds.left + dp(12), bounds.top + dp(22), paint);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(10));
        paint.setColor(Color.rgb(93, 104, 117));
        canvas.drawText(nodeCount + " nodes, " + edges.size() + " edges", bounds.left + dp(12), bounds.top + dp(38), paint);

        RectF plot = new RectF(bounds.left + dp(10), bounds.top + dp(46), bounds.right - dp(10), bounds.bottom - dp(10));
        float[] xs = new float[nodeCount];
        float[] ys = new float[nodeCount];
        float radius = Math.max(dp(28), Math.min(plot.width(), plot.height()) * 0.38f);
        float cx = plot.centerX();
        float cy = plot.centerY();
        for (int i = 0; i < nodeCount; i++) {
            double angle = (2.0 * Math.PI * i) / Math.max(1, nodeCount) - Math.PI / 2.0;
            xs[i] = cx + (float) Math.cos(angle) * radius;
            ys[i] = cy + (float) Math.sin(angle) * radius;
        }

        drawEdges(canvas, bounds, xs, ys, nodeCount, edges, highlighted);
        drawNodes(canvas, xs, ys, nodeCount, highlighted, pattern);
    }

    private void drawPanel(Canvas canvas, RectF bounds) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.WHITE);
        canvas.drawRoundRect(bounds, dp(8), dp(8), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(1));
        paint.setColor(Color.rgb(188, 199, 211));
        canvas.drawRoundRect(bounds, dp(8), dp(8), paint);
    }

    private void drawEmptyState(Canvas canvas) {
        drawPanel(canvas, graphArea);
        paint.setStyle(Paint.Style.FILL);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(14));
        paint.setColor(Color.rgb(93, 104, 117));
        canvas.drawText("No generated graph available.", graphArea.left + dp(18), graphArea.top + dp(42), paint);
    }

    private void drawEdges(Canvas canvas, RectF bounds, float[] xs, float[] ys, int nodeCount, List<int[]> edges, boolean[] highlighted) {
        int edgeLimit = Math.min(edges.size(), 4000);
        for (int i = 0; i < edgeLimit; i++) {
            int[] edge = edges.get(i);
            if (edge.length < 2) continue;
            int u = edge[0];
            int v = edge[1];
            if (u < 0 || u >= nodeCount || v < 0 || v >= nodeCount) continue;
            boolean highlightedEdge = highlighted[u] && highlighted[v];
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(highlightedEdge ? dp(3) : (nodeCount > 120 ? dp(1) : dp(1.5f)));
            paint.setColor(highlightedEdge ? Color.rgb(29, 122, 80) : Color.rgb(178, 188, 199));
            canvas.drawLine(xs[u], ys[u], xs[v], ys[v], paint);
        }
        if (edges.size() > edgeLimit) {
            paint.setStyle(Paint.Style.FILL);
            paint.setTextSize(dp(10));
            paint.setColor(Color.rgb(93, 104, 117));
            canvas.drawText("+" + (edges.size() - edgeLimit) + " edges hidden", bounds.left + dp(12), bounds.bottom - dp(12), paint);
        }
    }

    private void drawNodes(Canvas canvas, float[] xs, float[] ys, int nodeCount, boolean[] highlighted, boolean pattern) {
        float nodeRadius = nodeCount > 160 ? dp(4) : (nodeCount > 80 ? dp(6) : dp(9));
        for (int i = 0; i < nodeCount; i++) {
            boolean highlightedNode = highlighted[i];
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(highlightedNode ? Color.rgb(29, 122, 80) : Color.rgb(11, 87, 163));
            canvas.drawCircle(xs[i], ys[i], highlightedNode ? nodeRadius + dp(3) : nodeRadius, paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(highlightedNode ? dp(2) : dp(1));
            paint.setColor(highlightedNode ? Color.rgb(0, 0, 0) : Color.WHITE);
            canvas.drawCircle(xs[i], ys[i], highlightedNode ? nodeRadius + dp(3) : nodeRadius, paint);
            if (showLabels && nodeCount <= 120) {
                paint.setStyle(Paint.Style.FILL);
                paint.setColor(Color.rgb(24, 33, 43));
                paint.setTextSize(nodeCount > 80 ? dp(7) : dp(9));
                paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
                String label = pattern && i < solutionNodes.size() ? i + "->" + solutionNodes.get(i) : Integer.toString(i);
                canvas.drawText(label, xs[i] + nodeRadius + dp(2), ys[i] + dp(3), paint);
            }
        }
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
    }

    private boolean[] targetHighlights() {
        boolean[] highlighted = new boolean[Math.max(0, targetNodeCount)];
        for (Integer node : solutionNodes) {
            if (node != null && node >= 0 && node < highlighted.length) highlighted[node] = true;
        }
        return highlighted;
    }

    private boolean[] allHighlighted(int count) {
        boolean[] highlighted = new boolean[Math.max(0, count)];
        for (int i = 0; i < highlighted.length; i++) highlighted[i] = true;
        return highlighted;
    }

    private void drawScaleBadge(Canvas canvas) {
        String label = String.format(Locale.US, "%.0f%%", scale * 100f);
        paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        paint.setTextSize(dp(11));
        float width = paint.measureText(label) + dp(18);
        RectF badge = new RectF(getWidth() - width - dp(16), dp(64), getWidth() - dp(16), dp(92));
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(213, 232, 255));
        canvas.drawRoundRect(badge, dp(14), dp(14), paint);
        paint.setColor(Color.rgb(7, 55, 99));
        canvas.drawText(label, badge.left + dp(9), badge.top + dp(19), paint);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
    }

    private int dp(float value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }
}
