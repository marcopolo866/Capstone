#include <iostream>
#include <vector>
#include <fstream>
#include <algorithm>
#include <map>

using namespace std;

struct Graph {
    int n;
    vector<int> labels;
    vector<vector<int>> adj;
    vector<vector<int>> rev_adj;
    vector<vector<bool>> matrix; // For O(1) induced check

    Graph(int n) : n(n), labels(n), adj(n), rev_adj(n), matrix(n, vector<bool>(n, false)) {}

    void add_edge(int u, int v) {
        adj[u].push_back(v);
        rev_adj[v].push_back(u);
        matrix[u][v] = true;
    }
};

Graph read_graph(const string& filename) {
    ifstream ifs(filename);
    if (!ifs) exit(1);
    int n;
    ifs >> n;
    Graph g(n);
    for (int i = 0; i < n; ++i) {
        int id, label;
        ifs >> id >> label;
        g.labels[id] = label;
    }
    for (int i = 0; i < n; ++i) {
        int k;
        ifs >> k;
        while (k--) {
            int u, v;
            ifs >> u >> v;
            g.add_edge(u, v);
        }
    }
    return g;
}

struct Solver {
    const Graph& H;
    const Graph& G;
    long long count = 0;

    vector<int> h_to_g;
    vector<bool> g_used;
    vector<int> order;
    vector<vector<int>> candidates;

    Solver(const Graph& h, const Graph& g) : H(h), G(g), h_to_g(h.n, -1), g_used(g.n, false) {}

    void preprocess() {
        candidates.resize(H.n);
        for (int i = 0; i < H.n; ++i) {
            for (int j = 0; j < G.n; ++j) {
                if (H.labels[i] == G.labels[j] &&
                    G.adj[j].size() >= H.adj[i].size() &&
                    G.rev_adj[j].size() >= H.rev_adj[i].size()) {
                    candidates[i].push_back(j);
                }
            }
        }

        // Heuristic: Selection order based on connectivity and degree
        vector<bool> visited(H.n, false);
        for (int i = 0; i < H.n; ++i) {
            int best_v = -1;
            int max_conn = -1;
            int max_deg = -1;

            for (int v = 0; v < H.n; ++v) {
                if (visited[v]) continue;
                int conn = 0;
                for (int neighbor : H.adj[v]) if (visited[neighbor]) conn++;
                for (int neighbor : H.rev_adj[v]) if (visited[neighbor]) conn++;

                int deg = H.adj[v].size() + H.rev_adj[v].size();
                if (conn > max_conn || (conn == max_conn && deg > max_deg)) {
                    max_conn = conn;
                    max_deg = deg;
                    best_v = v;
                }
            }
            order.push_back(best_v);
            visited[best_v] = true;
        }
    }

    bool is_feasible(int h_idx, int g_node) {
        // Induced Subgraph Check
        for (int i = 0; i < h_idx; ++i) {
            int prev_h = order[i];
            int prev_g = h_to_g[prev_h];

            // Edge Preservation (H -> G)
            if (H.matrix[prev_h][order[h_idx]] && !G.matrix[prev_g][g_node]) return false;
            if (H.matrix[order[h_idx]][prev_h] && !G.matrix[g_node][prev_g]) return false;

            // Induced Constraint (G -> H: No extra edges in G)
            if (G.matrix[prev_g][g_node] && !H.matrix[prev_h][order[h_idx]]) return false;
            if (G.matrix[g_node][prev_g] && !H.matrix[order[h_idx]][prev_h]) return false;
        }
        return true;
    }

    void solve(int idx) {
        if (idx == H.n) {
            count++;
            return;
        }

        int u = order[idx];
        for (int v : candidates[u]) {
            if (!g_used[v]) {
                if (is_feasible(idx, v)) {
                    g_used[v] = true;
                    h_to_g[u] = v;
                    solve(idx + 1);
                    h_to_g[u] = -1;
                    g_used[v] = false;
                }
            }
        }
    }
};

int main(int argc, char** argv) {
    if (argc < 3) return 1;

    Graph H = read_graph(argv[1]);
    Graph G = read_graph(argv[2]);

    if (H.n > G.n) {
        cout << 0 << endl;
        return 0;
    }

    Solver solver(H, G);
    solver.preprocess();
    solver.solve(0);

    cout << solver.count << endl;

    return 0;
}