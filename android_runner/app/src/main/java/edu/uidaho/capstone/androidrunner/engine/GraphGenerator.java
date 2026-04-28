package edu.uidaho.capstone.androidrunner.engine;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Queue;
import java.util.Random;

public final class GraphGenerator {
    private GraphGenerator() {
    }

    public static GeneratedInputs generateShortest(File outDir, String family, int n, double density, long seed, String graphFamily) throws IOException {
        ensureDir(outDir);
        Random rng = new Random(seed);
        GeneratedInputs result = new GeneratedInputs();
        result.targetNodeCount = n;
        File csv = new File(outDir, "dijkstra_generated.csv");
        String via = "";
        if ("sp_via".equals(family)) {
            via = "v" + Math.max(1, Math.min(n - 2, n / 2));
        }
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(csv))) {
            writer.write("# start=v0 target=v" + (n - 1));
            if (!via.isEmpty()) writer.write(" via=" + via);
            writer.write("\n");
            writer.write("source,target,weight\n");
            List<int[]> edges = generateDirectedEdges(n, density, rng, graphFamily);
            for (int[] edge : edges) {
                writer.write("v" + edge[0] + ",v" + edge[1] + "," + edge[2] + "\n");
            }
        }
        result.dijkstraFile = csv;
        return result;
    }

    public static GeneratedInputs generateSubgraph(File outDir, int n, int k, double density, long seed, String graphFamily) throws IOException {
        ensureDir(outDir);
        Random rng = new Random(seed);
        boolean[][] target = generateUndirectedAdjacency(n, density, rng, graphFamily);
        int[] selected = pickConnectedNodes(target, Math.max(2, Math.min(k, n - 1)), rng);
        boolean[][] pattern = inducedSubgraph(target, selected);
        int[] targetLabels = labels(n);
        int[] patternLabels = new int[selected.length];
        for (int i = 0; i < selected.length; i++) {
            patternLabels[i] = targetLabels[selected[i]];
        }

        GeneratedInputs result = new GeneratedInputs();
        result.targetNodeCount = n;
        result.patternNodeCount = selected.length;
        result.vfPattern = new File(outDir, "pattern.vf");
        result.vfTarget = new File(outDir, "target.vf");
        result.ladPattern = new File(outDir, "pattern.lad");
        result.ladTarget = new File(outDir, "target.lad");
        writeVf(result.vfPattern, pattern, patternLabels);
        writeVf(result.vfTarget, target, targetLabels);
        writeLabelledLad(result.ladPattern, pattern, patternLabels);
        writeLabelledLad(result.ladTarget, target, targetLabels);
        result.patternEdges.addAll(edgeList(pattern));
        result.targetEdges.addAll(edgeList(target));
        return result;
    }

    private static List<int[]> generateDirectedEdges(int n, double density, Random rng, String graphFamily) {
        List<int[]> edges = new ArrayList<>();
        if ("grid".equals(graphFamily)) {
            int cols = Math.max(1, (int) Math.ceil(Math.sqrt(n)));
            for (int u = 0; u < n; u++) {
                int r = u / cols;
                int c = u % cols;
                int right = r * cols + c + 1;
                int down = (r + 1) * cols + c;
                if (c + 1 < cols && right < n) addDirectedPair(edges, u, right, rng);
                if (down < n) addDirectedPair(edges, u, down, rng);
            }
            return edges;
        }
        for (int u = 0; u < n; u++) {
            for (int v = 0; v < n; v++) {
                if (u == v) continue;
                if (rng.nextDouble() <= density) {
                    edges.add(new int[]{u, v, 1 + rng.nextInt(20)});
                }
            }
        }
        if (edges.isEmpty() && n >= 2) {
            edges.add(new int[]{0, n - 1, 1 + rng.nextInt(20)});
        }
        return edges;
    }

    private static void addDirectedPair(List<int[]> edges, int u, int v, Random rng) {
        int w = 1 + rng.nextInt(20);
        edges.add(new int[]{u, v, w});
        edges.add(new int[]{v, u, w});
    }

    private static boolean[][] generateUndirectedAdjacency(int n, double density, Random rng, String graphFamily) {
        boolean[][] adj = new boolean[n][n];
        if ("grid".equals(graphFamily)) {
            int cols = Math.max(1, (int) Math.ceil(Math.sqrt(n)));
            for (int u = 0; u < n; u++) {
                int r = u / cols;
                int c = u % cols;
                int right = r * cols + c + 1;
                int down = (r + 1) * cols + c;
                if (c + 1 < cols && right < n) addUndirected(adj, u, right);
                if (down < n) addUndirected(adj, u, down);
            }
            return adj;
        }
        if ("barabasi_albert".equals(graphFamily)) {
            for (int i = 1; i < n; i++) {
                int parent = rng.nextInt(i);
                addUndirected(adj, i, parent);
            }
        }
        for (int u = 0; u < n; u++) {
            for (int v = u + 1; v < n; v++) {
                if (rng.nextDouble() <= density) addUndirected(adj, u, v);
            }
        }
        if (!isConnectedEnough(adj)) {
            for (int i = 1; i < n; i++) addUndirected(adj, i - 1, i);
        }
        return adj;
    }

    private static void addUndirected(boolean[][] adj, int u, int v) {
        if (u == v) return;
        adj[u][v] = true;
        adj[v][u] = true;
    }

    private static boolean isConnectedEnough(boolean[][] adj) {
        return connectedComponent(adj, 0).size() >= Math.max(2, Math.min(adj.length, adj.length / 2));
    }

    private static List<Integer> connectedComponent(boolean[][] adj, int start) {
        List<Integer> result = new ArrayList<>();
        boolean[] seen = new boolean[adj.length];
        Queue<Integer> queue = new ArrayDeque<>();
        queue.add(start);
        seen[start] = true;
        while (!queue.isEmpty()) {
            int u = queue.remove();
            result.add(u);
            for (int v = 0; v < adj.length; v++) {
                if (adj[u][v] && !seen[v]) {
                    seen[v] = true;
                    queue.add(v);
                }
            }
        }
        return result;
    }

    private static int[] pickConnectedNodes(boolean[][] adj, int k, Random rng) {
        List<Integer> component = new ArrayList<>();
        for (int start = 0; start < adj.length; start++) {
            List<Integer> candidate = connectedComponent(adj, start);
            if (candidate.size() >= k && candidate.size() > component.size()) {
                component = candidate;
            }
        }
        if (component.size() < k) {
            int[] fallback = new int[k];
            for (int i = 0; i < k; i++) fallback[i] = i;
            return fallback;
        }
        Collections.shuffle(component, rng);
        int[] selected = new int[k];
        for (int i = 0; i < k; i++) selected[i] = component.get(i);
        return selected;
    }

    private static boolean[][] inducedSubgraph(boolean[][] adj, int[] selected) {
        boolean[][] sub = new boolean[selected.length][selected.length];
        for (int i = 0; i < selected.length; i++) {
            for (int j = i + 1; j < selected.length; j++) {
                if (adj[selected[i]][selected[j]]) addUndirected(sub, i, j);
            }
        }
        return sub;
    }

    private static int[] labels(int n) {
        int[] labels = new int[n];
        for (int i = 0; i < n; i++) labels[i] = 1 + (i % 5);
        return labels;
    }

    private static void writeVf(File file, boolean[][] adj, int[] labels) throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(file))) {
            writer.write(Integer.toString(adj.length));
            writer.write("\n");
            for (int i = 0; i < adj.length; i++) {
                writer.write(i + " " + labels[i] + "\n");
            }
            for (int i = 0; i < adj.length; i++) {
                List<Integer> neighbors = neighbors(adj, i);
                writer.write(Integer.toString(neighbors.size()));
                writer.write("\n");
                for (Integer v : neighbors) writer.write(i + " " + v + "\n");
            }
        }
    }

    private static void writeLabelledLad(File file, boolean[][] adj, int[] labels) throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(file))) {
            writer.write(Integer.toString(adj.length));
            writer.write("\n");
            for (int i = 0; i < adj.length; i++) {
                List<Integer> neighbors = neighbors(adj, i);
                writer.write(labels[i] + " " + neighbors.size());
                for (Integer v : neighbors) writer.write(" " + v);
                writer.write("\n");
            }
        }
    }

    private static List<Integer> neighbors(boolean[][] adj, int u) {
        List<Integer> neighbors = new ArrayList<>();
        for (int v = 0; v < adj.length; v++) if (adj[u][v]) neighbors.add(v);
        return neighbors;
    }

    private static List<int[]> edgeList(boolean[][] adj) {
        List<int[]> edges = new ArrayList<>();
        for (int u = 0; u < adj.length; u++) {
            for (int v = u + 1; v < adj.length; v++) {
                if (adj[u][v]) edges.add(new int[]{u, v});
            }
        }
        return edges;
    }

    private static void ensureDir(File dir) throws IOException {
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException(String.format(Locale.US, "Unable to create directory: %s", dir));
        }
    }
}
