// SubgraphIsomorphism - Glasgow-family solver for .lad / vertex-labelled LAD
// Build: g++ -std=c++17 -O3 -Wall -Wextra SubgraphIsomorphism_CLAUDE_lad.cpp -o si_lad

#include <algorithm>
#include <chrono>
#include <cctype>
#include <climits>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
using namespace std;

// ─── types ───────────────────────────────────────────────────────────────────
using NodeLabel = int32_t;
static constexpr NodeLabel NO_LABEL = -1;

struct Graph {
    int n = 0;
    bool directed = false;
    vector<NodeLabel> vlabel;
    // adjacency lists (undirected: both directions stored)
    vector<vector<int>> adj;
    vector<int> deg;
    // bitset adjacency
    int words = 0;
    vector<vector<uint64_t>> adjBit;
    bool allSameLabel = true;

    void init(int _n, bool dir = false) {
        n = _n; directed = dir;
        vlabel.assign(n, NO_LABEL);
        adj.resize(n); deg.assign(n, 0);
    }
    void addEdge(int u, int v) {
        adj[u].push_back(v);
        deg[u]++;
        if (!directed) {
            adj[v].push_back(u);
            deg[v]++;
        }
    }
    void buildBits() {
        words = (n + 63) / 64;
        adjBit.assign(n, vector<uint64_t>(words, 0));
        for (int u = 0; u < n; u++)
            for (int v : adj[u])
                adjBit[u][v>>6] |= 1ULL << (v&63);
    }
    inline bool hasEdge(int u, int v) const {
        return (adjBit[u][v>>6] >> (v&63)) & 1;
    }
    // AND two bitsets, return popcount
    int andCount(int u, int v) const {
        int c = 0;
        for (int w = 0; w < words; w++) c += __builtin_popcountll(adjBit[u][w] & adjBit[v][w]);
        return c;
    }
};

// ─── LAD parser ──────────────────────────────────────────────────────────────
// Standard LAD format:
//   Line 1: n (number of nodes)
//   For each node i (0..n-1): degree d, then d neighbours
//   Optional vertex labels: after edge section, "labels" keyword or just integers
//
// Vertex-labelled LAD variant used in this project:
//   Same edge section, then one label per node on subsequent lines OR
//   first line: n l (n nodes, labelled flag=l)
//   then node lines: d nb1 nb2 ... [optional label at end or separate section]

static Graph parseLAD(const string& path, bool& isDirected) {
    ifstream f(path);
    if (!f) { cerr << "Cannot open: " << path << "\n"; exit(1); }

    // Collect all tokens (skip # comments)
    vector<int> nums;
    string line;
    bool hasNonNumeric = false;
    while (getline(f, line)) {
        if (!line.empty() && line[0] == '#') continue;
        istringstream ss(line);
        string tok;
        while (ss >> tok) {
            // check if numeric (possibly negative)
            bool isNum = !tok.empty();
            size_t start = (tok[0]=='-'||tok[0]=='+') ? 1 : 0;
            for (size_t k = start; k < tok.size(); k++)
                if (!isdigit((unsigned char)tok[k])) { isNum = false; break; }
            if (isNum) nums.push_back(stoi(tok));
            else hasNonNumeric = true;
        }
    }
    (void)hasNonNumeric;

    isDirected = false;
    size_t pos = 0;
    auto nextInt = [&]() -> int {
        if (pos >= nums.size()) return -1;
        return nums[pos++];
    };
    auto peekInt = [&]() -> int {
        return pos < nums.size() ? nums[pos] : -1;
    };

    int n = nextInt();
    if (n <= 0) { cerr << "Bad node count in LAD file\n"; exit(1); }

    // Check if second value looks like a "labelled" flag (0 or 1) vs node 0's degree
    // Heuristic: if second token is 0 or 1 AND then we'd parse n adjacency lists consistently
    // We just proceed: read n adjacency lines
    Graph g; g.init(n, false);

    // Try to detect directed flag: some LAD variants have "n directed" header
    // If next value is 0 or 1 and overall token count suggests it:
    if (peekInt() == 0 || peekInt() == 1) {
        // could be directed flag - try both interpretations
        // simple heuristic: if value is 0 or 1, treat as directed flag only if
        // remaining tokens would be consistent with n adjacency lines
        // For safety, just check if it's 0/1 and value seems too small to be a degree
        int maybe = nextInt(); // consume
        if (maybe == 1) isDirected = true;
        g.directed = isDirected;
    }

    // Read adjacency lists
    vector<pair<int,int>> edges;
    for (int u = 0; u < n; u++) {
        int d = nextInt();
        if (d < 0) break;
        for (int j = 0; j < d; j++) {
            int v = nextInt();
            if (v < 0 || v >= n) continue;
            if (isDirected) {
                edges.push_back({u, v});
            } else {
                if (u < v) edges.push_back({u, v}); // dedup undirected
            }
        }
    }
    for (auto [u,v] : edges) g.addEdge(u, v);

    // Read optional vertex labels
    // remaining tokens are labels (one per node) if count >= n
    if ((int)(nums.size() - pos) >= n) {
        for (int i = 0; i < n; i++) g.vlabel[i] = nextInt();
    }

    // detect uniform labels
    g.allSameLabel = true;
    for (int i = 1; i < n; i++)
        if (g.vlabel[i] != g.vlabel[0]) { g.allSameLabel = false; break; }

    g.buildBits();
    return g;
}

// ─── solver ──────────────────────────────────────────────────────────────────
// Glasgow-inspired: AllDifferent + neighbourhood filtering on candidate sets

struct Solver {
    const Graph& P;
    const Graph& T;
    bool induced;
    uint64_t limit;
    bool printMappings;

    uint64_t count = 0;
    int Pn, Tn, tWords;

    // cands[p] = bitset of feasible target nodes for pattern node p
    vector<vector<uint64_t>> cands;
    // mapping
    vector<int> mapping;
    vector<bool> usedT;

    // variable ordering
    vector<int> order;

    // solutions
    vector<vector<int>> solutions;

    Solver(const Graph& p, const Graph& t, bool ind, uint64_t lim, bool pm)
        : P(p), T(t), induced(ind), limit(lim), printMappings(pm),
          Pn(p.n), Tn(t.n), tWords((t.n+63)/64),
          cands(p.n, vector<uint64_t>((t.n+63)/64, 0)),
          mapping(p.n, -1), usedT(t.n, false),
          order(p.n)
    {}

    bool initCands() {
        for (int p = 0; p < Pn; p++) {
            bool any = false;
            for (int t = 0; t < Tn; t++) {
                // label check
                if (!P.allSameLabel && P.vlabel[p] != NO_LABEL &&
                    P.vlabel[p] != T.vlabel[t]) continue;
                // degree check
                if (T.deg[t] < P.deg[p]) continue;
                // neighbourhood label check: for each label l in P.neighbours[p],
                // T.neighbours[t] must have enough nodes with that label
                // (fast: just degree if all same label)
                cands[p][t>>6] |= 1ULL << (t&63);
                any = true;
            }
            if (!any) return false;
        }
        return true;
    }

    // Neighbourhood consistency filter (arc-consistency style, one pass)
    // For each (p, t) in cands[p]: for each neighbour pNb of p,
    //   there must exist a neighbour tNb of t in cands[pNb]
    bool filterCands() {
        bool changed = true;
        while (changed) {
            changed = false;
            for (int p = 0; p < Pn; p++) {
                for (int w = 0; w < tWords; w++) {
                    uint64_t bits = cands[p][w];
                    while (bits) {
                        int bit = __builtin_ctzll(bits);
                        bits &= bits-1;
                        int t = w*64 + bit;
                        // check each pattern neighbour
                        bool ok = true;
                        for (int pNb : P.adj[p]) {
                            // is there any tNb in cands[pNb] that is adjacent to t?
                            bool found = false;
                            for (int ww = 0; ww < tWords && !found; ww++) {
                                uint64_t nb = cands[pNb][ww] & T.adjBit[t][ww];
                                if (nb) found = true;
                            }
                            if (!found) { ok = false; break; }
                        }
                        if (!ok) {
                            cands[p][w>>0] &= ~(1ULL << bit); // clear this candidate
                            // w is already the word index, bit is the bit
                            cands[p][w] &= ~(1ULL << bit);
                            changed = true;
                            if (candCount(p) == 0) return false;
                        }
                    }
                }
            }
        }
        return true;
    }

    int candCount(int p) const {
        int c = 0;
        for (int w = 0; w < tWords; w++) c += __builtin_popcountll(cands[p][w]);
        return c;
    }

    // Build order: MRV (smallest domain first), then most-constrained by already-ordered neighbours
    void buildOrder() {
        vector<bool> inOrder(Pn, false);
        // start with minimum domain
        int first = 0; int bestC = INT_MAX;
        for (int p = 0; p < Pn; p++) {
            int c = candCount(p);
            if (c < bestC) { bestC = c; first = p; }
        }
        order[0] = first; inOrder[first] = true;
        for (int i = 1; i < Pn; i++) {
            int chosen = -1; int bestScore = INT_MAX;
            for (int p = 0; p < Pn; p++) {
                if (inOrder[p]) continue;
                int conn = 0;
                for (int nb : P.adj[p]) if (inOrder[nb]) conn++;
                // MRV with connectivity tie-breaking
                int score = candCount(p) * 1000 - conn;
                if (chosen < 0 || score < bestScore) { bestScore = score; chosen = p; }
            }
            order[i] = chosen; inOrder[chosen] = true;
        }
    }

    bool isConsistent(int pNode, int tNode) {
        // check all already-mapped pattern neighbours
        for (int pNb : P.adj[pNode]) {
            if (mapping[pNb] < 0) continue;
            int tNb = mapping[pNb];
            if (P.directed) {
                // check direction: if pNode->pNb in P, need tNode->tNb in T
                if (P.hasEdge(pNode, pNb) && !T.hasEdge(tNode, tNb)) return false;
                if (P.hasEdge(pNb, pNode) && !T.hasEdge(tNb, tNode)) return false;
            } else {
                if (!T.hasEdge(tNode, tNb)) return false;
            }
        }
        if (induced) {
            for (int pi = 0; pi < Pn; pi++) {
                if (mapping[pi] < 0 || pi == pNode) continue;
                int tMapped = mapping[pi];
                if (!P.hasEdge(pNode, pi) && T.hasEdge(tNode, tMapped)) return false;
                if (!P.directed) continue;
                if (!P.hasEdge(pi, pNode) && T.hasEdge(tMapped, tNode)) return false;
            }
        }
        return true;
    }

    // Forward checking: update cands for unassigned nodes given new assignment pNode=tNode
    // Returns false if any domain becomes empty
    // Saves domains for restoration
    bool forwardCheck(int depth, int pNode, int tNode,
                      vector<pair<int,vector<uint64_t>>>& saved) {
        for (int pNb : P.adj[pNode]) {
            if (mapping[pNb] >= 0) continue;
            // tNode must be in T-neighbourhood of candidates
            auto old = cands[pNb];
            // intersect cands[pNb] with T.adjBit[tNode]
            bool any = false;
            for (int w = 0; w < tWords; w++) {
                cands[pNb][w] &= T.adjBit[tNode][w];
                // also remove tNode itself (injective)
                if ((w == (tNode>>6))) cands[pNb][w] &= ~(1ULL<<(tNode&63));
                if (cands[pNb][w]) any = true;
            }
            if (!any) {
                // restore what we've changed so far
                cands[pNb] = old;
                return false;
            }
            saved.push_back({pNb, old});
        }
        // remove tNode from ALL unassigned cands (injectivity)
        for (int p = 0; p < Pn; p++) {
            if (mapping[p] >= 0 || p == pNode) continue;
            if (!((cands[p][tNode>>6] >> (tNode&63)) & 1)) continue;
            saved.push_back({p, cands[p]});
            cands[p][tNode>>6] &= ~(1ULL<<(tNode&63));
            if (candCount(p) == 0) return false;
        }
        (void)depth;
        return true;
    }

    void solve(int depth) {
        if (count >= limit) return;
        if (depth == Pn) {
            count++;
            if (printMappings) solutions.push_back(mapping);
            return;
        }
        int pNode = order[depth];

        for (int w = 0; w < tWords; w++) {
            uint64_t bits = cands[pNode][w];
            while (bits) {
                int bit = __builtin_ctzll(bits);
                bits &= bits-1;
                int tNode = w*64 + bit;
                if (usedT[tNode]) continue;
                if (!isConsistent(pNode, tNode)) continue;

                mapping[pNode] = tNode;
                usedT[tNode] = true;

                vector<pair<int,vector<uint64_t>>> saved;
                bool ok = forwardCheck(depth, pNode, tNode, saved);
                if (ok) solve(depth+1);

                // restore
                for (auto& [p, old] : saved) cands[p] = move(old);
                usedT[tNode] = false;
                mapping[pNode] = -1;
                if (count >= limit) return;
            }
        }
    }

    uint64_t run() {
        if (!initCands()) return 0;
        // one-shot arc consistency
        if (!filterCands()) return 0;
        buildOrder();
        solve(0);
        return count;
    }
};

// ─── main ─────────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    bool induced = false;
    bool firstOnly = false;
    bool printMappings = false;
    uint64_t limit = UINT64_MAX;
    string patFile, tgtFile;

    for (int i = 1; i < argc; i++) {
        string a = argv[i];
        if (a == "--non-induced") induced = false;
        else if (a == "--induced") induced = true;
        else if (a == "--first-only" || a == "-F") { firstOnly = true; limit = 1; }
        else if (a == "--print-mappings") printMappings = true;
        else if (a == "--solution-limit") {
            if (++i >= argc) { cerr << "Missing value for --solution-limit\n"; return 1; }
            limit = stoull(argv[i]);
        }
        else if (patFile.empty()) patFile = a;
        else if (tgtFile.empty()) tgtFile = a;
        else { cerr << "Unexpected argument: " << a << "\n"; return 1; }
    }
    if (patFile.empty() || tgtFile.empty()) {
        cerr << "Usage: si_lad [--non-induced|--induced] [--first-only|-F] "
                "[--print-mappings] [--solution-limit N] <pattern.lad> <target.lad>\n";
        return 1;
    }
    (void)firstOnly; // limit=1 achieves the same effect

    auto t0 = chrono::high_resolution_clock::now();

    bool patDir = false, tgtDir = false;
    Graph P = parseLAD(patFile, patDir);
    Graph T = parseLAD(tgtFile, tgtDir);
    // if either is directed, treat both as directed
    if (patDir || tgtDir) { P.directed = true; T.directed = true; }

    Solver solver(P, T, induced, limit, printMappings);
    uint64_t cnt = solver.run();

    auto t1 = chrono::high_resolution_clock::now();
    double ms = chrono::duration<double,milli>(t1-t0).count();

    cout << cnt << "\n";
    cout << "solution_count=" << cnt << "\n";
    if (printMappings) {
        for (auto& m : solver.solutions) {
            cout << "Mapping:";
            for (int p = 0; p < P.n; p++)
                cout << " (" << p << " -> " << m[p] << ")";
            cout << "\n";
        }
    }
    cout << fixed << setprecision(3) << "runtime_ms=" << ms << "\n";
    return 0;
}
