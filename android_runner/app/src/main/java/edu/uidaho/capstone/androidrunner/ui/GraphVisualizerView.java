package edu.uidaho.capstone.androidrunner.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.util.AttributeSet;
import android.view.View;

import edu.uidaho.capstone.androidrunner.engine.GeneratedInputs;

import java.util.ArrayList;
import java.util.List;

public final class GraphVisualizerView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<int[]> edges = new ArrayList<>();
    private int nodeCount = 0;
    private String caption = "No graph loaded";

    public GraphVisualizerView(Context context) {
        super(context);
    }

    public GraphVisualizerView(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    public void setInputs(GeneratedInputs inputs) {
        edges.clear();
        if (inputs == null) {
            nodeCount = 0;
            caption = "No graph loaded";
        } else {
            nodeCount = inputs.targetNodeCount;
            edges.addAll(inputs.targetEdges);
            caption = "Target graph: " + inputs.targetNodeCount + " nodes, " + inputs.targetEdges.size() + " edges";
        }
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.WHITE);
        paint.setColor(Color.rgb(31, 41, 51));
        paint.setTextSize(28f);
        canvas.drawText(caption, 24, 36, paint);
        if (nodeCount <= 0) {
            paint.setColor(Color.rgb(95, 107, 118));
            paint.setTextSize(32f);
            canvas.drawText("Run a generated-input benchmark to render a graph.", 24, 100, paint);
            return;
        }
        int w = getWidth();
        int h = getHeight();
        float cx = w / 2f;
        float cy = (h + 40) / 2f;
        float r = Math.max(40f, Math.min(w, h) * 0.36f);
        float[] xs = new float[nodeCount];
        float[] ys = new float[nodeCount];
        for (int i = 0; i < nodeCount; i++) {
            double angle = (2.0 * Math.PI * i) / Math.max(1, nodeCount) - Math.PI / 2.0;
            xs[i] = cx + (float) Math.cos(angle) * r;
            ys[i] = cy + (float) Math.sin(angle) * r;
        }
        paint.setStrokeWidth(2f);
        paint.setColor(Color.rgb(180, 188, 197));
        for (int[] edge : edges) {
            if (edge.length < 2) continue;
            int u = edge[0];
            int v = edge[1];
            if (u >= 0 && u < nodeCount && v >= 0 && v < nodeCount) {
                canvas.drawLine(xs[u], ys[u], xs[v], ys[v], paint);
            }
        }
        for (int i = 0; i < nodeCount; i++) {
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(11, 92, 173));
            canvas.drawCircle(xs[i], ys[i], 11f, paint);
            if (nodeCount <= 80) {
                paint.setColor(Color.WHITE);
                paint.setTextSize(16f);
                canvas.drawText(Integer.toString(i), xs[i] - 5f, ys[i] + 6f, paint);
            }
        }
        paint.setStyle(Paint.Style.STROKE);
    }
}
