#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <algorithm>
#include <stdint.h>

using namespace std;

/**
 * Compact Bitset implementation for efficient adjacency and domain operations.
 * Optimized for GCC/Clang environments with __builtin intrinsics.
 */
struct Bitset {
    vector<uint64_t> bits;
    int n_bits;

    Bitset() : n_bits(0) {}
    Bitset(int n) : n_bits(n) {
        bits.assign((n + 63) / 64, 0);
    }

    inline void set(int i) {
        bits[i >> 6] |= (1ULL << (i & 63));
    }

    inline bool test(int i) const {
        return (bits[i >> 6] >> (i & 63)) & 1ULL;
    }

    inline int count() const {
        int c = 0;
        for (uint64_t b : bits) c += __builtin_popcountll(b);
        return c;
    }

    inline bool empty() const {
        for (uint64_t b : bits) if (b) return false;
        return true;
    }

    /**
     * Checks if the intersection of two bitsets is non-empty.
     */
    static inline bool intersects(const Bitset& a, const Bitset& b) {
        size_t sz = a.bits.size();
        for (size_t i = 0; i < sz; ++i) {
            if (a.bits[i] & b.bits[i]) return true;
        }
        return false;
    }
};

struct Graph {
    int n;
    vector<int> labels;
    vector<vector<int>> adj;
    vector<int> degrees;
};

/**
 * Reads the Glasgow-family vertex-labelled LAD format.
 */
Graph read_lad(const string& filename) {
    ifstream infile(filename);
    if (!infile) exit(0);
    int n;
    if (!(infile >> n)) exit(0);
    Graph g;
    g.n = n;
    g.labels.resize(n);
    g.adj.resize(n);
    g.degrees.resize(n);
    for (int i = 0; i < n; ++i) {
        int lbl, deg;
        if (!(infile >> lbl >> deg)) break;
        g.labels[i] = lbl;
        g.degrees[i] = deg;
        for (int j = 0; j < deg; ++j) {
            int neigh;
            infile >> neigh;
            g.adj[i].push_back(neigh);
        }
    }
    return g;
}

class SubgraphSolver {
    Graph H, G;
    vector<Bitset> adjG_bits;
    vector<Bitset> domains;
    vector<int> order;
    vector<vector<int>> preds;
    vector<int> mapping;
    vector<bool> usedG;
    long long total_count = 0;

public:
    SubgraphSolver(Graph h, Graph g) : H(h), G(g) {
        adjG_bits.assign(G.n, Bitset(G.n));
        for (int i = 0; i < G.n; ++i) {
            for (int v : G.adj[i]) adjG_bits[i].set(v);
        }
        mapping.assign(H.n, -1);
        usedG.assign(G.n, false);
    }

    /**
     * Propagates neighborhood constraints to reduce candidate domains.
     * For every pattern vertex u, a candidate v in Domain(u) must have 
     * at least one neighbor in Domain(u') for every neighbor u' of u.
     */
    bool refine() {
        bool changed = true;
        while (changed) {
            changed = false;
            for (int u = 0; u < H.n; ++u) {
                Bitset& dom_u = domains[u];
                for (size_t k = 0; k < dom_u.bits.size(); ++k) {
                    uint64_t val = dom_u.bits[k];
                    if (!val) continue;
                    uint64_t mask = 0;
                    uint64_t temp_val = val;
                    while (temp_val) {
                        int bit = __builtin_ctzll(temp_val);
                        int v = (k << 6) + bit;
                        if (v >= G.n) break;
                        
                        bool ok = true;
                        for (int u_neigh : H.adj[u]) {
                            if (!Bitset::intersects(adjG_bits[v], domains[u_neigh])) {
                                ok = false;
                                break;
                            }
                        }
                        if (!ok) {
                            mask |= (1ULL << bit);
                            changed = true;
                        }
                        temp_val &= ~(1ULL << bit);
                    }
                    dom_u.bits[k] &= ~mask;
                    if (dom_u.empty()) return false;
                }
            }
        }
        return true;
    }

    /**
     * Initializes domains based on labels/degrees and determines search order.
     */
    void prepare() {
        domains.assign(H.n, Bitset(G.n));
        for (int u = 0; u < H.n; ++u) {
            for (int v = 0; v < G.n; ++v) {
                if (H.labels[u] == G.labels[v] && H.degrees[u] <= G.degrees[v]) {
                    domains[u].set(v);
                }
            }
            if (domains[u].empty()) { domains.clear(); return; }
        }

        if (!refine()) { domains.clear(); return; }

        // Ordering Strategy: MRV (Minimum Remaining Values) combined with connectivity.
        // Priority given to vertices connected to the already-placed set.
        vector<bool> placed(H.n, false);
        for (int i = 0; i < H.n; ++i) {
            int best_u = -1;
            long long min_dom = 0x7FFFFFFFFFFFFFFFLL;
            int max_conn = -1;
            for (int u = 0; u < H.n; ++u) {
                if (placed[u]) continue;
                int conn = 0;
                for (int neighbor : H.adj[u]) if (placed[neighbor]) conn++;
                int d_size = domains[u].count();
                if (conn > max_conn || (conn == max_conn && d_size < min_dom)) {
                    max_conn = conn;
                    min_dom = d_size;
                    best_u = u;
                }
            }
            order.push_back(best_u);
            placed[best_u] = true;
        }

        // Cache predecessors in the search order for fast edge preservation checks.
        preds.resize(H.n);
        placed.assign(H.n, false);
        for (int u : order) {
            for (int neighbor : H.adj[u]) {
                if (placed[neighbor]) preds[u].push_back(neighbor);
            }
            placed[u] = true;
        }
    }

    /**
     * Recursive backtracking search to count all injective mappings.
     */
    void solve(int idx) {
        if (idx == H.n) {
            total_count++;
            return;
        }
        int u = order[idx];
        const Bitset& dom_u = domains[u];
        const vector<int>& u_preds = preds[u];

        for (size_t k = 0; k < dom_u.bits.size(); ++k) {
            uint64_t possible = dom_u.bits[k];
            while (possible) {
                int bit = __builtin_ctzll(possible);
                int v = (k << 6) + bit;
                if (v >= G.n) break;
                
                if (!usedG[v]) {
                    bool ok = true;
                    // Check if current target vertex v is adjacent to all target
                    // vertices already assigned to neighbors of u.
                    for (int pu : u_preds) {
                        if (!adjG_bits[v].test(mapping[pu])) {
                            ok = false;
                            break;
                        }
                    }
                    if (ok) {
                        mapping[u] = v;
                        usedG[v] = true;
                        solve(idx + 1);
                        usedG[v] = false;
                        mapping[u] = -1;
                    }
                }
                possible &= ~(1ULL << bit);
            }
        }
    }

    long long get_count() {
        if (domains.empty()) return 0;
        solve(0);
        return total_count;
    }
};

int main(int argc, char* argv[]) {
    if (argc < 3) return 0;
    
    Graph H = read_lad(argv[1]);
    Graph G = read_lad(argv[2]);

    // Fast exit if pattern is larger than target.
    if (H.n > G.n) {
        cout << 0 << endl;
        return 0;
    }

    SubgraphSolver solver(H, G);
    solver.prepare();
    cout << solver.get_count() << endl;

    return 0;
}