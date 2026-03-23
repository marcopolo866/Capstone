// SubgraphIsomorphism - VF3-family solver for .vf/.grf (directed, labelled)
// Build: g++ -std=c++17 -O3 -Wall -Wextra SubgraphIsomorphism_CLAUDE_grf.cpp -o si_grf

#include <algorithm>
#include <chrono>
#include <cctype>
#include <climits>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
using namespace std;

// ─── types ───────────────────────────────────────────────────────────────────
using NodeLabel = int32_t;
using EdgeLabel = int32_t;
static constexpr NodeLabel ANY_LABEL = -1;

struct Graph {
    int n = 0;
    vector<NodeLabel> vlabel;
    // adjacency: adj[u] = list of {v, elabel}
    vector<vector<pair<int,EdgeLabel>>> out, in;
    // fast bit-adjacency (directed: out-neighbour set)
    vector<vector<uint64_t>> outBit, inBit;
    // out-degree, in-degree
    vector<int> outdeg, indeg;

    bool allSameVLabel = true;
    bool allSameELabel = true;

    void init(int _n) {
        n = _n;
        vlabel.assign(n, ANY_LABEL);
        out.resize(n); in.resize(n);
        outdeg.assign(n,0); indeg.assign(n,0);
    }
    void addEdge(int u, int v, EdgeLabel el = 0) {
        out[u].push_back({v, el});
        in[v].push_back({u, el});
        outdeg[u]++; indeg[v]++;
    }
    void buildBits() {
        int words = (n + 63) / 64;
        outBit.assign(n, vector<uint64_t>(words,0));
        inBit.assign(n,  vector<uint64_t>(words,0));
        for (int u = 0; u < n; u++)
            for (auto [v,_] : out[u]) {
                outBit[u][v>>6] |= 1ULL<<(v&63);
                inBit[v][u>>6]  |= 1ULL<<(u&63);
            }
    }
    inline bool hasOutEdge(int u, int v) const {
        return (outBit[u][v>>6] >> (v&63)) & 1;
    }
    inline bool hasInEdge(int u, int v) const {
        return (inBit[u][v>>6] >> (v&63)) & 1;
    }
    // get edge label for directed edge u->v (-1 if not exist)
    EdgeLabel getEdgeLabel(int u, int v) const {
        if (!hasOutEdge(u,v)) return -1;
        for (auto [nb,el] : out[u]) if (nb==v) return el;
        return -1;
    }
};

// ─── parsers ─────────────────────────────────────────────────────────────────

// Skip whitespace / comments (lines starting with #)
static void skipWS(istream& s) {
    while (!s.eof()) {
        char c = s.peek();
        if (c == '#') { string line; getline(s,line); }
        else if (isspace((unsigned char)c)) s.get();
        else break;
    }
}

// .grf / .vf format:
//   Line 1: <num_nodes>
//   For each node: node_id [label]
//   Then edges: <u> <v> [edge_label]
// Real-world files are sometimes messy; we do a two-pass approach.

static Graph parseGRF(const string& path) {
    ifstream f(path);
    if (!f) { cerr << "Cannot open: " << path << "\n"; exit(1); }

    // Slurp all tokens
    vector<string> tokens;
    string tok;
    while (f >> tok) {
        if (tok[0] == '#') { string line; getline(f,line); continue; }
        tokens.push_back(tok);
    }

    size_t pos = 0;
    auto nextInt = [&]() -> int {
        if (pos >= tokens.size()) return -1;
        return stoi(tokens[pos++]);
    };
    auto peekStr = [&]() -> string {
        return pos < tokens.size() ? tokens[pos] : "";
    };
    auto isNum = [](const string& s) -> bool {
        if (s.empty()) return false;
        size_t i = (s[0]=='-'||s[0]=='+') ? 1 : 0;
        for (; i<s.size(); i++) if (!isdigit((unsigned char)s[i])) return false;
        return true;
    };

    int n = nextInt();
    if (n <= 0) { cerr << "Bad node count\n"; exit(1); }
    Graph g; g.init(n);

    // read node labels (optional: if next token is non-numeric it might be a label)
    for (int i = 0; i < n; i++) {
        if (isNum(peekStr())) {
            int id = nextInt();
            (void)id;
            // optional label after id
            if (!isNum(peekStr()) && !peekStr().empty()) {
                g.vlabel[i] = (NodeLabel)hash<string>{}(tokens[pos++]);
            } else if (isNum(peekStr())) {
                // could be label as integer
                // heuristic: if value looks like a label (not a node id), store it
                g.vlabel[i] = nextInt();
            }
        } else {
            // label only
            g.vlabel[i] = (NodeLabel)hash<string>{}(tokens[pos++]);
        }
    }

    // read edge count if present
    int eCount = -1;
    if (isNum(peekStr())) {
        // might be edge count or first edge u
        // peek further: if we see a pair of node ids, no separate edge count
        // We'll just try to parse edge-count then edges
        size_t saved = pos;
        int maybe = nextInt();
        if (isNum(peekStr())) {
            int nxt = stoi(tokens[pos]);
            if (nxt >= 0 && nxt < n) {
                // looks like first edge already
                pos = saved;
                eCount = -1;
            } else {
                eCount = maybe;
            }
        } else {
            pos = saved;
        }
    }

    // read edges
    int edgesRead = 0;
    while (pos < tokens.size()) {
        if (!isNum(tokens[pos])) { pos++; continue; }
        int u = nextInt();
        if (pos >= tokens.size() || !isNum(tokens[pos])) break;
        int v = nextInt();
        if (u < 0 || u >= n || v < 0 || v >= n) break;
        EdgeLabel el = 0;
        if (isNum(peekStr())) el = nextInt();
        g.addEdge(u, v, el);
        edgesRead++;
        if (eCount > 0 && edgesRead >= eCount) break;
    }

    // detect uniform labels
    g.allSameVLabel = true;
    for (int i = 1; i < n; i++)
        if (g.vlabel[i] != g.vlabel[0]) { g.allSameVLabel = false; break; }
    g.allSameELabel = true;
    for (int u = 0; u < n && g.allSameELabel; u++)
        for (auto [v,el] : g.out[u])
            if (el != g.out[0].empty() ? 0 : el) { g.allSameELabel = false; break; }

    g.buildBits();
    return g;
}

// ─── solver ──────────────────────────────────────────────────────────────────

struct Solver {
    const Graph& P;   // pattern
    const Graph& T;   // target
    bool induced;
    bool firstOnly;
    bool printMappings;
    uint64_t limit;

    uint64_t count = 0;
    vector<int> mapping;   // mapping[p] = t
    vector<bool> usedT;

    // candidate sets: cands[p] = bitset over target nodes
    int tWords;
    vector<vector<uint64_t>> cands;

    // ordering
    vector<int> order;       // order[i] = p-node to assign at depth i
    vector<int> orderPos;    // orderPos[p] = depth

    // stored mappings
    vector<vector<int>> solutions;

    Solver(const Graph& p, const Graph& t, bool ind, bool fst, bool pm, uint64_t lim)
        : P(p), T(t), induced(ind), firstOnly(fst), printMappings(pm), limit(lim),
          mapping(p.n, -1), usedT(t.n, false),
          tWords((t.n+63)/64), cands(p.n, vector<uint64_t>((t.n+63)/64, 0)),
          order(p.n), orderPos(p.n)
    {}

    // Initial candidate filter: label match + degree constraints
    bool initCands() {
        for (int p = 0; p < P.n; p++) {
            bool any = false;
            for (int t = 0; t < T.n; t++) {
                if (!P.allSameVLabel && P.vlabel[p] != ANY_LABEL &&
                    P.vlabel[p] != T.vlabel[t]) continue;
                if (T.outdeg[t] < P.outdeg[p]) continue;
                if (T.indeg[t]  < P.indeg[p])  continue;
                cands[p][t>>6] |= 1ULL<<(t&63);
                any = true;
            }
            if (!any) return false;
        }
        return true;
    }

    // Count bits in a candidate set
    int candCount(int p) {
        int cnt = 0;
        for (int w = 0; w < tWords; w++) cnt += __builtin_popcountll(cands[p][w]);
        return cnt;
    }

    // Build variable ordering: static MRV on initial cands, connectivity bias
    void buildOrder() {
        vector<bool> inOrder(P.n, false);
        // pick node with smallest cand set first
        int first = 0;
        int best = INT_MAX;
        for (int p = 0; p < P.n; p++) {
            int c = candCount(p);
            if (c < best) { best = c; first = p; }
        }
        order[0] = first; inOrder[first] = true; orderPos[first] = 0;
        for (int i = 1; i < P.n; i++) {
            int chosen = -1; int bestScore = INT_MAX;
            for (int p = 0; p < P.n; p++) {
                if (inOrder[p]) continue;
                // count already-ordered neighbours (connectivity)
                int conn = 0;
                for (auto [nb,_] : P.out[p]) if (inOrder[nb]) conn++;
                for (auto [nb,_] : P.in[p])  if (inOrder[nb]) conn++;
                int score = candCount(p) - conn * 1000; // prefer connected, small cands
                if (chosen < 0 || score < bestScore) { bestScore = score; chosen = p; }
            }
            order[i] = chosen; inOrder[chosen] = true; orderPos[chosen] = i;
        }
    }

    // Check if assigning mapping[pNode]=tNode is consistent with current partial mapping
    bool isConsistent(int pNode, int tNode) {
        // For each already-mapped pattern neighbour, check edges
        for (auto [pNb, el] : P.out[pNode]) {
            if (mapping[pNb] < 0) continue;
            int tNb = mapping[pNb];
            if (!T.hasOutEdge(tNode, tNb)) return false;
            if (!P.allSameELabel && el != ANY_LABEL) {
                if (T.getEdgeLabel(tNode, tNb) != el) return false;
            }
        }
        for (auto [pNb, el] : P.in[pNode]) {
            if (mapping[pNb] < 0) continue;
            int tNb = mapping[pNb];
            if (!T.hasOutEdge(tNb, tNode)) return false;
            if (!P.allSameELabel && el != ANY_LABEL) {
                if (T.getEdgeLabel(tNb, tNode) != el) return false;
            }
        }
        if (induced) {
            // non-edges: for mapped neighbours NOT in P.out[pNode], ensure no edge exists
            for (int pi = 0; pi < P.n; pi++) {
                if (mapping[pi] < 0 || pi == pNode) continue;
                int tMapped = mapping[pi];
                // check pNode->pi direction
                if (!P.hasOutEdge(pNode, pi)) {
                    if (T.hasOutEdge(tNode, tMapped)) return false;
                }
                if (!P.hasOutEdge(pi, pNode)) {
                    if (T.hasOutEdge(tMapped, tNode)) return false;
                }
            }
        }
        return true;
    }

    void solve(int depth) {
        if (count >= limit) return;
        if (depth == P.n) {
            count++;
            if (printMappings) solutions.push_back(mapping);
            return;
        }
        int pNode = order[depth];

        // iterate candidates
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
                solve(depth+1);
                usedT[tNode] = false;
                mapping[pNode] = -1;
                if (count >= limit) return;
            }
        }
    }

    uint64_t run() {
        if (!initCands()) return 0;
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
        cerr << "Usage: si_grf [--non-induced|--induced] [--first-only|-F] "
                "[--print-mappings] [--solution-limit N] <pattern> <target>\n";
        return 1;
    }

    auto t0 = chrono::high_resolution_clock::now();

    Graph P = parseGRF(patFile);
    Graph T = parseGRF(tgtFile);

    Solver solver(P, T, induced, firstOnly, printMappings, limit);
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
