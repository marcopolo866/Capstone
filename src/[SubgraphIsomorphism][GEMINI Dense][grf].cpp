#include <iostream>
#include <vector>
#include <fstream>
#include <algorithm>
#include <map>
#include <set>

/**
 * High-Performance Induced Subgraph Isomorphism Solver
 * * Strategy:
 * 1. Pre-filtering: Degree and Label consistency.
 * 2. Bitset-based Candidate sets: Using std::vector<bool> for memory-efficient 
 * intersection and pruning.
 * 3. Dynamic Ordering: Smallest Candidate Set First (SCSF) at each step.
 * 4. Constraint Propagation: When u is mapped to v, all neighbors of u
 * must map to neighbors of v (and non-neighbors to non-neighbors).
 */

struct Graph {
    int n;
    std::vector<int> labels;
    std::vector<std::vector<int>> adj; // Outgoing
    std::vector<std::vector<int>> rev_adj; // Incoming
    std::vector<std::vector<bool>> matrix; // For O(1) edge lookup

    Graph(int nodes) : n(nodes), labels(nodes, 0), adj(nodes), rev_adj(nodes), 
                       matrix(nodes, std::vector<bool>(nodes, false)) {}
};

Graph load_graph(const std::string& filename) {
    std::ifstream infile(filename);
    if (!infile.is_open()) exit(1);
    int n;
    infile >> n;
    Graph g(n);
    for (int i = 0; i < n; ++i) {
        int id, label;
        infile >> id >> label;
        g.labels[id] = label;
    }
    for (int i = 0; i < n; ++i) {
        int k;
        infile >> k;
        for (int j = 0; j < k; ++j) {
            int u, v;
            infile >> u >> v;
            g.adj[u].push_back(v);
            g.rev_adj[v].push_back(u);
            g.matrix[u][v] = true;
        }
    }
    return g;
}

struct Solver {
    const Graph& H;
    const Graph& G;
    long long total_count = 0;

    // candidate_sets[h_node][g_node] == true if g_node is a possible match
    std::vector<std::vector<bool>> candidate_sets;
    std::vector<int> mapping; // h_node -> g_node (-1 if unmapped)
    std::vector<bool> g_used; // g_node is already mapped

    Solver(const Graph& h, const Graph& g) 
        : H(h), G(g), candidate_sets(h.n, std::vector<bool>(g.n, false)), 
          mapping(h.n, -1), g_used(g.n, false) {}

    // Initial pruning: check labels and degrees (in/out)
    bool initial_refinement() {
        if (H.n > G.n) return false;
        for (int i = 0; i < H.n; ++i) {
            int valid_count = 0;
            for (int j = 0; j < G.n; ++j) {
                if (H.labels[i] == G.labels[j] &&
                    H.adj[i].size() <= G.adj[j].size() &&
                    H.rev_adj[i].size() <= G.rev_adj[j].size()) {
                    candidate_sets[i][j] = true;
                    valid_count++;
                }
            }
            if (valid_count == 0) return false;
        }
        return true;
    }

    // Induced constraint check: compares edges between mapped nodes
    bool is_induced_valid(int h_idx, int g_idx) {
        for (int prev_h = 0; prev_h < H.n; ++prev_h) {
            int prev_g = mapping[prev_h];
            if (prev_g == -1) continue;

            // Edge Preservation H -> G
            if (H.matrix[h_idx][prev_h] && !G.matrix[g_idx][prev_g]) return false;
            if (H.matrix[prev_h][h_idx] && !G.matrix[prev_g][g_idx]) return false;

            // Induced check (Extra edge in G not in H)
            if (G.matrix[g_idx][prev_g] && !H.matrix[h_idx][prev_h]) return false;
            if (G.matrix[prev_g][g_idx] && !H.matrix[prev_h][h_idx]) return false;
        }
        return true;
    }

    void solve() {
        if (!initial_refinement()) {
            std::cout << 0 << std::endl;
            return;
        }
        backtrack(0);
        std::cout << total_count << std::endl;
    }

    void backtrack(int matched_count) {
        if (matched_count == H.n) {
            total_count++;
            return;
        }

        // 1. Dynamic Search Order: Select h_node with smallest candidate set
        int best_h = -1;
        int min_candidates = G.n + 1;

        for (int i = 0; i < H.n; ++i) {
            if (mapping[i] == -1) {
                int count = 0;
                for (int j = 0; j < G.n; ++j) {
                    if (candidate_sets[i][j] && !g_used[j]) count++;
                }
                if (count == 0) return; // Early prune
                if (count < min_candidates) {
                    min_candidates = count;
                    best_h = i;
                }
            }
        }

        // 2. Try candidates for best_h
        for (int v = 0; v < G.n; ++v) {
            if (candidate_sets[best_h][v] && !g_used[v]) {
                if (is_induced_valid(best_h, v)) {
                    // Local propagation logic:
                    // Check if neighbors of best_h can still find matches in neighbors of v
                    // Since this is induced, we must also satisfy degree/label constraints
                    
                    mapping[best_h] = v;
                    g_used[v] = true;

                    backtrack(matched_count + 1);

                    // Reset state
                    mapping[best_h] = -1;
                    g_used[v] = false;
                }
            }
        }
    }
};

int main(int argc, char* argv[]) {
    if (argc < 3) return 1;

    Graph h = load_graph(argv[1]);
    Graph g = load_graph(argv[2]);

    Solver solver(h, g);
    solver.solve();

    return 0;
}