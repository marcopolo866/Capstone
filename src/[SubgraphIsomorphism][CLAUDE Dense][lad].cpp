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

// For each pattern vertex, bitset of candidate target vertices
// Using uint64_t words
static const int MAXG = 2048;
static int words; // ceil(gn/64)

struct Domain {
    uint64_t bits[MAXG/64];
    int count;
};

inline bool testBit(const uint64_t* b, int i) { return (b[i>>6] >> (i&63)) & 1; }
inline void setBit(uint64_t* b, int i) { b[i>>6] |= 1ULL << (i&63); }
inline void clearBit(uint64_t* b, int i) { b[i>>6] &= ~(1ULL << (i&63)); }

int popcount(const uint64_t* b, int w) {
    int c = 0;
    for (int i = 0; i < w; i++) c += __builtin_popcountll(b[i]);
    return c;
}

// domains[i] for pattern vertex i
static vector<Domain> initDomains;

// Search state
static vector<int> assignment; // assignment[i] = target vertex or -1
static uint64_t usedBits[MAXG/64]; // which target vertices are used

long long count_solutions;

// For each pattern vertex, precompute pattern neighbors
// neighbor constraint: if u->v in H and u is assigned to x, then v's domain must be subset of N(x)

// We do backtracking with forward checking
// Order: pick unassigned pattern vertex with smallest domain

// Domain storage per level: we store snapshots
struct Level {
    int pv; // pattern vertex assigned
    int tv; // target vertex assigned
    vector<Domain> saved; // saved domains for all unassigned vertices
};

// Iterative approach with explicit stack to avoid recursion overhead
// Actually use recursive for clarity but with domain snapshots

// For fast neighbor intersection: adjacency bitsets for target graph
static vector<array<uint64_t, MAXG/64>> gadj; // gadj[v] = bitset of neighbors of v in G

void intersectWithNeighbors(uint64_t* dom, int tv) {
    for (int w = 0; w < words; w++)
        dom[w] &= gadj[tv][w];
}

// domains: current domains for each pattern vertex
// assigned: assignment array
// assigned bitset: usedBits

long long solve(vector<Domain>& domains, vector<int>& asgn, int depth) {
    // Find unassigned vertex with smallest domain
    int best = -1, bestCount = INT_MAX;
    for (int i = 0; i < hn; i++) {
        if (asgn[i] != -1) continue;
        int c = domains[i].count;
        if (c == 0) return 0;
        if (c < bestCount) { bestCount = c; best = i; }
    }
    if (best == -1) return 1; // all assigned

    // Try each candidate for best
    long long total = 0;
    int pv = best;
    
    // Collect candidates
    vector<int> cands;
    cands.reserve(bestCount);
    for (int w = 0; w < words; w++) {
        uint64_t b = domains[pv].bits[w];
        while (b) {
            int bit = __builtin_ctzll(b);
            int tv = w*64 + bit;
            if (tv < gn) cands.push_back(tv);
            b &= b-1;
        }
    }

    for (int tv : cands) {
        if (testBit(usedBits, tv)) continue;
        
        // Save domains
        vector<Domain> saved = domains;
        
        // Assign pv -> tv
        asgn[pv] = tv;
        setBit(usedBits, tv);
        
        // Update domains: for each unassigned neighbor of pv in H,
        // intersect their domain with N(tv) in G
        // Also remove tv from all unassigned domains
        bool feasible = true;
        
        // Remove tv from all domains
        for (int i = 0; i < hn && feasible; i++) {
            if (asgn[i] != -1) continue;
            if (testBit(domains[i].bits, tv)) {
                clearBit(domains[i].bits, tv);
                domains[i].count--;
                if (domains[i].count == 0) { feasible = false; break; }
            }
        }
        
        if (feasible) {
            // For each H-neighbor u of pv that is unassigned,
            // domain[u] must be subset of G-neighbors of tv
            for (int u : H.adj[pv]) {
                if (asgn[u] != -1) {
                    // Check edge exists
                    if (!G.adjSet[tv].count(asgn[u])) { feasible = false; break; }
                    continue;
                }
                // Intersect domain[u] with gadj[tv]
                int newcount = 0;
                for (int w = 0; w < words; w++) {
                    domains[u].bits[w] &= gadj[tv][w];
                    newcount += __builtin_popcountll(domains[u].bits[w]);
                }
                domains[u].count = newcount;
                if (newcount == 0) { feasible = false; break; }
            }
        }
        
        if (feasible) {
            total += solve(domains, asgn, depth+1);
        }
        
        // Restore
        domains = saved;
        asgn[pv] = -1;
        clearBit(usedBits, tv);
    }
    
    return total;
}

int main(int argc, char* argv[]) {
    ios::sync_with_stdio(false);
    
    H = readGraph(argv[1]);
    G = readGraph(argv[2]);
    hn = H.n;
    gn = G.n;
    words = (gn + 63) / 64;
    
    if (words > MAXG/64) {
        // Fallback: shouldn't happen for reasonable inputs
        words = MAXG/64;
    }
    
    // Build adjacency bitsets for G
    gadj.resize(gn);
    for (int v = 0; v < gn; v++) {
        gadj[v].fill(0);
        for (int u : G.adj[v]) setBit(gadj[v].data(), u);
    }
    
    // Initialize domains: candidate[i] = target vertices with matching label
    // and degree >= H.adj[i].size()
    vector<Domain> domains(hn);
    for (int i = 0; i < hn; i++) {
        domains[i].bits[0] = 0; // init
        for (int w = 0; w < words; w++) domains[i].bits[w] = 0;
        int hd = (int)H.adj[i].size();
        int hl = H.label[i];
        int cnt = 0;
        for (int j = 0; j < gn; j++) {
            if (G.label[j] == hl && (int)G.adj[j].size() >= hd) {
                setBit(domains[i].bits, j);
                cnt++;
            }
        }
        domains[i].count = cnt;
    }
    
    // Pairwise initial filtering: for each edge (u,v) in H,
    // candidate[u] must have a neighbor in candidate[v] and vice versa
    // Repeat until stable (arc consistency AC-3 style)
    bool changed = true;
    while (changed) {
        changed = false;
        for (int u = 0; u < hn; u++) {
            for (int v : H.adj[u]) {
                // For each candidate x of u, check that x has at least one neighbor in cand[v]
                for (int w = 0; w < words; w++) {
                    uint64_t b = domains[u].bits[w];
                    while (b) {
                        int bit = __builtin_ctzll(b);
                        int x = w*64 + bit;
                        b &= b-1;
                        if (x >= gn) continue;
                        // Does x have any neighbor in domains[v]?
                        bool has = false;
                        for (int ww = 0; ww < words && !has; ww++) {
                            if (gadj[x][ww] & domains[v].bits[ww]) has = true;
                        }
                        if (!has) {
                            clearBit(domains[u].bits, x);
                            domains[u].count--;
                            changed = true;
                        }
                    }
                }
            }
        }
    }
    
    // Check feasibility
    for (int i = 0; i < hn; i++) {
        if (domains[i].count == 0) { cout << 0 << "\n"; return 0; }
    }
    
    vector<int> asgn(hn, -1);
    memset(usedBits, 0, sizeof(usedBits));
    
    long long ans = solve(domains, asgn, 0);
    cout << ans << "\n";
    return 0;
}