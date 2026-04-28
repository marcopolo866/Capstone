package edu.uidaho.capstone.androidrunner.engine;

import android.os.Debug;
import android.os.SystemClock;

import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.BenchmarkTrial;
import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.SolverVariant;

import org.json.JSONObject;

public final class NativeSolverBridge {
    public BenchmarkTrial run(
            SolverVariant variant,
            GeneratedInputs inputs,
            int pointIndex,
            int iterationIndex,
            long seed
    ) {
        BenchmarkTrial trial = new BenchmarkTrial();
        trial.pointIndex = pointIndex;
        trial.iterationIndex = iterationIndex;
        trial.seed = seed;
        trial.variantId = variant.variantId;
        trial.family = variant.family;
        long beforeNative = Debug.getNativeHeapAllocatedSize();
        long beforeJava = Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory();
        long start = SystemClock.elapsedRealtimeNanos();
        try {
            String inputA = "";
            String inputB = "";
            String ladFormat = inputs.ladFormat;
            if ("dijkstra".equals(variant.family) || "sp_via".equals(variant.family)) {
                inputA = inputs.dijkstraFile.getAbsolutePath();
            } else if ("glasgow".equals(variant.family)) {
                inputA = inputs.ladPattern.getAbsolutePath();
                inputB = inputs.ladTarget.getAbsolutePath();
            } else {
                inputA = inputs.vfPattern.getAbsolutePath();
                inputB = inputs.vfTarget.getAbsolutePath();
            }
            String json = CapstoneNative.runSolver(variant.variantId, variant.family, inputA, inputB, ladFormat);
            long end = SystemClock.elapsedRealtimeNanos();
            JSONObject payload = new JSONObject(json);
            trial.status = payload.optString("status", "failed");
            trial.stdout = payload.optString("stdout", "");
            trial.stderr = payload.optString("stderr", "");
            trial.returnCode = payload.optInt("returnCode", "ok".equals(trial.status) ? 0 : 1);
            trial.answerKind = payload.optString("answerKind", "");
            trial.answerValue = payload.optString("answerValue", "");
            trial.solutionCount = payload.optLong("solutionCount", -1);
            trial.distance = payload.optString("distance", "");
            trial.pathLength = payload.optInt("pathLength", -1);
            trial.runtimeMs = (end - start) / 1_000_000.0;
        } catch (Exception exc) {
            long end = SystemClock.elapsedRealtimeNanos();
            trial.status = "failed";
            trial.stderr = exc.getMessage() == null ? exc.toString() : exc.getMessage();
            trial.returnCode = 1;
            trial.runtimeMs = (end - start) / 1_000_000.0;
        }
        long afterNative = Debug.getNativeHeapAllocatedSize();
        long afterJava = Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory();
        long peakBytes = Math.max(Math.max(beforeNative, afterNative), Math.max(beforeJava, afterJava));
        trial.peakKb = Math.max(0.0, peakBytes / 1024.0);
        return trial;
    }
}
