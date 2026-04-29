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
    private final List<int[]> edges = new ArrayList<>();
    private final List<Integer> solutionNodes = new ArrayList<>();
    private final RectF canvasBounds = new RectF();
    private ScaleGestureDetector scaleDetector;
    private int nodeCount = 0;
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
        edges.clear();
        solutionNodes.clear();
        if (inputs == null) {
            nodeCount = 0;
            caption = "No graph loaded";
            setContentDescription("Graph visualizer. No graph loaded.");
        } else {
            nodeCount = inputs.targetNodeCount;
            edges.addAll(inputs.targetEdges);
            solutionNodes.addAll(inputs.solutionNodes);
            caption = "Seed " + inputs.seed + ": " + inputs.targetNodeCount + " nodes, " + inputs.targetEdges.size() + " edges";
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
        if (nodeCount <= 0) return true;
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
        canvasBounds.set(dp(8), dp(54), getWidth() - dp(8), getHeight() - dp(8));
        drawPanel(canvas);

        if (nodeCount <= 0) {
            drawEmptyState(canvas);
            return;
        }

        float cx = canvasBounds.centerX();
        float cy = canvasBounds.centerY() + dp(8);
        float radius = Math.max(dp(42), Math.min(canvasBounds.width(), canvasBounds.height()) * 0.38f);
        float[] xs = new float[nodeCount];
        float[] ys = new float[nodeCount];
        for (int i = 0; i < nodeCount; i++) {
            double angle = (2.0 * Math.PI * i) / Math.max(1, nodeCount) - Math.PI / 2.0;
            xs[i] = cx + (float) Math.cos(angle) * radius;
            ys[i] = cy + (float) Math.sin(angle) * radius;
        }

        canvas.save();
        canvas.translate(offsetX, offsetY);
        canvas.scale(scale, scale, cx, cy);
        boolean[] highlighted = highlightedNodes();
        drawEdges(canvas, xs, ys, highlighted);
        drawNodes(canvas, xs, ys, highlighted);
        canvas.restore();

        drawScaleBadge(canvas);
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
        String meta = nodeCount <= 0 ? "Generated target graphs appear after a run starts."
                : String.format(Locale.US, "Scale %.0f%% | labels %s | solution nodes %d", scale * 100f, showLabels ? "on" : "off", solutionNodes.size());
        canvas.drawText(meta, dp(12), dp(42), paint);
    }

    private void drawPanel(Canvas canvas) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.WHITE);
        canvas.drawRoundRect(canvasBounds, dp(8), dp(8), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(1));
        paint.setColor(Color.rgb(188, 199, 211));
        canvas.drawRoundRect(canvasBounds, dp(8), dp(8), paint);
    }

    private void drawEmptyState(Canvas canvas) {
        paint.setStyle(Paint.Style.FILL);
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(dp(14));
        paint.setColor(Color.rgb(93, 104, 117));
        canvas.drawText("No generated graph available.", canvasBounds.left + dp(18), canvasBounds.top + dp(42), paint);
    }

    private void drawEdges(Canvas canvas, float[] xs, float[] ys, boolean[] highlighted) {
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(nodeCount > 120 ? dp(1) : dp(1.5f));
        int edgeLimit = Math.min(edges.size(), 4000);
        for (int i = 0; i < edgeLimit; i++) {
            int[] edge = edges.get(i);
            if (edge.length < 2) continue;
            int u = edge[0];
            int v = edge[1];
            if (u >= 0 && u < nodeCount && v >= 0 && v < nodeCount) {
                boolean solutionEdge = highlighted[u] && highlighted[v];
                paint.setStrokeWidth(solutionEdge ? dp(3) : (nodeCount > 120 ? dp(1) : dp(1.5f)));
                paint.setColor(solutionEdge ? Color.rgb(57, 106, 69) : Color.rgb(178, 188, 199));
                canvas.drawLine(xs[u], ys[u], xs[v], ys[v], paint);
            }
        }
        if (edges.size() > edgeLimit) {
            paint.setStyle(Paint.Style.FILL);
            paint.setTextSize(dp(10));
            paint.setColor(Color.rgb(93, 104, 117));
            canvas.drawText("+" + (edges.size() - edgeLimit) + " edges hidden", canvasBounds.left + dp(12), canvasBounds.bottom - dp(12), paint);
        }
    }

    private void drawNodes(Canvas canvas, float[] xs, float[] ys, boolean[] highlighted) {
        float nodeRadius = nodeCount > 160 ? dp(4) : (nodeCount > 80 ? dp(6) : dp(9));
        for (int i = 0; i < nodeCount; i++) {
            boolean solutionNode = highlighted[i];
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(solutionNode ? Color.rgb(57, 106, 69) : Color.rgb(11, 87, 163));
            canvas.drawCircle(xs[i], ys[i], solutionNode ? nodeRadius + dp(3) : nodeRadius, paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(solutionNode ? dp(2) : dp(1));
            paint.setColor(solutionNode ? Color.rgb(0, 0, 0) : Color.WHITE);
            canvas.drawCircle(xs[i], ys[i], solutionNode ? nodeRadius + dp(3) : nodeRadius, paint);
            if (showLabels && nodeCount <= 120) {
                paint.setStyle(Paint.Style.FILL);
                paint.setColor(Color.rgb(24, 33, 43));
                paint.setTextSize(nodeCount > 80 ? dp(7) : dp(9));
                paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
                String label = Integer.toString(i);
                canvas.drawText(label, xs[i] + nodeRadius + dp(2), ys[i] + dp(3), paint);
            }
        }
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
    }

    private boolean[] highlightedNodes() {
        boolean[] highlighted = new boolean[Math.max(0, nodeCount)];
        for (Integer node : solutionNodes) {
            if (node != null && node >= 0 && node < highlighted.length) highlighted[node] = true;
        }
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
