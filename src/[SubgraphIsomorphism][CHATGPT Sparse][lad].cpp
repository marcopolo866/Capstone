#include <bits/stdc++.h>
using namespace std;

struct Graph {
    int n = 0;
    int words = 0;
    vector<int> label;
    vector<int> degree;
    vector<vector<int>> adj;
    vector<vector<unsigned long long>> adj_bits;
    vector<unordered_map<int, int>> neigh_label_count;
    unordered_map<int, vector<int>> vertices_by_label;
};

static inline int popcount64(unsigned long long x) {
    return __builtin_popcountll(x);
}

static Graph read_lad(const string &path) {
    ifstream in(path);
    if (!in) {
        throw runtime_error("cannot open file");
    }

    Graph g;
    in >> g.n;
    if (!in || g.n < 0) {
        throw runtime_error("bad graph header");
    }

    g.words = (g.n + 63) >> 6;
    g.label.assign(g.n, 0);
    g.degree.assign(g.n, 0);
    g.adj.assign(g.n, {});

    for (int u = 0; u < g.n; ++u) {
        int lab, deg;
        in >> lab >> deg;
        if (!in || deg < 0) {
            throw runtime_error("bad vertex row");
        }
        g.label[u] = lab;
        g.degree[u] = deg;
        g.adj[u].resize(deg);
        for (int i = 0; i < deg; ++i) {
            in >> g.adj[u][i];
            if (!in) {
                throw runtime_error("bad adjacency list");
            }
        }
    }

    g.adj_bits.assign(g.n, vector<unsigned long long>(g.words, 0ULL));
    g.neigh_label_count.assign(g.n, {});

    for (int u = 0; u < g.n; ++u) {
        auto &vec = g.adj[u];
        sort(vec.begin(), vec.end());
        vec.erase(unique(vec.begin(), vec.end()), vec.end());
        g.degree[u] = (int) vec.size();
        for (int v : vec) {
            if (v < 0 || v >= g.n || v == u) {
                throw runtime_error("invalid edge endpoint");
            }
            g.adj_bits[u][v >> 6] |= 1ULL << (v & 63);
        }
    }

    for (int u = 0; u < g.n; ++u) {
        for (int v : g.adj[u]) {
            ++g.neigh_label_count[u][g.label[v]];
        }
        g.vertices_by_label[g.label[u]].push_back(u);
    }

    return g;
}

struct TrailEntry {
    int u;
    int w;
    unsigned long long old_word;
};

class Solver {
public:
    Solver(Graph p, Graph t) : P(move(p)), T(move(t)) {
        pw = P.words;
        tw = T.words;
        dom.assign(P.n, vector<unsigned long long>(tw, 0ULL));
        dom_count.assign(P.n, 0);
        initial_dom_count.assign(P.n, 0);
        assigned.assign(P.n, -1);
        used.assign(tw, 0ULL);
        pattern_by_label = P.vertices_by_label;
        target_label_total.reserve(T.vertices_by_label.size() * 2 + 1);
        for (auto &kv : T.vertices_by_label) {
            target_label_total[kv.first] = (int) kv.second.size();
        }
        assigned_by_label.reserve(P.vertices_by_label.size() * 2 + 1);
        build_initial_domains();
    }

    unsigned __int128 solve() {
        if (!initial_consistency()) {
            return 0;
        }
        return dfs();
    }

private:
    Graph P, T;
    int pw = 0, tw = 0;

    vector<vector<unsigned long long>> dom;
    vector<int> dom_count;
    vector<int> initial_dom_count;
    vector<int> assigned;
    vector<unsigned long long> used;
    vector<TrailEntry> trail;

    unordered_map<int, vector<int>> pattern_by_label;
    unordered_map<int, int> target_label_total;
    unordered_map<int, int> assigned_by_label;

    static inline bool bit_test(const vector<unsigned long long> &bits, int v) {
        return (bits[v >> 6] >> (v & 63)) & 1ULL;
    }

    inline bool used_test(int v) const {
        return (used[v >> 6] >> (v & 63)) & 1ULL;
    }

    inline void set_used(int v) {
        used[v >> 6] |= 1ULL << (v & 63);
    }

    inline void clear_used(int v) {
        used[v >> 6] &= ~(1ULL << (v & 63));
    }

    inline void set_word(int u, int wi, unsigned long long nw) {
        unsigned long long ow = dom[u][wi];
        if (ow == nw) return;
        trail.push_back({u, wi, ow});
        dom[u][wi] = nw;
        dom_count[u] += popcount64(nw) - popcount64(ow);
    }

    inline void restore(size_t mark) {
        while (trail.size() > mark) {
            TrailEntry e = trail.back();
            trail.pop_back();
            unsigned long long cur = dom[e.u][e.w];
            dom[e.u][e.w] = e.old_word;
            dom_count[e.u] += popcount64(e.old_word) - popcount64(cur);
        }
    }

    void build_initial_domains() {
        for (int u = 0; u < P.n; ++u) {
            auto it = T.vertices_by_label.find(P.label[u]);
            if (it == T.vertices_by_label.end()) continue;

            const auto &cand_list = it->second;
            for (int v : cand_list) {
                if (T.degree[v] < P.degree[u]) continue;
                if (!neighbour_label_feasible(u, v)) continue;
                dom[u][v >> 6] |= 1ULL << (v & 63);
            }

            int cnt = 0;
            for (int wi = 0; wi < tw; ++wi) cnt += popcount64(dom[u][wi]);
            dom_count[u] = cnt;
            initial_dom_count[u] = cnt;
        }
    }

    bool neighbour_label_feasible(int u, int v) const {
        const auto &need = P.neigh_label_count[u];
        const auto &have = T.neigh_label_count[v];
        for (const auto &kv : need) {
            auto it = have.find(kv.first);
            int got = (it == have.end() ? 0 : it->second);
            if (got < kv.second) return false;
        }
        return true;
    }

    bool intersects_adj_domain(int tv, int pu) const {
        const auto &adjb = T.adj_bits[tv];
        const auto &d = dom[pu];
        for (int wi = 0; wi < tw; ++wi) {
            if (adjb[wi] & d[wi]) return true;
        }
        return false;
    }

    int singleton_value(int u) const {
        for (int wi = 0; wi < tw; ++wi) {
            unsigned long long w = dom[u][wi];
            if (w) {
                return (wi << 6) + __builtin_ctzll(w);
            }
        }
        return -1;
    }

    bool revise(int x, int y, deque<int> &q, vector<unsigned char> &in_q, deque<int> &singletons, vector<unsigned char> &in_single) {
        if (assigned[x] != -1) return true;
        bool changed = false;

        for (int wi = 0; wi < tw; ++wi) {
            unsigned long long word = dom[x][wi];
            if (!word) continue;

            unsigned long long remove_mask = 0ULL;
            unsigned long long temp = word;
            while (temp) {
                int b = __builtin_ctzll(temp);
                int tv = (wi << 6) + b;
                if (tv >= T.n) break;
                if (!intersects_adj_domain(tv, y)) {
                    remove_mask |= 1ULL << b;
                }
                temp &= temp - 1ULL;
            }

            if (remove_mask) {
                set_word(x, wi, word & ~remove_mask);
                changed = true;
            }
        }

        if (dom_count[x] == 0) return false;
        if (changed) {
            if (!in_q[x]) {
                in_q[x] = 1;
                q.push_back(x);
            }
            if (assigned[x] == -1 && dom_count[x] == 1 && !in_single[x]) {
                in_single[x] = 1;
                singletons.push_back(x);
            }
        }
        return true;
    }

    bool assign_vertex(int u, int v, vector<pair<int, int>> &forced, deque<int> &q, vector<unsigned char> &in_q, deque<int> &singletons, vector<unsigned char> &in_single) {
        if (assigned[u] != -1) return assigned[u] == v;
        if (used_test(v)) return false;
        if (!bit_test(dom[u], v)) return false;

        int only_w = v >> 6;
        unsigned long long only_mask = 1ULL << (v & 63);
        for (int wi = 0; wi < tw; ++wi) {
            unsigned long long nw = (wi == only_w ? (dom[u][wi] & only_mask) : 0ULL);
            if (nw != dom[u][wi]) set_word(u, wi, nw);
        }
        if (dom_count[u] != 1) return false;

        assigned[u] = v;
        forced.push_back({u, v});
        set_used(v);
        ++assigned_by_label[P.label[u]];

        auto pit = pattern_by_label.find(P.label[u]);
        if (pit != pattern_by_label.end()) {
            for (int x : pit->second) {
                if (x == u || assigned[x] != -1) continue;
                int wi = v >> 6;
                unsigned long long mask = 1ULL << (v & 63);
                if (dom[x][wi] & mask) {
                    set_word(x, wi, dom[x][wi] & ~mask);
                    if (dom_count[x] == 0) return false;
                    if (!in_q[x]) {
                        in_q[x] = 1;
                        q.push_back(x);
                    }
                    if (dom_count[x] == 1 && !in_single[x]) {
                        in_single[x] = 1;
                        singletons.push_back(x);
                    }
                }
            }
        }

        for (int x : P.adj[u]) {
            if (assigned[x] != -1) {
                int xv = assigned[x];
                if (((T.adj_bits[v][xv >> 6] >> (xv & 63)) & 1ULL) == 0ULL) return false;
                continue;
            }

            bool changed = false;
            const auto &adjb = T.adj_bits[v];
            for (int wi = 0; wi < tw; ++wi) {
                unsigned long long nw = dom[x][wi] & adjb[wi];
                if (nw != dom[x][wi]) {
                    set_word(x, wi, nw);
                    changed = true;
                }
            }
            if (dom_count[x] == 0) return false;
            if (changed) {
                if (!in_q[x]) {
                    in_q[x] = 1;
                    q.push_back(x);
                }
                if (dom_count[x] == 1 && !in_single[x]) {
                    in_single[x] = 1;
                    singletons.push_back(x);
                }
            }
        }

        int remaining_pattern = 0;
        auto pcount_it = P.vertices_by_label.find(P.label[u]);
        if (pcount_it != P.vertices_by_label.end()) {
            remaining_pattern = (int) pcount_it->second.size() - assigned_by_label[P.label[u]];
        }
        int remaining_target = target_label_total[P.label[u]] - assigned_by_label[P.label[u]];
        if (remaining_pattern > remaining_target) return false;

        return true;
    }

    bool propagate(vector<pair<int, int>> &forced, deque<int> &q, vector<unsigned char> &in_q, deque<int> &singletons, vector<unsigned char> &in_single) {
        while (!singletons.empty() || !q.empty()) {
            while (!singletons.empty()) {
                int u = singletons.front();
                singletons.pop_front();
                in_single[u] = 0;
                if (assigned[u] != -1) continue;
                if (dom_count[u] != 1) continue;
                int v = singleton_value(u);
                if (v < 0) return false;
                if (!assign_vertex(u, v, forced, q, in_q, singletons, in_single)) return false;
            }

            if (q.empty()) continue;
            int y = q.front();
            q.pop_front();
            in_q[y] = 0;

            for (int x : P.adj[y]) {
                if (assigned[x] != -1) continue;
                if (!revise(x, y, q, in_q, singletons, in_single)) return false;
            }
        }
        return true;
    }

    bool initial_consistency() {
        for (int u = 0; u < P.n; ++u) {
            if (dom_count[u] == 0) return false;
        }

        deque<int> q;
        vector<unsigned char> in_q(P.n, 0);
        deque<int> singletons;
        vector<unsigned char> in_single(P.n, 0);
        vector<pair<int, int>> forced;

        for (int u = 0; u < P.n; ++u) {
            q.push_back(u);
            in_q[u] = 1;
            if (dom_count[u] == 1) {
                singletons.push_back(u);
                in_single[u] = 1;
            }
        }

        size_t mark = trail.size();
        if (!propagate(forced, q, in_q, singletons, in_single)) {
            for (auto it = forced.rbegin(); it != forced.rend(); ++it) {
                --assigned_by_label[P.label[it->first]];
                clear_used(it->second);
                assigned[it->first] = -1;
            }
            restore(mark);
            return false;
        }
        return true;
    }

    int choose_vertex() const {
        int best = -1;
        int best_dom = INT_MAX;
        int best_assigned_n = -1;
        int best_deg = -1;
        int best_init = INT_MAX;

        for (int u = 0; u < P.n; ++u) {
            if (assigned[u] != -1) continue;
            int dc = dom_count[u];
            int assigned_n = 0;
            for (int w : P.adj[u]) assigned_n += (assigned[w] != -1);
            int deg = P.degree[u];
            int initc = initial_dom_count[u];

            if (dc < best_dom ||
                (dc == best_dom && assigned_n > best_assigned_n) ||
                (dc == best_dom && assigned_n == best_assigned_n && deg > best_deg) ||
                (dc == best_dom && assigned_n == best_assigned_n && deg == best_deg && initc < best_init) ||
                (dc == best_dom && assigned_n == best_assigned_n && deg == best_deg && initc == best_init && u < best)) {
                best = u;
                best_dom = dc;
                best_assigned_n = assigned_n;
                best_deg = deg;
                best_init = initc;
            }
        }

        return best;
    }

    void collect_candidates(int u, vector<int> &out) const {
        out.clear();
        out.reserve(dom_count[u]);
        for (int wi = 0; wi < tw; ++wi) {
            unsigned long long word = dom[u][wi];
            while (word) {
                int b = __builtin_ctzll(word);
                int v = (wi << 6) + b;
                if (v < T.n) out.push_back(v);
                word &= word - 1ULL;
            }
        }

        vector<pair<int, int>> scored;
        scored.reserve(out.size());
        for (int v : out) {
            int score = 0;
            for (int w : P.adj[u]) {
                if (assigned[w] != -1) continue;
                score += (int) intersects_adj_domain(v, w);
            }
            scored.push_back({score, v});
        }

        sort(scored.begin(), scored.end(), [&](const auto &a, const auto &b) {
            if (a.first != b.first) return a.first < b.first;
            if (T.degree[a.second] != T.degree[b.second]) return T.degree[a.second] < T.degree[b.second];
            return a.second < b.second;
        });

        for (size_t i = 0; i < scored.size(); ++i) out[i] = scored[i].second;
    }

    unsigned __int128 dfs() {
        int remaining = 0;
        for (int u = 0; u < P.n; ++u) remaining += (assigned[u] == -1);
        if (remaining == 0) return 1;

        int u = choose_vertex();
        if (u == -1) return 1;
        if (dom_count[u] == 0) return 0;

        vector<int> candidates;
        collect_candidates(u, candidates);

        unsigned __int128 total = 0;
        for (int v : candidates) {
            size_t mark = trail.size();
            vector<pair<int, int>> forced;
            deque<int> q;
            vector<unsigned char> in_q(P.n, 0);
            deque<int> singletons;
            vector<unsigned char> in_single(P.n, 0);

            if (assign_vertex(u, v, forced, q, in_q, singletons, in_single) &&
                propagate(forced, q, in_q, singletons, in_single)) {
                total += dfs();
            }

            for (auto it = forced.rbegin(); it != forced.rend(); ++it) {
                --assigned_by_label[P.label[it->first]];
                clear_used(it->second);
                assigned[it->first] = -1;
            }
            restore(mark);
        }

        return total;
    }
};

int main(int argc, char **argv) {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    if (argc != 3) {
        return 1;
    }

    try {
        Graph pattern = read_lad(argv[1]);
        Graph target = read_lad(argv[2]);
        Solver solver(move(pattern), move(target));
        unsigned __int128 ans = solver.solve();
        if (ans == 0) {
            cout << 0 << '\n';
        } else {
            string out;
            while (ans > 0) {
                unsigned digit = (unsigned) (ans % 10);
                out.push_back(char('0' + digit));
                ans /= 10;
            }
            reverse(out.begin(), out.end());
            cout << out << '\n';
        }
    } catch (...) {
        return 1;
    }

    return 0;
}