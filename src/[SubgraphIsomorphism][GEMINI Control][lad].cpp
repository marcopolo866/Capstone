#include <iostream>
#include <vector>
#include <fstream>
#include <algorithm>
#include <cstdint>

using namespace std;

struct Bitset {
    vector<uint64_t> bits;
    int size;

    Bitset() : size(0) {}
    Bitset(int n) : size(n) {
        bits.assign((n + 63) / 64, 0);
    }

    inline void set(int i) {
        bits[i >> 6] |= (1ULL << (i & 63));
    }

    inline bool get(int i) const {
        return (bits[i >> 6] >> (i & 63)) & 1;
    }

    inline int count() const {
        int c = 0;
        for (uint64_t b : bits) c += __builtin_popcountll(b);
        return c;
    }
};

struct Graph {
    int n;
    vector<int> labels;
    vector<vector<int>> adj;
    vector<Bitset> adj_mat;

    Graph(int n_v) : n(n_v), labels(n_v), adj(n_v), adj_mat(n_v, Bitset(n_v)) {}
};

Graph read_lad(const string& filename) {
    ifstream infile(filename);
    if (!infile) exit(1);
    int n;
    if (!(infile >> n)) exit(1);
    Graph g(n);
    for (int i = 0; i < n; ++i) {
        int label, degree;
        infile >> label >> degree;
        g.labels[i] = label;
        for (int j = 0; j < degree; ++j) {
            int neighbor;
            infile >> neighbor;
            g.adj[i].push_back(neighbor);
            g.adj_mat[i].set(neighbor);
        }
    }
    return g;
}

struct Solver {
    const Graph& H;
    const Graph& G;
    vector<int> p_to_t;
    vector<bool> t_used;
    vector<int> order;
    vector<vector<int>> forward_edges; 
    long long total_count = 0;

    Solver(const Graph& h, const Graph& g) : H(h), G(g), p_to_t(h.n, -1), t_used(g.n, false) {
        select_order();
    }

    void select_order() {
        vector<bool> visited(H.n, false);
        for (int i = 0; i < H.n; ++i) {
            int best_u = -1;
            int max_conn = -1;
            int min_dom = 1e9;

            for (int u = 0; u < H.n; ++u) {
                if (visited[u]) continue;
                int conn = 0;
                for (int v : H.adj[u]) if (visited[v]) conn++;

                int dom_estimate = 0;
                for (int t = 0; t < G.n; ++t) {
                    if (G.labels[t] == H.labels[u] && G.adj[t].size() >= H.adj[u].size()) {
                        dom_estimate++;
                    }
                }

                if (conn > max_conn) {
                    max_conn = conn;
                    min_dom = dom_estimate;
                    best_u = u;
                } else if (conn == max_conn && dom_estimate < min_dom) {
                    min_dom = dom_estimate;
                    best_u = u;
                }
            }
            order.push_back(best_u);
            visited[best_u] = true;
        }

        forward_edges.resize(H.n);
        vector<bool> placed(H.n, false);
        for (int u : order) {
            for (int neighbor : H.adj[u]) {
                if (placed[neighbor]) {
                    forward_edges[u].push_back(neighbor);
                }
            }
            placed[u] = true;
        }
    }

    void solve(int idx) {
        if (idx == H.n) {
            total_count++;
            return;
        }

        int u = order[idx];
        const auto& constraints = forward_edges[u];

        for (int v = 0; v < G.n; ++v) {
            if (t_used[v]) continue;
            if (G.labels[v] != H.labels[u]) continue;
            if (G.adj[v].size() < H.adj[u].size()) continue;

            bool possible = true;
            for (int pu : constraints) {
                if (!G.adj_mat[v].get(p_to_t[pu])) {
                    possible = false;
                    break;
                }
            }

            if (possible) {
                t_used[v] = true;
                p_to_t[u] = v;
                solve(idx + 1);
                p_to_t[u] = -1;
                t_used[v] = false;
            }
        }
    }
};

int main(int argc, char** argv) {
    if (argc != 3) return 1;

    Graph H = read_lad(argv[1]);
    Graph G = read_lad(argv[2]);

    Solver solver(H, G);
    solver.solve(0);

    cout << solver.total_count << endl;

    return 0;
}