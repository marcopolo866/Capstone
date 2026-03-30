#include <iostream>
#include <vector>
#include <fstream>
#include <cstdint>
#include <algorithm>
#include <string>

using namespace std;

// ----------- Bitset (dynamic, fast) -----------
struct Bitset {
    vector<uint64_t> w;
    int n;

    Bitset() {}
    Bitset(int n_) : n(n_), w((n_ + 63) >> 6, 0) {}

    inline void set(int i) { w[i >> 6] |= (1ULL << (i & 63)); }
    inline void reset(int i) { w[i >> 6] &= ~(1ULL << (i & 63)); }
    inline bool test(int i) const { return (w[i >> 6] >> (i & 63)) & 1ULL; }

    inline void fill() {
        for (auto &x : w) x = ~0ULL;
        trim();
    }

    inline void clear() {
        for (auto &x : w) x = 0;
    }

    inline void trim() {
        int extra = (w.size() << 6) - n;
        if (extra > 0)
            w.back() &= (~0ULL >> extra);
    }

    inline int count() const {
        int c = 0;
        for (auto x : w) c += __builtin_popcountll(x);
        return c;
    }

    inline bool empty() const {
        for (auto x : w) if (x) return false;
        return true;
    }

    inline void intersect(const Bitset &o) {
        for (size_t i = 0; i < w.size(); i++) w[i] &= o.w[i];
    }

    inline void subtract(const Bitset &o) {
        for (size_t i = 0; i < w.size(); i++) w[i] &= ~o.w[i];
    }
};

// ----------- Graph -----------
struct Graph {
    int n;
    vector<int> label;
    vector<Bitset> out, in;
};

Graph read_graph(const string &path) {
    ifstream fin(path);
    Graph g;
    fin >> g.n;
    g.label.resize(g.n);

    for (int i = 0; i < g.n; i++) {
        int id, l;
        fin >> id >> l;
        g.label[id] = l;
    }

    g.out.assign(g.n, Bitset(g.n));
    g.in.assign(g.n, Bitset(g.n));

    for (int i = 0; i < g.n; i++) {
        int k;
        fin >> k;
        for (int j = 0; j < k; j++) {
            int u, v;
            fin >> u >> v;
            g.out[u].set(v);
            g.in[v].set(u);
        }
    }

    return g;
}

// ----------- Solver State -----------
Graph H, G;

vector<Bitset> cand;   // candidate sets
vector<int> matchH;    // H -> G
vector<int> matchG;    // G -> H

long long solution_count = 0;

// ----------- Initial Filtering -----------
void initial_filter() {
    for (int u = 0; u < H.n; u++) {
        for (int v = 0; v < G.n; v++) {
            if (H.label[u] != G.label[v]) continue;

            // degree pruning
            if (H.out[u].count() > G.out[v].count()) continue;
            if (H.in[u].count() > G.in[v].count()) continue;

            cand[u].set(v);
        }
    }
}

// ----------- Propagation -----------
bool propagate() {
    bool changed = true;

    while (changed) {
        changed = false;

        for (int u = 0; u < H.n; u++) {
            if (matchH[u] != -1) continue;

            Bitset newC = cand[u];

            // enforce adjacency with matched nodes
            for (int v = 0; v < H.n; v++) {
                if (matchH[v] == -1) continue;

                int gv = matchH[v];

                if (H.out[u].test(v)) {
                    newC.intersect(G.in[gv]);
                } else {
                    newC.subtract(G.in[gv]);
                }

                if (H.out[v].test(u)) {
                    newC.intersect(G.out[gv]);
                } else {
                    newC.subtract(G.out[gv]);
                }
            }

            if (newC.empty()) return false;

            // detect change
            for (size_t i = 0; i < newC.w.size(); i++) {
                if (newC.w[i] != cand[u].w[i]) {
                    cand[u] = newC;
                    changed = true;
                    break;
                }
            }
        }
    }

    return true;
}

// ----------- Select Next Variable -----------
int select_node() {
    int best = -1;
    int bestSize = 1e9;

    for (int i = 0; i < H.n; i++) {
        if (matchH[i] != -1) continue;

        int sz = cand[i].count();
        if (sz < bestSize) {
            bestSize = sz;
            best = i;
        }
    }

    return best;
}

// ----------- DFS -----------
void dfs() {
    if (!propagate()) return;

    int u = select_node();
    if (u == -1) {
        solution_count++;
        return;
    }

    Bitset options = cand[u];

    for (int v = 0; v < G.n; v++) {
        if (!options.test(v)) continue;
        if (matchG[v] != -1) continue;

        // save state
        auto cand_backup = cand;
        auto matchH_backup = matchH;
        auto matchG_backup = matchG;

        // assign
        matchH[u] = v;
        matchG[v] = u;

        // enforce injectivity
        for (int i = 0; i < H.n; i++) {
            if (i != u) cand[i].reset(v);
        }

        dfs();

        // restore
        cand = cand_backup;
        matchH = matchH_backup;
        matchG = matchG_backup;
    }
}

// ----------- Main -----------
int main(int argc, char** argv) {
    if (argc != 3) {
        cerr << "Usage: ./solver pattern target\n";
        return 1;
    }

    H = read_graph(argv[1]);
    G = read_graph(argv[2]);

    cand.assign(H.n, Bitset(G.n));
    matchH.assign(H.n, -1);
    matchG.assign(G.n, -1);

    initial_filter();

    dfs();

    cout << solution_count << "\n";
    return 0;
}