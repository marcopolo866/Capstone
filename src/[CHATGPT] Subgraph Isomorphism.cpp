/**
 *  Prompt:
    Write a program in C++ that, given a large target graph, can find all instances of a smaller 
    pattern within it, or otherwise confirm there are no instances inputs like the provided files, 
    should work with both .lad and .grf files. Input files will look very similar to this. The key idea is the 
    fastest runtime as possible, so take every shortcut possible. Just output the code as a block to copy and paste, nothing else. 
    Also be sure to output how long the program took to run as precise as possible without losing accuracy in milliseconds.
    The code should also be as portable and universal as possible, so use common C++ libraries.   
    The output should only be these lines:  
    The nodes of the target graph that create the pattern, if multiple, one numbered list on each line if possible, otherwise wraparound with brackets. 
    How many instances exist of the smaller graph in the bigger target graph as a whole integer number
    The last line should be the execution time of the program in milliseconds.
*/

// Compile (examples):
//   g++ -O3 -march=native -DNDEBUG -std=c++17 subiso.cpp -o subiso
//   clang++ -O3 -DNDEBUG -std=c++17 subiso.cpp -o subiso
//   MSVC (Developer Command Prompt):
//     cl /O2 /DNDEBUG /std:c++17 subiso.cpp

#include <algorithm>
#include <array>
#include <bitset>
#include <chrono>
#include <cctype>
#include <cinttypes>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

using namespace std;

static inline bool ends_with_ci(const string &s, const string &suf) {
    if (s.size() < suf.size()) return false;
    return equal(suf.rbegin(), suf.rend(), s.rbegin(),
                 [](char a, char b) { return tolower((unsigned char)a) == tolower((unsigned char)b); });
}

static vector<long long> extract_ints_from_line(const string &line) {
    vector<long long> res;
    long long sign = 1, val = 0;
    bool in = false;
    for (size_t i = 0; i <= line.size(); ++i) {
        char c = (i < line.size() ? line[i] : ' ');
        if (!in) {
            if (c == '-' || c == '+') {
                if (i + 1 < line.size() && isdigit((unsigned char)line[i + 1])) {
                    in = true;
                    sign = (c == '-') ? -1 : 1;
                    val = 0;
                }
            } else if (isdigit((unsigned char)c)) {
                in = true;
                sign = 1;
                val = c - '0';
            }
        } else {
            if (isdigit((unsigned char)c)) {
                val = val * 10 + (c - '0');
            } else {
                res.push_back(sign * val);
                in = false;
                sign = 1;
                val = 0;
            }
        }
    }
    return res;
}

static inline void sort_unique_vec(vector<int> &v) {
    sort(v.begin(), v.end());
    v.erase(unique(v.begin(), v.end()), v.end());
}

struct Graph {
    int n = 0;
    bool directed = false;
    vector<int> id_of;                 // internal idx -> original id (GRF), or idx for LAD
    vector<int> label;                 // vertex labels (GRF), 0 for LAD
    vector<vector<int>> out;           // outgoing adjacency (or undirected adjacency for LAD)
    vector<vector<int>> in;            // incoming adjacency (same as out for LAD)
    vector<int> outdeg, indeg, undeg;  // degrees

    // Optional outgoing adjacency bitset for fast edge queries
    bool use_bits = false;
    int words = 0;
    vector<uint64_t> out_bits;         // size n * words

    inline bool has_out_edge(int a, int b) const {
        if (use_bits) {
            uint64_t w = out_bits[(size_t)a * (size_t)words + (size_t)(b >> 6)];
            return (w >> (b & 63)) & 1ULL;
        }
        const auto &v = out[a];
        return binary_search(v.begin(), v.end(), b);
    }
};

static Graph read_lad(const string &path) {
    ifstream f(path);
    if (!f) throw runtime_error("Failed to open file: " + path);

    Graph g;
    g.directed = false;

    f >> g.n;
    g.id_of.resize(g.n);
    iota(g.id_of.begin(), g.id_of.end(), 0);
    g.label.assign(g.n, 0);
    g.out.assign(g.n, {});

    for (int i = 0; i < g.n; ++i) {
        int d;
        f >> d;
        g.out[i].reserve((size_t)max(0, d));
        for (int k = 0; k < d; ++k) {
            int nb;
            f >> nb;
            if (0 <= nb && nb < g.n) g.out[i].push_back(nb);
        }
    }

    // Symmetrize (LAD used here as undirected adjacency lists)
    vector<vector<int>> orig = g.out;
    for (int i = 0; i < g.n; ++i) {
        for (int nb : orig[i]) {
            if (0 <= nb && nb < g.n) g.out[nb].push_back(i);
        }
    }
    for (int i = 0; i < g.n; ++i) sort_unique_vec(g.out[i]);

    g.in = g.out;

    g.outdeg.resize(g.n);
    g.indeg.resize(g.n);
    g.undeg.resize(g.n);
    for (int i = 0; i < g.n; ++i) {
        int d = (int)g.out[i].size();
        g.outdeg[i] = d;
        g.indeg[i] = d;
        g.undeg[i] = d;
    }
    return g;
}

static Graph read_grf(const string &path) {
    ifstream f(path);
    if (!f) throw runtime_error("Failed to open file: " + path);

    Graph g;
    g.directed = true;

    string line;
    int n = -1;

    // Find node count (first non-empty/non-comment line with an int)
    while (getline(f, line)) {
        size_t p = line.find_first_not_of(" \t\r\n");
        if (p == string::npos) continue;
        if (line[p] == '#') continue;
        auto ints = extract_ints_from_line(line);
        if (!ints.empty()) { n = (int)ints[0]; break; }
    }
    if (n < 0) throw runtime_error("Invalid GRF (missing node count): " + path);

    g.n = n;
    g.id_of.assign(n, 0);
    g.label.assign(n, 0);
    g.out.assign(n, {});
    g.in.assign(n, {});

    vector<int> ids_in_order;
    ids_in_order.reserve((size_t)n);
    unordered_map<int, int> id_to_idx;
    id_to_idx.reserve((size_t)n * 2);

    // Read n lines of: nodeId label (ignore extra ints)
    for (int i = 0; i < n; ) {
        if (!getline(f, line)) throw runtime_error("Invalid GRF (EOF in labels): " + path);
        size_t p = line.find_first_not_of(" \t\r\n");
        if (p == string::npos) continue;
        if (line[p] == '#') continue;

        auto ints = extract_ints_from_line(line);
        if ((int)ints.size() < 2) continue;

        int id = (int)ints[0];
        int lab = (int)ints[1];
        ids_in_order.push_back(id);
        id_to_idx[id] = i;
        g.id_of[i] = id;
        g.label[i] = lab;
        ++i;
    }

    // For each node, read an int m then m edge lines (best-effort parse)
    for (int ord = 0; ord < n; ++ord) {
        int node_id = ids_in_order[ord];
        int node_idx = id_to_idx[node_id];

        int m = -1;
        while (getline(f, line)) {
            size_t p = line.find_first_not_of(" \t\r\n");
            if (p == string::npos) continue;
            if (line[p] == '#') continue;
            auto ints = extract_ints_from_line(line);
            if (!ints.empty()) { m = (int)ints[0]; break; }
        }
        if (m < 0) throw runtime_error("Invalid GRF (missing edge count): " + path);

        g.out[node_idx].reserve((size_t)max(0, m));
        for (int e = 0; e < m; ++e) {
            vector<long long> ints;
            while (getline(f, line)) {
                size_t p = line.find_first_not_of(" \t\r\n");
                if (p == string::npos) continue;
                if (line[p] == '#') continue;
                ints = extract_ints_from_line(line);
                if (!ints.empty()) break;
            }
            if (ints.empty()) throw runtime_error("Invalid GRF (EOF in edges): " + path);

            int dst_id = -1;
            if (ints.size() == 1) {
                dst_id = (int)ints[0];
            } else {
                // Common variants: "src dst" or "dst label" (edge labels ignored)
                int a = (int)ints[0];
                int b = (int)ints[1];
                if (a == node_id && id_to_idx.find(b) != id_to_idx.end()) dst_id = b;
                else if (id_to_idx.find(a) != id_to_idx.end()) dst_id = a;
                else if (id_to_idx.find(b) != id_to_idx.end()) dst_id = b;
                else continue;
            }

            auto it = id_to_idx.find(dst_id);
            if (it == id_to_idx.end()) continue;
            g.out[node_idx].push_back(it->second);
        }
    }

    // Sort/unique and build incoming adjacency
    for (int i = 0; i < n; ++i) sort_unique_vec(g.out[i]);
    for (int i = 0; i < n; ++i) {
        for (int nb : g.out[i]) g.in[nb].push_back(i);
    }
    for (int i = 0; i < n; ++i) sort_unique_vec(g.in[i]);

    // Degrees
    g.outdeg.resize(n);
    g.indeg.resize(n);
    g.undeg.resize(n);
    for (int i = 0; i < n; ++i) {
        g.outdeg[i] = (int)g.out[i].size();
        g.indeg[i] = (int)g.in[i].size();

        // undirected degree = |out U in|
        const auto &A = g.out[i];
        const auto &B = g.in[i];
        size_t pa = 0, pb = 0;
        int cnt = 0;
        while (pa < A.size() && pb < B.size()) {
            int a = A[pa], b = B[pb];
            if (a == b) { ++cnt; ++pa; ++pb; }
            else if (a < b) { ++cnt; ++pa; }
            else { ++cnt; ++pb; }
        }
        cnt += (int)(A.size() - pa);
        cnt += (int)(B.size() - pb);
        g.undeg[i] = cnt;
    }

    return g;
}

static Graph read_vf(const string &path) {
    ifstream f(path);
    if (!f) throw runtime_error("Failed to open file: " + path);

    Graph g;
    g.directed = true;

    string line;
    int n = -1;

    while (getline(f, line)) {
        size_t p = line.find_first_not_of(" \t\r\n");
        if (p == string::npos) continue;
        if (line[p] == '#') continue;
        auto ints = extract_ints_from_line(line);
        if (!ints.empty()) { n = (int)ints[0]; break; }
    }
    if (n < 0) throw runtime_error("Invalid VF (missing node count): " + path);

    g.n = n;
    g.id_of.assign(n, 0);
    g.label.assign(n, 0);
    g.out.assign(n, {});
    g.in.assign(n, {});

    vector<int> ids_in_order;
    ids_in_order.reserve((size_t)n);
    unordered_map<int, int> id_to_idx;
    id_to_idx.reserve((size_t)n * 2);

    for (int i = 0; i < n; ) {
        if (!getline(f, line)) throw runtime_error("Invalid VF (EOF in labels): " + path);
        size_t p = line.find_first_not_of(" \t\r\n");
        if (p == string::npos) continue;
        if (line[p] == '#') continue;
        auto ints = extract_ints_from_line(line);
        if ((int)ints.size() < 2) continue;
        int id = (int)ints[0];
        int lab = (int)ints[1];
        ids_in_order.push_back(id);
        id_to_idx[id] = i;
        g.id_of[i] = id;
        g.label[i] = lab;
        ++i;
    }

    for (int ord = 0; ord < n; ++ord) {
        int node_id = ids_in_order[ord];
        int node_idx = id_to_idx[node_id];

        int m = -1;
        while (getline(f, line)) {
            size_t p = line.find_first_not_of(" \t\r\n");
            if (p == string::npos) continue;
            if (line[p] == '#') continue;
            auto ints = extract_ints_from_line(line);
            if (!ints.empty()) { m = (int)ints[0]; break; }
        }
        if (m < 0) throw runtime_error("Invalid VF (missing edge count): " + path);

        g.out[node_idx].reserve((size_t)max(0, m));
        for (int e = 0; e < m; ++e) {
            vector<long long> ints;
            while (getline(f, line)) {
                size_t p = line.find_first_not_of(" \t\r\n");
                if (p == string::npos) continue;
                if (line[p] == '#') continue;
                ints = extract_ints_from_line(line);
                if (!ints.empty()) break;
            }
            if (ints.empty()) throw runtime_error("Invalid VF (EOF in edges): " + path);

            int dst_id = -1;
            if (ints.size() == 1) {
                dst_id = (int)ints[0];
            } else {
                int a = (int)ints[0];
                int b = (int)ints[1];
                if (a == node_id && id_to_idx.find(b) != id_to_idx.end()) dst_id = b;
                else if (id_to_idx.find(b) != id_to_idx.end()) dst_id = b;
                else if (id_to_idx.find(a) != id_to_idx.end()) dst_id = a;
                else continue;
            }

            auto it = id_to_idx.find(dst_id);
            if (it == id_to_idx.end()) continue;
            g.out[node_idx].push_back(it->second);
        }
    }

    for (int i = 0; i < n; ++i) sort_unique_vec(g.out[i]);
    for (int i = 0; i < n; ++i) {
        for (int nb : g.out[i]) g.in[nb].push_back(i);
    }
    for (int i = 0; i < n; ++i) sort_unique_vec(g.in[i]);

    g.outdeg.resize(n);
    g.indeg.resize(n);
    g.undeg.resize(n);
    for (int i = 0; i < n; ++i) {
        g.outdeg[i] = (int)g.out[i].size();
        g.indeg[i] = (int)g.in[i].size();
        const auto &A = g.out[i];
        const auto &B = g.in[i];
        size_t pa = 0, pb = 0;
        int cnt = 0;
        while (pa < A.size() && pb < B.size()) {
            int a = A[pa], b = B[pb];
            if (a == b) { ++cnt; ++pa; ++pb; }
            else if (a < b) { ++cnt; ++pa; }
            else { ++cnt; ++pb; }
        }
        cnt += (int)(A.size() - pa);
        cnt += (int)(B.size() - pb);
        g.undeg[i] = cnt;
    }

    return g;
}

static Graph read_graph_auto(const string &path) {
    if (ends_with_ci(path, ".lad")) return read_lad(path);
    if (ends_with_ci(path, ".grf")) return read_grf(path);
    if (ends_with_ci(path, ".vf")) return read_vf(path);

    // fallback heuristic: comment style => GRF
    ifstream f(path);
    string line;
    while (getline(f, line)) {
        size_t p = line.find_first_not_of(" \t\r\n");
        if (p == string::npos) continue;
        if (line[p] == '#') return read_grf(path);
        break;
    }
    return read_lad(path);
}

static void maybe_build_bitset(Graph &g, int threshold_n = 12000) {
    if (g.n <= 0 || g.n > threshold_n) {
        g.use_bits = false;
        return;
    }
    g.use_bits = true;
    g.words = (g.n + 63) >> 6;
    g.out_bits.assign((size_t)g.n * (size_t)g.words, 0ULL);
    for (int i = 0; i < g.n; ++i) {
        for (int nb : g.out[i]) {
            g.out_bits[(size_t)i * (size_t)g.words + (size_t)(nb >> 6)] |= (1ULL << (nb & 63));
        }
    }
}

struct PatternBits {
    int n = 0;
    int words = 0;
    vector<uint64_t> out_bits; // size n*words
    inline bool has_out(int a, int b) const {
        uint64_t w = out_bits[(size_t)a * (size_t)words + (size_t)(b >> 6)];
        return (w >> (b & 63)) & 1ULL;
    }
    inline bool has_und(int a, int b) const {
        return has_out(a, b) || has_out(b, a);
    }
};

int main(int argc, char **argv) {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    bool first_only = false;
    bool induced = true;
    vector<string> positional;
    positional.reserve(static_cast<size_t>(max(0, argc - 1)));
    for (int i = 1; i < argc; ++i) {
        string arg = argv[i];
        if (arg == "--first-only" || arg == "-F") {
            first_only = true;
            continue;
        }
        if (arg == "--non-induced" || arg == "--noninduced") {
            induced = false;
            continue;
        }
        if (arg == "--induced") {
            induced = true;
            continue;
        }
        positional.push_back(std::move(arg));
    }

    if (positional.size() != 2) {
        cerr << "Usage: " << argv[0] << " [--first-only|-F] [--induced|--non-induced] <pattern_graph.(lad|grf)> <target_graph.(lad|grf)>\n";
        return 1;
    }

    const string pattern_path = positional[0];
    const string target_path = positional[1];

    Graph pattern = read_graph_auto(pattern_path);
    Graph target = read_graph_auto(target_path);

    auto t0 = chrono::steady_clock::now();

    maybe_build_bitset(target);

    // Pattern adjacency bitset
    PatternBits pb;
    pb.n = pattern.n;
    pb.words = (pb.n + 63) >> 6;
    pb.out_bits.assign((size_t)pb.n * (size_t)pb.words, 0ULL);
    for (int i = 0; i < pattern.n; ++i) {
        for (int nb : pattern.out[i]) {
            if (0 <= nb && nb < pattern.n) {
                pb.out_bits[(size_t)i * (size_t)pb.words + (size_t)(nb >> 6)] |= (1ULL << (nb & 63));
            }
        }
    }

    const bool use_directed = pattern.directed;

    // Empty / impossible cases
    if (pattern.n == 0) {
        auto t1 = chrono::steady_clock::now();
        double sec = chrono::duration<double>(t1 - t0).count();
        cout.setf(std::ios::fixed);
        cout << setprecision(6) << 1 << " " << sec << " " << sec << "\n";
        return 0;
    }
    if (pattern.n > target.n) {
        auto t1 = chrono::steady_clock::now();
        double sec = chrono::duration<double>(t1 - t0).count();
        cout.setf(std::ios::fixed);
        cout << setprecision(6) << 0 << " " << sec << " " << sec << "\n";
        return 0;
    }

    // Label buckets for target (LAD labels are 0, so everything shares one bucket)
    unordered_map<int, vector<int>> label_buckets;
    label_buckets.reserve((size_t)target.n * 2);
    for (int v = 0; v < target.n; ++v) {
        label_buckets[target.label[v]].push_back(v);
    }

    // Candidate lists per pattern vertex (label + degree filters)
    vector<vector<int>> cand(pattern.n);
    vector<int> pat_deg_use(pattern.n);
    for (int u = 0; u < pattern.n; ++u) {
        pat_deg_use[u] = use_directed ? (pattern.outdeg[u] + pattern.indeg[u]) : pattern.undeg[u];

        auto it = label_buckets.find(pattern.label[u]);
        if (it == label_buckets.end()) continue;

        const auto &bucket = it->second;
        cand[u].reserve(bucket.size());
        for (int v : bucket) {
            if (use_directed) {
                if (target.outdeg[v] < pattern.outdeg[u]) continue;
                if (target.indeg[v] < pattern.indeg[u]) continue;
            } else {
                if (target.undeg[v] < pattern.undeg[u]) continue;
            }
            cand[u].push_back(v);
        }
        if (cand[u].empty()) {
            auto t1 = chrono::steady_clock::now();
            double sec = chrono::duration<double>(t1 - t0).count();
            cout.setf(std::ios::fixed);
            cout << setprecision(6) << 0 << " " << sec << " " << sec << "\n";
            return 0;
        }
    }

    // Pattern neighbor lists (for forward checking)
    vector<vector<int>> pat_neighbors(pattern.n);
    if (use_directed) {
        for (int u = 0; u < pattern.n; ++u) {
            vector<int> neigh;
            neigh.reserve(pattern.out[u].size() + pattern.in[u].size());
            for (int x : pattern.out[u]) neigh.push_back(x);
            for (int x : pattern.in[u]) neigh.push_back(x);
            sort_unique_vec(neigh);
            pat_neighbors[u] = std::move(neigh);
        }
    } else {
        for (int u = 0; u < pattern.n; ++u) {
            vector<int> neigh = pattern.out[u];
            sort_unique_vec(neigh);
            pat_neighbors[u] = std::move(neigh);
        }
    }

    auto tgt_has_dir = [&](int a, int b) -> bool { return target.has_out_edge(a, b); };
    auto tgt_has_und = [&](int a, int b) -> bool { return target.has_out_edge(a, b) || target.has_out_edge(b, a); };

    vector<int> mapP(pattern.n, -1);         // pattern vertex -> target vertex
    vector<char> usedT(target.n, 0);         // target used flags
    vector<int> mapped; mapped.reserve(pattern.n);

    long long solutions = 0;
    double first_solution_sec = -1.0;

    auto consistent = [&](int u, int v) -> bool {
        if (use_directed) {
            if (induced) {
                if (pb.has_out(u, u) != tgt_has_dir(v, v)) return false;
            } else {
                if (pb.has_out(u, u) && !tgt_has_dir(v, v)) return false;
            }
            for (int w : mapped) {
                int tw = mapP[w];
                bool pat_uv = pb.has_out(u, w);
                bool tar_uv = tgt_has_dir(v, tw);
                if (induced) {
                    if (pat_uv != tar_uv) return false;
                } else {
                    if (pat_uv && !tar_uv) return false;
                }

                bool pat_vu = pb.has_out(w, u);
                bool tar_vu = tgt_has_dir(tw, v);
                if (induced) {
                    if (pat_vu != tar_vu) return false;
                } else {
                    if (pat_vu && !tar_vu) return false;
                }
            }
        } else {
            if (induced) {
                if (pb.has_und(u, u) != tgt_has_und(v, v)) return false;
            } else {
                if (pb.has_und(u, u) && !tgt_has_und(v, v)) return false;
            }
            for (int w : mapped) {
                int tw = mapP[w];
                bool pat_uw = pb.has_und(u, w);
                bool tar_uw = tgt_has_und(v, tw);
                if (induced) {
                    if (pat_uw != tar_uw) return false;
                } else {
                    if (pat_uw && !tar_uw) return false;
                }
            }
        }
        return true;
    };

    auto has_any_candidate = [&](int x) -> bool {
        for (int tv : cand[x]) {
            if (usedT[tv]) continue;
            if (consistent(x, tv)) return true;
        }
        return false;
    };

    function<void(int)> dfs = [&](int depth) {
        if (first_only && solutions > 0) return;
        if (depth == pattern.n) {
            if (solutions == 0) {
                auto now = chrono::steady_clock::now();
                first_solution_sec = chrono::duration<double>(now - t0).count();
            }
            ++solutions;
            return;
        }

        // MRV + tie-break by pattern degree
        int best_u = -1;
        int best_cnt = INT_MAX;
        int best_deg = -1;
        vector<int> best_list;

        for (int u = 0; u < pattern.n; ++u) {
            if (mapP[u] != -1) continue;

            vector<int> tmp;
            tmp.reserve(cand[u].size());
            for (int v : cand[u]) {
                if (usedT[v]) continue;
                if (!consistent(u, v)) continue;
                tmp.push_back(v);
            }

            int cnt = (int)tmp.size();
            if (cnt == 0) return;

            int deg = pat_deg_use[u];
            if (cnt < best_cnt || (cnt == best_cnt && deg > best_deg)) {
                best_cnt = cnt;
                best_deg = deg;
                best_u = u;
                best_list.swap(tmp);
            }
        }

        int u = best_u;
        const auto &candidates = best_list;

        for (int v : candidates) {
            mapP[u] = v;
            usedT[v] = 1;
            mapped.push_back(u);

            // Forward check: neighbors of u must still have some feasible candidate
            bool ok = true;
            for (int x : pat_neighbors[u]) {
                if (mapP[x] != -1) continue;
                if (!has_any_candidate(x)) { ok = false; break; }
            }

            if (ok) dfs(depth + 1);

            mapped.pop_back();
            usedT[v] = 0;
            mapP[u] = -1;
        }
    };

    dfs(0);

    auto t1 = chrono::steady_clock::now();
    double all_sec = chrono::duration<double>(t1 - t0).count();
    if (first_solution_sec < 0.0) {
        first_solution_sec = all_sec;
    }

    cout.setf(std::ios::fixed);
    cout << setprecision(6) << solutions << " " << first_solution_sec << " " << all_sec << "\n";

    return 0;
}
