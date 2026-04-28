package edu.uidaho.capstone.androidrunner.engine;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class Stats {
    private Stats() {
    }

    public static Double median(List<Double> values) {
        List<Double> clean = clean(values);
        if (clean.isEmpty()) return null;
        Collections.sort(clean);
        int mid = clean.size() / 2;
        if (clean.size() % 2 == 1) return clean.get(mid);
        return (clean.get(mid - 1) + clean.get(mid)) / 2.0;
    }

    public static double stdev(List<Double> values) {
        List<Double> clean = clean(values);
        if (clean.size() < 2) return 0.0;
        double mean = 0.0;
        for (double value : clean) mean += value;
        mean /= clean.size();
        double sum = 0.0;
        for (double value : clean) {
            double delta = value - mean;
            sum += delta * delta;
        }
        return Math.sqrt(sum / (clean.size() - 1));
    }

    private static List<Double> clean(List<Double> values) {
        List<Double> out = new ArrayList<>();
        for (Double value : values) {
            if (value != null && Double.isFinite(value)) out.add(value);
        }
        return out;
    }
}
