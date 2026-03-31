#include <vector>
#include <unordered_set>
#include <algorithm>
#include <climits>
#include <cstdio>
#include <cstdlib>
using namespace std;

// ── Graph representation ──────────────────────────────────────────────────────

struct Graph {
    int n;
    vector<int> label;
    vector<vector<int>> out, in;
    vector<unordered_set<int>> outSet, inSet;

    void init(int _n) {
        n = _n;
        label.resize(n);
        out.resize(n); in.resize(n);
        outSet.resize(n); inSet.resize(n);
    }

    void addEdge(int u, int v) {
        out[u].push_back(v);
        in[v].push_back(u);
        outSet[u].insert(v);
        inSet[v].insert(u);
    }

    bool hasEdge(int u, int v) const { return outSet[u].count(v) > 0; }
    int outDeg(int u) const { return (int)out[u].size(); }
    int inDeg(int u)  const { return (int)in[u].size(); }
};

Graph readGraph(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) { fprintf(stderr, "Cannot open %s\n", path); exit(1); }
    int n; fscanf(f, "%d", &n);
    Graph g; g.init(n);
    for (int i = 0; i < n; i++) {
        int id, lbl; fscanf(f, "%d %d", &id, &lbl);
        g.label[id] = lbl;
    }
    for (int i = 0; i < n; i++) {
        int k; fscanf(f, "%d", &k);
        for (int j = 0; j < k; j++) {
            int u, v; fscanf(f, "%d %d", &u, &v);
            g.addEdge(u, v);
        }
    }
    fclose(f);
    return g;
}

// ── Matching order ────────────────────────────────────────────────────────────
// Greedy: at each step pick the unordered node with most connections
// to already-ordered nodes. Tie-break: highest total degree.

vector<int> computeMatchingOrder(const Graph& H) {
    int n = H.n;
    vector<bool> inOrder(n, false);
    vector<int> order;
    order.reserve(n);
    vector<int> connScore(n, 0);

    auto totalDeg = [&](int u) { return H.outDeg(u) + H.inDeg(u); };

    int start = 0;
    for (int i = 1; i < n; i++)
        if (totalDeg(i) > totalDeg(start)) start = i;

    auto addNode = [&](int u) {
        order.push_back(u); inOrder[u] = true;
        for (int v : H.out[u]) if (!inOrder[v]) connScore[v]++;
        for (int v : H.in[u])  if (!inOrder[v]) connScore[v]++;
    };

    addNode(start);
    while ((int)order.size() < n) {
        int best = -1;
        for (int u = 0; u < n; u++) {
            if (inOrder[u]) continue;
            if (best == -1 ||
                connScore[u] > connScore[best] ||
                (connScore[u] == connScore[best] && totalDeg(u) > totalDeg(best)))
                best = u;
        }
        addNode(best);
    }
    return order;
}

// ── Solver ────────────────────────────────────────────────────────────────────

struct Solver {
    const Graph& H;
    const Graph& G;
    int hn, gn;

    vector<int> order;
    vector<int> posInOrder;

    // For each depth d, precomputed relationship to all j < d:
    struct DepthInfo {
        vector<int> pred;  // j where order[j]->order[d] in H
        vector<int> succ;  // j where order[d]->order[j] in H
        vector<int> none;  // j where no edge in H (neither direction)
        // "both" edges: j appears in both pred and succ
    };
    vector<DepthInfo> di;

    vector<int> hToG;
    vector<bool> used;
    long long count;

    Solver(const Graph& _H, const Graph& _G)
        : H(_H), G(_G), hn(_H.n), gn(_G.n), count(0)
    {
        order = computeMatchingOrder(H);
        posInOrder.resize(hn);
        for (int i = 0; i < hn; i++) posInOrder[order[i]] = i;

        di.resize(hn);
        for (int i = 0; i < hn; i++) {
            int u = order[i];
            for (int j = 0; j < i; j++) {
                int v = order[j];
                bool vu = H.hasEdge(v, u);
                bool uv = H.hasEdge(u, v);
                if (vu) di[i].pred.push_back(j);
                if (uv) di[i].succ.push_back(j);
                if (!vu && !uv) di[i].none.push_back(j);
            }
        }

        hToG.resize(hn, -1);
        used.resize(gn, false);
    }

    bool getCandidates(int depth, vector<int>& cands) {
        int hu = order[depth];
        int lbl     = H.label[hu];
        int needOut = H.outDeg(hu);
        int needIn  = H.inDeg(hu);

        const auto& pp = di[depth].pred;
        const auto& ps = di[depth].succ;

        if (pp.empty() && ps.empty()) {
            for (int gv = 0; gv < gn; gv++) {
                if (!used[gv] && G.label[gv] == lbl &&
                    G.outDeg(gv) >= needOut && G.inDeg(gv) >= needIn)
                    cands.push_back(gv);
            }
        } else {
            // Find smallest anchoring set
            int bestJ = -1;
            int bestSz = INT_MAX;
            bool bestIsPred = true;

            for (int j : pp) {
                int sz = (int)G.out[hToG[order[j]]].size();
                if (sz < bestSz) { bestSz = sz; bestJ = j; bestIsPred = true; }
            }
            for (int j : ps) {
                int sz = (int)G.in[hToG[order[j]]].size();
                if (sz < bestSz) { bestSz = sz; bestJ = j; bestIsPred = false; }
            }

            if (bestIsPred) {
                int gj = hToG[order[bestJ]];
                for (int gv : G.out[gj]) {
                    if (!used[gv] && G.label[gv] == lbl &&
                        G.outDeg(gv) >= needOut && G.inDeg(gv) >= needIn)
                        cands.push_back(gv);
                }
            } else {
                int gj = hToG[order[bestJ]];
                for (int gv : G.in[gj]) {
                    if (!used[gv] && G.label[gv] == lbl &&
                        G.outDeg(gv) >= needOut && G.inDeg(gv) >= needIn)
                        cands.push_back(gv);
                }
            }
            if (cands.empty()) return false;

            // Intersect with remaining pred constraints
            for (int j : pp) {
                if (j == bestJ && bestIsPred) continue;
                int gj = hToG[order[j]];
                size_t w = 0;
                for (size_t r = 0; r < cands.size(); r++)
                    if (G.hasEdge(gj, cands[r])) cands[w++] = cands[r];
                cands.resize(w);
                if (cands.empty()) return false;
            }

            // Intersect with remaining succ constraints
            for (int j : ps) {
                if (j == bestJ && !bestIsPred) continue;
                int gj = hToG[order[j]];
                size_t w = 0;
                for (size_t r = 0; r < cands.size(); r++)
                    if (G.hasEdge(cands[r], gj)) cands[w++] = cands[r];
                cands.resize(w);
                if (cands.empty()) return false;
            }
        }
        return !cands.empty();
    }

    // Check node-induced constraint: no extra edges in G not in H.
    // getCandidates already enforced all required edges (pred + succ).
    // We only need to check "no-edge" pairs and "reverse" of one-directional edges.
    bool checkInduced(int depth, int gv) {
        int hu = order[depth];

        // No-edge pairs: neither direction
        for (int j : di[depth].none) {
            int gj = hToG[order[j]];
            if (G.hasEdge(gv, gj) || G.hasEdge(gj, gv)) return false;
        }

        // One-directional pred edges (v->u in H, not u->v):
        // getCandidates ensured G.hasEdge(gj, gv). Check ~G.hasEdge(gv, gj).
        for (int j : di[depth].pred) {
            int hv = order[j];
            if (!H.hasEdge(hu, hv)) { // only one direction (hv->hu)
                if (G.hasEdge(gv, hToG[hv])) return false;
            }
            // If both directions, succ will handle the other check
        }

        // One-directional succ edges (u->v in H, not v->u):
        // getCandidates ensured G.hasEdge(gv, gj). Check ~G.hasEdge(gj, gv).
        for (int j : di[depth].succ) {
            int hv = order[j];
            if (!H.hasEdge(hv, hu)) { // only one direction (hu->hv)
                if (G.hasEdge(hToG[hv], gv)) return false;
            }
        }

        return true;
    }

    void search(int depth) {
        if (depth == hn) { count++; return; }

        vector<int> cands;
        cands.reserve(64);
        if (!getCandidates(depth, cands)) return;

        int hu = order[depth];
        for (int gv : cands) {
            if (!checkInduced(depth, gv)) continue;
            hToG[hu] = gv;
            used[gv] = true;
            search(depth + 1);
            used[gv] = false;
        }
        hToG[hu] = -1;
    }

    long long solve() { count = 0; search(0); return count; }
};

int main(int argc, char* argv[]) {
    if (argc < 3) { fprintf(stderr, "Usage: %s <pattern> <target>\n", argv[0]); return 1; }
    Graph H = readGraph(argv[1]);
    Graph G = readGraph(argv[2]);
    Solver solver(H, G);
    printf("%lld\n", solver.solve());
    return 0;
}