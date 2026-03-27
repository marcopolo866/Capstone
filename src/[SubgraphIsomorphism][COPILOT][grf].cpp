// src/[SubgraphIsomorphism][COPILOT][grf].cpp
// Compile: g++ -std=c++17 -O3 -Wall -Wextra src/[SubgraphIsomorphism][COPILOT][grf].cpp -o src/vf3_copilot

#include <bits/stdc++.h>
using namespace std;
using u64 = uint64_t;
using u32 = uint32_t;
using i64 = long long;

static void usage(const char* prog) {
    cerr << "Usage: " << prog << " [--non-induced|--noninduced] [--first-only|-F] <pattern_file> <target_file>\n";
    cerr << "       " << prog << " <pattern_file> <target_file>\n";
    cerr << "Accepts --induced (treated as non-induced for compatibility).\n";
}

struct Graph {
    int n = 0;
    vector<int> label; // integer labels
    vector<vector<int>> adj;
    vector<int> deg;
    vector<u64> adjbit_flat; // adjacency bitsets flattened per vertex (size = n * words)
    int words = 0;
    void init_bits() {
        words = (n + 63) >> 6;
        adjbit_flat.assign((size_t)n * words, 0);
        for (int u = 0; u < n; ++u) {
            for (int v : adj[u]) {
                int w = v >> 6;
                int b = v & 63;
                adjbit_flat[(size_t)u * words + w] |= (u64)1 << b;
            }
        }
    }
    inline bool adjacent(int u, int v) const {
        if (u < 0 || v < 0 || u >= n || v >= n) return false;
        int w = v >> 6;
        int b = v & 63;
        return (adjbit_flat[(size_t)u * words + w] >> b) & 1ULL;
    }
    // popcount of intersection between u's neighbors and bitset (bitset is words long)
    inline int neigh_intersect_count_with_bitset(int u, const u64* bitset) const {
        int cnt = 0;
        const u64* row = &adjbit_flat[(size_t)u * words];
        for (int i = 0; i < words; ++i) {
            cnt += __builtin_popcountll(row[i] & bitset[i]);
        }
        return cnt;
    }
};

static bool parse_graph_file(const string& path, Graph& G) {
    ifstream in(path);
    if (!in) return false;
    string line;
    // read first non-empty line as n
    int n = -1;
    while (getline(in, line)) {
        // trim
        bool allws = true;
        for (char c : line) if (!isspace((unsigned char)c)) { allws = false; break; }
        if (allws) continue;
        stringstream ss(line);
        if (!(ss >> n)) return false;
        break;
    }
    if (n < 0) return false;
    G.n = n;
    G.label.assign(n, 0);
    G.adj.assign(n, {});
    G.deg.assign(n, 0);
    // Next n lines: vertex metadata containing at least id and label (robust)
    // We'll read lines until we've parsed n vertex label entries.
    unordered_map<string,int> labelmap;
    int next_label_id = 1;
    int parsed = 0;
    while (parsed < n && getline(in, line)) {
        // skip blank lines
        bool allws = true;
        for (char c : line) if (!isspace((unsigned char)c)) { allws = false; break; }
        if (allws) continue;
        // tokenize
        stringstream ss(line);
        vector<string> toks;
        string t;
        while (ss >> t) toks.push_back(t);
        if (toks.empty()) continue;
        // first token likely id; find first token that is not the id (second token) as label
        string labstr;
        if (toks.size() >= 2) {
            labstr = toks[1];
        } else {
            // if only one token, maybe label on next token line; try to read next non-empty token
            if (!(in >> labstr)) labstr = "0";
            string rest;
            getline(in, rest);
        }
        // remove possible "label=" prefix or "l=" etc
        size_t pos = string::npos;
        if ((pos = labstr.find('=')) != string::npos) labstr = labstr.substr(pos+1);
        // map label string to int
        int lid;
        auto it = labelmap.find(labstr);
        if (it == labelmap.end()) {
            lid = next_label_id++;
            labelmap.emplace(labstr, lid);
        } else lid = it->second;
        G.label[parsed] = lid;
        ++parsed;
    }
    if (parsed != n) return false;
    // Now for each vertex: a line with edge count, followed by that many edge lines (u v style)
    // We'll read until we've filled adjacency for all vertices.
    int v_idx = 0;
    while (v_idx < n && getline(in, line)) {
        // skip blanks
        bool allws = true;
        for (char c : line) if (!isspace((unsigned char)c)) { allws = false; break; }
        if (allws) continue;
        stringstream ss(line);
        int ec = -1;
        if (!(ss >> ec)) {
            // maybe line contains "degree: X" or other tokens; try to extract first integer
            ss.clear();
            ss.str(line);
            string tok;
            while (ss >> tok) {
                bool isnum = true;
                for (char ch : tok) if (!isdigit((unsigned char)ch) && ch!='-') { isnum = false; break; }
                if (isnum) { ec = stoi(tok); break; }
            }
            if (ec < 0) return false;
        }
        // read ec edge lines
        int read = 0;
        while (read < ec && getline(in, line)) {
            bool allws2 = true;
            for (char c : line) if (!isspace((unsigned char)c)) { allws2 = false; break; }
            if (allws2) continue;
            stringstream es(line);
            int a=-1,b=-1;
            if (!(es >> a >> b)) {
                // try to parse first two integers in line
                es.clear();
                es.str(line);
                string tok;
                vector<int> ints;
                while (es >> tok) {
                    bool isnum = true;
                    for (char ch : tok) if (!isdigit((unsigned char)ch) && ch!='-') { isnum = false; break; }
                    if (isnum) ints.push_back(stoi(tok));
                    if (ints.size()>=2) break;
                }
                if (ints.size()>=2) { a = ints[0]; b = ints[1]; }
                else continue;
            }
            // add edge; some files may list global u v; we only add if a==v_idx or a is arbitrary?
            // The format says "then for each vertex: a line with edge count, followed by that many edge lines (u v style)"
            // We'll accept edges where a==v_idx or where either endpoint equals v_idx; otherwise still add if within range.
            if (a >= 0 && a < n && b >= 0 && b < n) {
                G.adj[a].push_back(b);
                if (a != b) G.adj[b].push_back(a);
            }
            ++read;
        }
        ++v_idx;
    }
    // Normalize adjacency: remove duplicates
    for (int i = 0; i < n; ++i) {
        auto &v = G.adj[i];
        sort(v.begin(), v.end());
        v.erase(unique(v.begin(), v.end()), v.end());
        G.deg[i] = (int)v.size();
    }
    G.init_bits();
    return true;
}

struct Solver {
    const Graph *P;
    const Graph *T;
    int pn, tn;
    bool first_only = false;
    i64 solutions = 0;
    vector<vector<int>> domains; // candidate lists per pattern vertex
    vector<vector<u64>> domain_bits; // bitset per pattern vertex
    int words = 0;
    vector<int> order; // variable ordering: pattern vertex indices
    vector<int> inv_order; // inverse mapping from position to pattern vertex
    vector<int> map_p2t; // mapping pattern->target, -1 if unmapped
    vector<int> map_t2p; // mapping target->pattern, -1 if unused
    vector<u64> used_bits; // bitset of used target vertices
    // scratch for recursion: none allocated per recursion
    Solver(const Graph* p, const Graph* t, bool firstOnly): P(p), T(t), first_only(firstOnly) {
        pn = P->n; tn = T->n;
        words = (tn + 63) >> 6;
        domains.assign(pn, {});
        domain_bits.assign(pn, vector<u64>(words,0));
        order.resize(pn);
        inv_order.resize(pn);
        map_p2t.assign(pn, -1);
        map_t2p.assign(tn, -1);
        used_bits.assign(words, 0);
    }

    void build_initial_domains() {
        // For each pattern vertex u, candidate v in target if label matches and deg(v) >= deg(u)
        for (int u = 0; u < pn; ++u) {
            domains[u].clear();
            fill(domain_bits[u].begin(), domain_bits[u].end(), 0);
            for (int v = 0; v < tn; ++v) {
                if (P->label[u] != T->label[v]) continue;
                if (T->deg[v] < P->deg[u]) continue;
                domains[u].push_back(v);
                int w = v >> 6; int b = v & 63;
                domain_bits[u][w] |= (u64)1 << b;
            }
        }
    }

    void compute_ordering() {
        // MRV: sort pattern vertices by domain size ascending, tie-break by degree descending
        vector<int> idx(pn);
        for (int i = 0; i < pn; ++i) idx[i] = i;
        sort(idx.begin(), idx.end(), [&](int a, int b){
            int sa = (int)domains[a].size();
            int sb = (int)domains[b].size();
            if (sa != sb) return sa < sb;
            if (P->deg[a] != P->deg[b]) return P->deg[a] > P->deg[b];
            return a < b;
        });
        for (int i = 0; i < pn; ++i) {
            order[i] = idx[i];
            inv_order[idx[i]] = i;
        }
    }

    inline bool is_used(int v) const {
        int w = v >> 6; int b = v & 63;
        return (used_bits[w] >> b) & 1ULL;
    }
    inline void set_used(int v) {
        int w = v >> 6; int b = v & 63;
        used_bits[w] |= (u64)1 << b;
    }
    inline void clear_used(int v) {
        int w = v >> 6; int b = v & 63;
        used_bits[w] &= ~((u64)1 << b);
    }

    bool consistent(int pu, int tv) {
        // For each neighbor pnbr of pu that is already mapped, check adjacency between tv and mapped target
        for (int pnbr : P->adj[pu]) {
            int mapped = map_p2t[pnbr];
            if (mapped == -1) continue;
            if (!T->adjacent(tv, mapped)) return false;
        }
        return true;
    }

    bool forward_check_candidate(int pu, int tv) {
        // For each unmapped neighbor pnbr of pu, ensure there exists at least one candidate in its domain
        // that is neighbor of tv and not used.
        const u64* tv_row = &T->adjbit_flat[(size_t)tv * T->words];
        for (int pnbr : P->adj[pu]) {
            if (map_p2t[pnbr] != -1) continue;
            // domain_bits[pnbr] & tv_row & ~used_bits must be non-empty
            int cnt = 0;
            for (int w = 0; w < words; ++w) {
                u64 bits = domain_bits[pnbr][w] & tv_row[w] & ~used_bits[w];
                if (bits) { cnt = 1; break; }
            }
            if (!cnt) return false;
        }
        return true;
    }

    void search_rec(int depth) {
        if (depth == pn) {
            ++solutions;
            if (first_only && solutions >= 1) return;
            return;
        }
        int pu = order[depth];
        // iterate candidates in deterministic order
        const vector<int>& candlist = domains[pu];
        for (int v : candlist) {
            if (is_used(v)) continue;
            if (!consistent(pu, v)) continue;
            // quick forward-check
            set_used(v);
            map_p2t[pu] = v;
            map_t2p[v] = pu;
            bool ok = forward_check_candidate(pu, v);
            if (ok) {
                search_rec(depth + 1);
                if (first_only && solutions >= 1) {
                    // unwind
                    map_p2t[pu] = -1;
                    map_t2p[v] = -1;
                    clear_used(v);
                    return;
                }
            }
            map_p2t[pu] = -1;
            map_t2p[v] = -1;
            clear_used(v);
        }
    }

    i64 solve() {
        build_initial_domains();
        // if any domain empty -> zero
        for (int u = 0; u < pn; ++u) {
            if (domains[u].empty()) return 0;
        }
        compute_ordering();
        // initial forward-check: ensure for each pattern edge (u,w) there exists at least one target edge between domains
        // (lightweight)
        for (int u = 0; u < pn; ++u) {
            for (int w : P->adj[u]) {
                if (u >= w) continue;
                // check existence of v in domain[u] and x in domain[w] with adjacency
                bool found = false;
                for (int v : domains[u]) {
                    const u64* row = &T->adjbit_flat[(size_t)v * T->words];
                    for (int x : domains[w]) {
                        int word = x >> 6; int bit = x & 63;
                        if ((row[word] >> bit) & 1ULL) { found = true; break; }
                    }
                    if (found) break;
                }
                if (!found) return 0;
            }
        }
        // start recursion
        search_rec(0);
        return solutions;
    }
};

int main(int argc, char** argv) {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    if (argc < 3) {
        usage(argv[0]);
        return 1;
    }
    bool first_only = false;
    bool non_induced = false;
    vector<string> files;
    for (int i = 1; i < argc; ++i) {
        string s = argv[i];
        if (s == "--first-only" || s == "-F" || s == "--firstonly" || s == "--first") {
            first_only = true;
        } else if (s == "--non-induced" || s == "--noninduced" || s == "--non-induced" ) {
            non_induced = true;
        } else if (s == "--noninduced") {
            non_induced = true;
        } else if (s == "--induced") {
            // accept but ignore (treat as non-induced)
            non_induced = true;
        } else if (s.rfind("-",0) == 0) {
            // unknown flag
            usage(argv[0]);
            return 1;
        } else {
            files.push_back(s);
        }
    }
    if (files.size() != 2) {
        usage(argv[0]);
        return 1;
    }
    string pattern_file = files[0];
    string target_file = files[1];

    Graph P, T;
    if (!parse_graph_file(pattern_file, P)) {
        cerr << "Failed to parse pattern file: " << pattern_file << "\n";
        return 2;
    }
    if (!parse_graph_file(target_file, T)) {
        cerr << "Failed to parse target file: " << target_file << "\n";
        return 3;
    }

    // If pattern larger than target, zero
    if (P.n > T.n) {
        double ms = 0.0;
        cout << 0 << "\n";
        cout << "solution_count=" << 0 << "\n";
        cout.setf(std::ios::fixed); cout<<setprecision(3);
        cout << "runtime_ms=" << ms << "\n";
        return 0;
    }

    // Build solver (we always run non-induced semantics)
    auto t0 = chrono::high_resolution_clock::now();
    Solver solver(&P, &T, first_only);
    i64 count = solver.solve();
    auto t1 = chrono::high_resolution_clock::now();
    chrono::duration<double, std::milli> dur = t1 - t0;
    double ms = dur.count();

    // Output
    cout << count << "\n";
    cout << "solution_count=" << count << "\n";
    cout.setf(std::ios::fixed);
    cout << setprecision(3);
    cout << "runtime_ms=" << ms << "\n";

    return 0;
}
