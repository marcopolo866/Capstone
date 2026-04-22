#include <cstdio>
#include <cstdlib>
#include <vector>
#include <unordered_set>
#include <algorithm>
#include <functional>
#include <fstream>
#include <map>
#include <cstdint>
#include <climits>

struct Graph {
    int n;
    std::vector<int> label;
    std::vector<std::vector<int>> adj;
    // Adjacency as bitset-like sorted list for fast edge checks
    std::vector<std::unordered_set<int>> adjset;
};

Graph readGraph(const char* path) {
    std::ifstream f(path);
    Graph g;
    f >> g.n;
    g.label.resize(g.n);
    g.adj.resize(g.n);
    g.adjset.resize(g.n);
    for (int i = 0; i < g.n; i++) {
        int lbl, deg;
        f >> lbl >> deg;
        g.label[i] = lbl;
        g.adj[i].resize(deg);
        for (int j = 0; j < deg; j++) {
            f >> g.adj[i][j];
            g.adjset[i].insert(g.adj[i][j]);
        }
    }
    return g;
}

int main(int argc, char** argv) {
    if (argc < 3) return 1;

    Graph H = readGraph(argv[1]);
    Graph G = readGraph(argv[2]);

    int hn = H.n;
    int gn = G.n;

    // For each target vertex, build a label->count map of its neighbors
    // for stronger candidate pruning
    std::vector<std::map<int,int>> gNbrLabelCount(gn);
    for (int v = 0; v < gn; v++) {
        for (int nb : G.adj[v]) {
            gNbrLabelCount[v][G.label[nb]]++;
        }
    }

    // For each pattern vertex, build a label->count map of its neighbors
    std::vector<std::map<int,int>> hNbrLabelCount(hn);
    for (int u = 0; u < hn; u++) {
        for (int nb : H.adj[u]) {
            hNbrLabelCount[u][H.label[nb]]++;
        }
    }

    // Compute initial candidates for each pattern vertex
    // Candidate v for pattern vertex u requires:
    //   1. label(v) == label(u)
    //   2. deg(v) >= deg(u)
    //   3. For each label l, gNbrLabelCount[v][l] >= hNbrLabelCount[u][l]
    std::vector<std::vector<int>> cands(hn);
    for (int u = 0; u < hn; u++) {
        for (int v = 0; v < gn; v++) {
            if (G.label[v] != H.label[u]) continue;
            if ((int)G.adj[v].size() < (int)H.adj[u].size()) continue;
            bool ok = true;
            for (auto& [lbl, cnt] : hNbrLabelCount[u]) {
                auto it = gNbrLabelCount[v].find(lbl);
                if (it == gNbrLabelCount[v].end() || it->second < cnt) {
                    ok = false; break;
                }
            }
            if (ok) cands[u].push_back(v);
        }
    }

    // Compute vertex ordering for pattern
    // Strategy: greedy, always pick the unordered vertex that:
    //   (a) has the most already-ordered neighbors (maximises constraint propagation)
    //   (b) ties broken by fewest candidates (most constrained)
    std::vector<int> order;
    order.reserve(hn);
    std::vector<bool> inOrder(hn, false);

    // Start with most constrained (fewest candidates)
    {
        int best = 0;
        for (int u = 1; u < hn; u++) {
            if (cands[u].size() < cands[best].size()) best = u;
        }
        order.push_back(best);
        inOrder[best] = true;
    }

    while ((int)order.size() < hn) {
        int best = -1;
        int bestAdjCount = -1;
        size_t bestCandSize = SIZE_MAX;

        for (int u = 0; u < hn; u++) {
            if (inOrder[u]) continue;
            int adjCount = 0;
            for (int nb : H.adj[u]) {
                if (inOrder[nb]) adjCount++;
            }
            bool better = false;
            if (best == -1) {
                better = true;
            } else if (adjCount > bestAdjCount) {
                better = true;
            } else if (adjCount == bestAdjCount && cands[u].size() < bestCandSize) {
                better = true;
            }
            if (better) {
                best = u;
                bestAdjCount = adjCount;
                bestCandSize = cands[u].size();
            }
        }
        order.push_back(best);
        inOrder[best] = true;
    }

    // For each position i in order, precompute which earlier positions j < i
    // correspond to pattern neighbors of order[i]
    std::vector<std::vector<int>> prevNeighbors(hn);
    for (int i = 0; i < hn; i++) {
        int u = order[i];
        for (int j = 0; j < i; j++) {
            int w = order[j];
            if (H.adjset[u].count(w)) {
                prevNeighbors[i].push_back(j);
            }
        }
    }

    // Backtracking search
    std::vector<int> assignment(hn, -1);
    std::vector<bool> used(gn, false);
    long long count = 0;

    // Iterative DFS to avoid function call overhead on deep stacks
    // depth, candidate index
    std::vector<int> candIdx(hn, 0);
    int depth = 0;

    // We'll use a simple recursive lambda but with explicit stack to be safe
    std::function<void(int)> solve = [&](int d) {
        if (d == hn) {
            count++;
            return;
        }
        int u = order[d];
        const auto& cv = cands[u];
        const auto& pn = prevNeighbors[d];

        for (int v : cv) {
            if (used[v]) continue;

            // Check edge constraints with previously assigned neighbors
            bool ok = true;
            for (int j : pn) {
                int w = assignment[j];
                if (!G.adjset[v].count(w)) {
                    ok = false;
                    break;
                }
            }
            if (!ok) continue;

            assignment[d] = v;
            used[v] = true;
            solve(d + 1);
            used[v] = false;
        }
        assignment[d] = -1;
    };

    solve(0);

    printf("%lld\n", count);
    return 0;
}