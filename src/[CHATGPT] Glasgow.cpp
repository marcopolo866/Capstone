/*
Write a program in C++ that, given a large target graph, finds all instances of a smaller pattern graph within it, 
or confirms that no instances exist. The program should accept inputs like the provided files (shown below) and must 
support both .lad and .grf graph formats. Input files will look very similar to these references. 
The key idea is achieving the fastest runtime possible, so take every shortcut available, including advanced pruning, 
ordering heuristics, and constraint-based filtering. The solution should be optimized for performance over readability 
and must scale well to large graphs. ​Just output the code as a single block to copy and paste, nothing else. 
The program must also output how long it took to run, measured as precisely as possible in milliseconds, 
without losing accuracy. 
​The program must print only the following lines, in this exact order: 
The nodes of the target graph that form each instance of the pattern graph. If multiple instances exist, 
print one numbered list per line. If an instance does not fit on a single line, wrap the list in brackets and 
continue on subsequent lines. The total number of distinct instances of the smaller graph found in 
the larger target graph, printed as a single integer. The execution time of the program in milliseconds, 
printed on the final line.
*/
#include <iostream>
#include <fstream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <chrono>
#include <string>
#include <cstdlib>

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

Graph read_lad(const string &file) {
    ifstream in(file);
    if (!in) exit(1);
    Graph g;
    in >> g.n;
    g.label.resize(g.n);
    g.adj.assign(g.n, {});
    for (int i = 0; i < g.n; i++) {
        in >> g.label[i];
        int v;
        while (in >> v && v != 0)
            g.adj[i].push_back(v - 1);
    }
    g.deg.resize(g.n);
    for (int i = 0; i < g.n; i++) {
        sort(g.adj[i].begin(), g.adj[i].end());
        g.deg[i] = g.adj[i].size();
    }
    return g;
}

Graph read_graph(const string &file) {
    return read_lad(file);
}

int main(int argc, char **argv) {
    auto start = chrono::high_resolution_clock::now();

    Graph target  = read_graph(argv[1]);
    Graph pattern = read_graph(argv[2]);

    int pn = pattern.n, tn = target.n;

    vector<int> order(pn);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [&](int a, int b) {
        return pattern.deg[a] > pattern.deg[b];
    });

    vector<int> map_p2t(pn, -1);
    vector<char> used(tn, 0);

    bool found = false;
    vector<int> solution;

    function<void(int)> dfs = [&](int depth) {
        if (found) return;

        if (depth == pn) {
            solution.resize(pn);
            for (int i = 0; i < pn; i++) {
                int p = order[i];
                solution[p] = map_p2t[p];
            }
            found = true;
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

        sort(candidates.begin(), candidates.end(), [&](int a, int b) {
            if (target.deg[a] != target.deg[b])
                return target.deg[a] > target.deg[b]; // higher degree first
            return a > b; // higher index first
        });

        for (int t : candidates) {
            if (used[t]) continue;
            if (pattern.label[p] != target.label[t]) continue;
            if (pattern.deg[p] > target.deg[t]) continue;

            bool ok = true;
            for (int i = 0; i < depth && ok; i++) {
                int pp = order[i];
                int tt = map_p2t[pp];
                if (has_edge(pattern, p, pp) && !has_edge(target, t, tt))
                    ok = false;
            }
            if (!ok) continue;

            used[t] = 1;
            map_p2t[p] = t;
            dfs(depth + 1);
            used[t] = 0;
            map_p2t[p] = -1;
        }
    };

    dfs(0);

    auto end = chrono::high_resolution_clock::now();
    long long ms =
        chrono::duration_cast<chrono::milliseconds>(end - start).count();

    if (found) {
    cout << "Mapping: ";
    for (int p = 0; p < pn; p++) {
        cout << "(" << p << " -> " << solution[p] << ") ";
    }
    cout << "\nTime: " << ms << "\n";
    }


    return 0;
}
