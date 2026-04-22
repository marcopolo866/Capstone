#include <bits/stdc++.h>
using namespace std;

struct Graph {
    int n;
    vector<int> label;
    vector<vector<int>> adj;
    vector<unordered_set<int>> adjSet;
};

Graph readGraph(const char* path) {
    ifstream f(path);
    Graph g;
    f >> g.n;
    g.label.resize(g.n);
    g.adj.resize(g.n);
    g.adjSet.resize(g.n);
    for (int i = 0; i < g.n; i++) {
        int deg;
        f >> g.label[i] >> deg;
        g.adj[i].resize(deg);
        for (int j = 0; j < deg; j++) {
            f >> g.adj[i][j];
            g.adjSet[i].insert(g.adj[i][j]);
        }
    }
    return g;
}

static Graph H, G;
static int hn, gn;
static vector<int> order;
static vector<int> mapping;   // mapping[hi] = gi
static vector<bool> used;
static long long count_;
static vector<vector<int>> cands; // initial candidates per pattern vertex

// For each position in order, precomputed pattern neighbors that appear earlier in order
static vector<vector<pair<int,int>>> prevNeighbors; // prevNeighbors[pos] = list of (patternVertex, orderPos)

void buildOrder() {
    // Degree-based ordering with BFS-like connectivity
    vector<bool> inOrder(hn, false);
    order.clear();
    order.reserve(hn);

    // Start with highest degree
    int start = 0;
    for (int i = 1; i < hn; i++)
        if (H.adj[i].size() > H.adj[start].size()) start = i;
    order.push_back(start);
    inOrder[start] = true;

    while ((int)order.size() < hn) {
        int best = -1, bestScore = -1;
        for (int v : order) {
            for (int nb : H.adj[v]) {
                if (inOrder[nb]) continue;
                int score = 0;
                for (int nb2 : H.adj[nb])
                    if (inOrder[nb2]) score++;
                if (score > bestScore || (score == bestScore && best != -1 && H.adj[nb].size() > H.adj[best].size())) {
                    bestScore = score;
                    best = nb;
                }
            }
        }
        if (best == -1) {
            // disconnected: pick highest degree unplaced
            for (int i = 0; i < hn; i++) {
                if (!inOrder[i]) {
                    if (best == -1 || H.adj[i].size() > H.adj[best].size()) best = i;
                }
            }
        }
        order.push_back(best);
        inOrder[best] = true;
    }
}

void buildPrevNeighbors() {
    vector<int> posOf(hn);
    for (int i = 0; i < hn; i++) posOf[order[i]] = i;
    prevNeighbors.resize(hn);
    for (int i = 0; i < hn; i++) {
        int v = order[i];
        for (int nb : H.adj[v]) {
            if (posOf[nb] < i) {
                prevNeighbors[i].push_back({nb, posOf[nb]});
            }
        }
    }
}

void buildCands() {
    cands.resize(hn);
    for (int i = 0; i < hn; i++) {
        int v = order[i];
        int lv = H.label[v];
        int hdeg = (int)H.adj[v].size();
        for (int u = 0; u < gn; u++) {
            if (G.label[u] == lv && (int)G.adj[u].size() >= hdeg)
                cands[i].push_back(u);
        }
    }
}

void solve(int depth) {
    if (depth == hn) {
        count_++;
        return;
    }
    int pv = order[depth];
    (void)pv;
    for (int gv : cands[depth]) {
        if (used[gv]) continue;
        // Check all previously placed neighbors
        bool ok = true;
        for (auto [nb, nbPos] : prevNeighbors[depth]) {
            int mapped = mapping[nb];
            if (!G.adjSet[gv].count(mapped)) { ok = false; break; }
        }
        if (!ok) continue;
        mapping[pv] = gv;
        used[gv] = true;
        solve(depth + 1);
        used[gv] = false;
        mapping[pv] = -1;
    }
}

int main(int argc, char* argv[]) {
    if (argc < 3) return 1;
    H = readGraph(argv[1]);
    G = readGraph(argv[2]);
    hn = H.n; gn = G.n;
    mapping.assign(hn, -1);
    used.assign(gn, false);
    count_ = 0;
    buildOrder();
    buildPrevNeighbors();
    buildCands();
    solve(0);
    cout << count_ << "\n";
    return 0;
}