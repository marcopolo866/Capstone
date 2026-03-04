/*
Write a program in C++ that, given a large target graph, finds all instances of a smaller pattern graph within it,
or confirms that no instances exist. The program should accept inputs like the provided files (shown below) and must
support both .lad and .grf graph formats. Input files will look very similar to these references.
The key idea is achieving the fastest runtime possible, so take every shortcut available, including advanced pruning,
ordering heuristics, and constraint-based filtering. The solution should be optimized for performance over readability
and must scale well to large graphs. Just output the code as a single block to copy and paste, nothing else.
The program must also output how long it took to run, measured as precisely as possible in milliseconds,
without losing accuracy.
The program must print only the following lines, in this exact order:
The nodes of the target graph that form each instance of the pattern graph. If multiple instances exist,
print one numbered list per line. If an instance does not fit on a single line, wrap the list in brackets and
continue on subsequent lines. The total number of distinct instances of the smaller graph found in
the larger target graph, printed as a single integer. The execution time of the program in milliseconds,
printed on the final line.
*/
#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <chrono>
#include <string>
#include <cstdlib>
#include <cstdio>

using namespace std;

struct Graph {
    int n;
    vector<int> label;
    vector<vector<int>> adj;
    vector<int> deg;
};

static inline bool has_edge(const Graph &g, int u, int v) {
    const auto &a = g.adj[u];
    return binary_search(a.begin(), a.end(), v);
}

// Parse ints from a text line, store into vals. Returns number parsed.
static int parse_ints(const char *line, vector<int> &vals) {
    vals.clear();
    const char *p = line;
    while (*p) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (!*p) break;
        bool neg = (*p == '-');
        if (neg) p++;
        if (*p < '0' || *p > '9') break;
        int v = 0;
        while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        vals.push_back(neg ? -v : v);
    }
    return (int)vals.size();
}

Graph read_lad(const string &file) {
    FILE *f = fopen(file.c_str(), "r");
    if (!f) exit(1);
    Graph g;
    if (fscanf(f, "%d", &g.n) != 1) { fclose(f); exit(1); }
    g.label.resize(g.n);
    g.adj.assign(g.n, {});

    char line[65536];
    fgets(line, sizeof(line), f); // consume rest of first line

    // Pass 1: read all vertex lines, detect format.
    // Standard LAD: every line satisfies vals[0] == vals.size()-1.
    // Vertex-labelled LAD (write_lad output): vals[0]=label, vals[1]=count; any line
    // where label != degree+1 will fail the standard check.
    vector<vector<int>> all_vals(g.n);
    bool vertex_labelled = false;
    vector<int> tmp;
    for (int i = 0; i < g.n; i++) {
        if (!fgets(line, sizeof(line), f)) break;
        parse_ints(line, tmp);
        all_vals[i] = tmp;
        if (!tmp.empty() && tmp[0] != (int)tmp.size() - 1)
            vertex_labelled = true;
    }
    fclose(f);

    // Pass 2: parse adjacency using detected format.
    for (int i = 0; i < g.n; i++) {
        auto& vals = all_vals[i];
        if (vals.empty()) { g.label[i] = 0; continue; }
        if (vertex_labelled) {
            // Vertex-labelled: vals[0]=label, vals[1]=count, vals[2..]=neighbors
            g.label[i] = vals[0];
            int count = (vals.size() >= 2) ? vals[1] : 0;
            for (int j = 2; j <= count + 1 && j < (int)vals.size(); j++) {
                int v = vals[j];
                if (v >= 0 && v < g.n && v != i) g.adj[i].push_back(v);
            }
        } else {
            // Standard: vals[0]=count, vals[1..]=neighbors
            g.label[i] = 0;
            int count = vals[0];
            for (int j = 1; j <= count && j < (int)vals.size(); j++) {
                int v = vals[j];
                if (v >= 0 && v < g.n && v != i) g.adj[i].push_back(v);
            }
        }
    }

    // Make graph undirected: add reverse edges, then sort+dedup
    for (int i = 0; i < g.n; i++) {
        for (int v : g.adj[i]) g.adj[v].push_back(i);
    }
    g.deg.resize(g.n);
    for (int i = 0; i < g.n; i++) {
        sort(g.adj[i].begin(), g.adj[i].end());
        g.adj[i].erase(unique(g.adj[i].begin(), g.adj[i].end()), g.adj[i].end());
        g.deg[i] = (int)g.adj[i].size();
    }
    return g;
}

void dfs(int depth, int pn, int tn,
         const Graph &pattern, const Graph &target,
         const vector<int> &order,
         vector<int> &map_p2t, vector<char> &used,
         long long &total_instances, vector<int> &solution) {
    if (depth == pn) {
        for (int i = 0; i < pn; i++) {
            solution[order[i]] = map_p2t[order[i]];
        }
        total_instances++;
        cout << "Mapping: ";
        for (int p = 0; p < pn; p++) {
            cout << "(" << p << " -> " << solution[p] << ")";
            if (p + 1 < pn) cout << " ";
        }
        cout << "\n";
        return;
    }

    int p = order[depth];

    vector<int> candidates;
    for (int t = 0; t < tn; t++) {
        if (!used[t] &&
            pattern.label[p] == target.label[t] &&
            pattern.deg[p] <= target.deg[t]) {
            candidates.push_back(t);
        }
    }

    sort(candidates.begin(), candidates.end(), [&target](int a, int b) {
        if (target.deg[a] != target.deg[b])
            return target.deg[a] > target.deg[b];
        return a > b;
    });

    for (int t : candidates) {
        bool ok = true;
        for (int i = 0; i < depth && ok; i++) {
            int pp = order[i];
            int tt = map_p2t[pp];
            if (has_edge(pattern, p, pp) && !has_edge(target, t, tt))
                ok = false;
            if (has_edge(pattern, pp, p) && !has_edge(target, tt, t))
                ok = false;
        }
        if (!ok) continue;

        used[t] = 1;
        map_p2t[p] = t;
        dfs(depth + 1, pn, tn, pattern, target, order,
            map_p2t, used, total_instances, solution);
        used[t] = 0;
        map_p2t[p] = -1;
    }
}

int main(int argc, char **argv) {
    if (argc < 3) return 1;
    auto start = chrono::high_resolution_clock::now();

    // Match the workflow and the other solvers: pattern first, target second.
    Graph pattern = read_lad(argv[1]);
    Graph target  = read_lad(argv[2]);

    int pn = pattern.n, tn = target.n;

    vector<int> order(pn);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [&](int a, int b) {
        return pattern.deg[a] > pattern.deg[b];
    });

    vector<int> map_p2t(pn, -1);
    vector<char> used(tn, 0);

    long long total_instances = 0;
    vector<int> solution(pn, -1);

    dfs(0, pn, tn, pattern, target, order, map_p2t, used, total_instances, solution);

    auto end = chrono::high_resolution_clock::now();
    long long ms =
        chrono::duration_cast<chrono::milliseconds>(end - start).count();

    cout << total_instances << "\n";
    cout << "Time: " << ms << "\n";

    return 0;
}
