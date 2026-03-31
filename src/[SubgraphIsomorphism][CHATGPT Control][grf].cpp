#include <iostream>
#include <vector>
#include <fstream>
#include <algorithm>
#include <cstdint>
#include <functional>
#include <string>

using namespace std;

struct Graph {
    int n = 0;
    vector<int> label;
    vector<vector<int>> out;
    vector<vector<int>> in;
};

static bool read_graph(const string &filename, Graph &g) {
    ifstream fin(filename);
    if (!fin) return false;
    if (!(fin >> g.n)) return false;
    if (g.n < 0 || g.n > 1000000) return false;

    g.label.assign(g.n, 0);
    g.out.assign(g.n, {});
    g.in.assign(g.n, {});

    for (int i = 0; i < g.n; i++) {
        int id = -1, lbl = 0;
        if (!(fin >> id >> lbl)) return false;
        if (id < 0 || id >= g.n) return false;
        g.label[id] = lbl;
    }

    for (int i = 0; i < g.n; i++) {
        int k = 0;
        if (!(fin >> k)) return false;
        if (k < 0) return false;
        for (int j = 0; j < k; j++) {
            int u = -1, v = -1;
            if (!(fin >> u >> v)) return false;
            if (u < 0 || u >= g.n || v < 0 || v >= g.n) return false;
            g.out[u].push_back(v);
            g.in[v].push_back(u);
        }
    }

    // Sort adjacency for binary search
    for (int i = 0; i < g.n; i++) {
        sort(g.out[i].begin(), g.out[i].end());
        sort(g.in[i].begin(), g.in[i].end());
    }

    return true;
}

// Binary search edge existence
inline bool has_edge(const vector<vector<int>> &adj, int u, int v) {
    const auto &vec = adj[u];
    return binary_search(vec.begin(), vec.end(), v);
}

int main(int argc, char **argv) {
    bool first_only = false;
    vector<string> positional;
    positional.reserve(static_cast<size_t>(max(0, argc - 1)));
    for (int i = 1; i < argc; i++) {
        string arg = argv[i] ? string(argv[i]) : string();
        if (arg == "--non-induced") continue; // backwards-compatible no-op
        if (arg == "--first-only") { first_only = true; continue; }
        positional.push_back(arg);
    }

    if (positional.size() != 2) {
        cerr << "Usage: ./solver pattern target\n";
        return 1;
    }

    Graph H, G;
    if (!read_graph(positional[0], H) || !read_graph(positional[1], G)) {
        cerr << "Failed to parse graph input(s).\n";
        return 1;
    }

    const int nH = H.n;
    const int nG = G.n;

    // Precompute degrees
    vector<int> H_out_deg(nH), H_in_deg(nH);
    vector<int> G_out_deg(nG), G_in_deg(nG);

    for (int i = 0; i < nH; i++) {
        H_out_deg[i] = H.out[i].size();
        H_in_deg[i] = H.in[i].size();
    }
    for (int i = 0; i < nG; i++) {
        G_out_deg[i] = G.out[i].size();
        G_in_deg[i] = G.in[i].size();
    }

    // Initial candidate sets
    vector<vector<int>> candidates(nH);
    for (int u = 0; u < nH; u++) {
        for (int v = 0; v < nG; v++) {
            if (H.label[u] == G.label[v] &&
                H_out_deg[u] <= G_out_deg[v] &&
                H_in_deg[u] <= G_in_deg[v]) {
                candidates[u].push_back(v);
            }
        }
    }

    vector<int> mapping(nH, -1);
    vector<bool> used(nG, false);

    int64_t total = 0;

    // Order selection: smallest domain
    auto select_node = [&](const vector<vector<int>> &cand) {
        int best = -1;
        size_t best_size = SIZE_MAX;
        for (int i = 0; i < nH; i++) {
            if (mapping[i] == -1) {
                if (cand[i].size() < best_size) {
                    best_size = cand[i].size();
                    best = i;
                }
            }
        }
        return best;
    };

    // Recursive search
    function<bool(vector<vector<int>> &)> dfs =
    [&](vector<vector<int>> &cand) {

        int u = select_node(cand);
        if (u == -1) {
            total++;
            return first_only;
        }

        auto current_candidates = cand[u];

        for (int v : current_candidates) {
            if (used[v]) continue;

            bool ok = true;

            // Check consistency with assigned nodes
            for (int u2 = 0; u2 < nH && ok; u2++) {
                if (mapping[u2] != -1) {
                    int v2 = mapping[u2];

                    // Edge preservation
                    if (has_edge(H.out, u, u2) && !has_edge(G.out, v, v2)) ok = false;
                    if (has_edge(H.out, u2, u) && !has_edge(G.out, v2, v)) ok = false;

                    // Node-induced constraint
                    if (!has_edge(H.out, u, u2) && has_edge(G.out, v, v2)) ok = false;
                    if (!has_edge(H.out, u2, u) && has_edge(G.out, v2, v)) ok = false;
                }
            }

            if (!ok) continue;

            // Save state
            mapping[u] = v;
            used[v] = true;

            vector<vector<int>> new_cand = cand;

            // Forward pruning
            for (int u2 = 0; u2 < nH; u2++) {
                if (mapping[u2] != -1) continue;

                vector<int> filtered;
                for (int v2 : new_cand[u2]) {
                    if (used[v2]) continue;

                    bool keep = true;

                    // Check edge constraints with new mapping
                    if (has_edge(H.out, u, u2) && !has_edge(G.out, v, v2)) keep = false;
                    if (has_edge(H.out, u2, u) && !has_edge(G.out, v2, v)) keep = false;

                    if (!has_edge(H.out, u, u2) && has_edge(G.out, v, v2)) keep = false;
                    if (!has_edge(H.out, u2, u) && has_edge(G.out, v2, v)) keep = false;

                    if (keep) filtered.push_back(v2);
                }

                new_cand[u2].swap(filtered);

                if (new_cand[u2].empty()) {
                    ok = false;
                    break;
                }
            }

            if (ok && dfs(new_cand)) {
                mapping[u] = -1;
                used[v] = false;
                return true;
            }

            mapping[u] = -1;
            used[v] = false;
        }

        return false;
    };

    dfs(candidates);

    cout << total << "\n";
    return 0;
}
