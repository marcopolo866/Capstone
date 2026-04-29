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
import java.util.PriorityQueue;
import java.util.Queue;
import java.util.Random;

public final class GraphGenerator {
    private GraphGenerator() {
    }

    public static GeneratedInputs generateShortest(File outDir, String family, int n, double density, long seed, String graphFamily) throws IOException {
        ensureDir(outDir);
        Random rng = new Random(seed);
        GeneratedInputs result = new GeneratedInputs();
        result.seed = seed;
        result.targetNodeCount = n;
        result.shortestFamily = family;
        File csv = new File(outDir, "dijkstra_generated.csv");
        int start = n <= 1 ? 0 : rng.nextInt(n);
        int target = pickDifferentNode(n, rng, start, -1);
        int viaNode = "sp_via".equals(family) && n >= 3 ? pickDifferentNode(n, rng, start, target) : -1;
        result.shortestStartNode = start;
        result.shortestTargetNode = target;
        result.shortestViaNode = viaNode;
        List<int[]> edges = generateDirectedEdges(n, density, rng, graphFamily);
        if (viaNode >= 0) {
            ensureReachablePath(edges, n, start, viaNode, rng);
            ensureReachablePath(edges, n, viaNode, target, rng);
        } else {
            ensureReachablePath(edges, n, start, target, rng);
        }
        populateShortestPath(result, edges);
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(csv))) {
            writer.write("# start=v" + start + " target=v" + target);
            if (viaNode >= 0) writer.write(" via=v" + viaNode);
            writer.write("\n");
            writer.write("source,target,weight\n");
            for (int[] edge : edges) {
                result.targetEdges.add(new int[]{edge[0], edge[1]});
                writer.write("v" + edge[0] + ",v" + edge[1] + "," + edge[2] + "\n");
            }
        }
        result.dijkstraFile = csv;
        return result;
    }

    private static int pickDifferentNode(int n, Random rng, int first, int second) {
        if (n <= 1) return 0;
        int node = rng.nextInt(n);
        while (node == first || node == second) node = rng.nextInt(n);
        return node;
    }

    private static void ensureReachablePath(List<int[]> edges, int n, int start, int target, Random rng) {
        if (n <= 1 || start == target) return;
        List<Integer> path = new ArrayList<>();
        path.add(start);
        int extraCount = n <= 3 ? 0 : rng.nextInt(Math.min(3, n - 2) + 1);
        List<Integer> candidates = new ArrayList<>();
        for (int node = 0; node < n; node++) {
            if (node != start && node != target) candidates.add(node);
        }
        Collections.shuffle(candidates, rng);
        for (int i = 0; i < extraCount && i < candidates.size(); i++) path.add(candidates.get(i));
        path.add(target);
        for (int i = 0; i + 1 < path.size(); i++) {
            edges.add(new int[]{path.get(i), path.get(i + 1), 1 + rng.nextInt(9)});
        }
    }

    private static void populateShortestPath(GeneratedInputs result, List<int[]> edges) {
        if (result.targetNodeCount <= 0 || result.shortestStartNode < 0 || result.shortestTargetNode < 0) return;
        PathResult path;
        if (result.shortestViaNode >= 0) {
            PathResult first = shortestPath(result.targetNodeCount, edges, result.shortestStartNode, result.shortestViaNode);
            PathResult second = shortestPath(result.targetNodeCount, edges, result.shortestViaNode, result.shortestTargetNode);
            if (!first.reachable || !second.reachable) {
                path = PathResult.unreachable();
            } else {
                path = new PathResult();
                path.reachable = true;
                path.weight = first.weight + second.weight;
                path.nodes.addAll(first.nodes);
                if (!second.nodes.isEmpty()) path.nodes.addAll(second.nodes.subList(1, second.nodes.size()));
            }
        } else {
            path = shortestPath(result.targetNodeCount, edges, result.shortestStartNode, result.shortestTargetNode);
        }
        result.shortestPathReachable = path.reachable;
        result.shortestPathWeight = path.reachable ? path.weight : -1L;
        result.shortestPathNodes.addAll(path.nodes);
        for (int i = 0; i + 1 < path.nodes.size(); i++) {
            result.shortestPathEdges.add(new int[]{path.nodes.get(i), path.nodes.get(i + 1)});
        }
    }

    private static PathResult shortestPath(int n, List<int[]> edges, int start, int target) {
        List<List<int[]>> adj = new ArrayList<>();
        for (int i = 0; i < n; i++) adj.add(new ArrayList<>());
        for (int[] edge : edges) {
            if (edge.length < 3) continue;
            int u = edge[0];
            int v = edge[1];
            int w = edge[2];
            if (u >= 0 && u < n && v >= 0 && v < n && w >= 0) adj.get(u).add(new int[]{v, w});
        }
        long inf = Long.MAX_VALUE / 4L;
        long[] dist = new long[n];
        int[] parent = new int[n];
        for (int i = 0; i < n; i++) {
            dist[i] = inf;
            parent[i] = -1;
        }
        PriorityQueue<long[]> queue = new PriorityQueue<>((a, b) -> Long.compare(a[0], b[0]));
        dist[start] = 0L;
        queue.add(new long[]{0L, start});
        while (!queue.isEmpty()) {
            long[] item = queue.remove();
            long d = item[0];
            int u = (int) item[1];
            if (d != dist[u]) continue;
            if (u == target) break;
            for (int[] edge : adj.get(u)) {
                int v = edge[0];
                long next = d + edge[1];
                if (next < dist[v]) {
                    dist[v] = next;
                    parent[v] = u;
                    queue.add(new long[]{next, v});
                }
            }
        }
        if (dist[target] >= inf) return PathResult.unreachable();
        PathResult result = new PathResult();
        result.reachable = true;
        result.weight = dist[target];
        List<Integer> reversed = new ArrayList<>();
        for (int node = target; node >= 0; node = parent[node]) {
            reversed.add(node);
            if (node == start) break;
        }
        Collections.reverse(reversed);
        result.nodes.addAll(reversed);
        return result;
    }

    private static final class PathResult {
        final List<Integer> nodes = new ArrayList<>();
        boolean reachable;
        long weight;

        static PathResult unreachable() {
            return new PathResult();
        }
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
        result.seed = seed;
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
        for (int node : selected) result.solutionNodes.add(node);
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
        boolean[] inComponent = new boolean[adj.length];
        for (Integer node : component) inComponent[node] = true;
        boolean[] selectedFlags = new boolean[adj.length];
        List<Integer> result = new ArrayList<>();
        List<Integer> frontier = new ArrayList<>();
        int start = component.get(rng.nextInt(component.size()));
        selectedFlags[start] = true;
        result.add(start);
        addFrontierNeighbors(adj, inComponent, selectedFlags, frontier, start);
        while (result.size() < k && !frontier.isEmpty()) {
            int pickIndex = rng.nextInt(frontier.size());
            int node = frontier.remove(pickIndex);
            if (selectedFlags[node]) continue;
            selectedFlags[node] = true;
            result.add(node);
            addFrontierNeighbors(adj, inComponent, selectedFlags, frontier, node);
        }
        if (result.size() < k) {
            Collections.shuffle(component, rng);
            for (Integer node : component) {
                if (result.size() >= k) break;
                if (!selectedFlags[node]) result.add(node);
            }
        }
        int[] selectedNodes = new int[k];
        for (int i = 0; i < k; i++) selectedNodes[i] = result.get(i);
        return selectedNodes;
    }

    private static void addFrontierNeighbors(boolean[][] adj, boolean[] inComponent, boolean[] selected, List<Integer> frontier, int node) {
        for (int v = 0; v < adj.length; v++) {
            if (adj[node][v] && inComponent[v] && !selected[v] && !frontier.contains(v)) {
                frontier.add(v);
            }
        }
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
