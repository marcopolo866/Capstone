#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <numeric>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

using namespace std;

struct Graph {
    int n = 0;
    vector<int> label;
    vector<vector<int>> nbr;
    vector<int> deg;
};

static Graph read_lad(const char *path) {
    ifstream in(path);
    Graph g;
    if (!in) {
        return g;
    }

    in >> g.n;
    if (!in || g.n < 0) {
        g.n = 0;
        return g;
    }

    g.label.resize(g.n);
    g.nbr.assign(g.n, {});
    g.deg.resize(g.n);

    for (int i = 0; i < g.n; ++i) {
        int lab = 0, d = 0;
        in >> lab >> d;
        g.label[i] = lab;
        g.deg[i] = d;
        g.nbr[i].resize(d);
        for (int j = 0; j < d; ++j) {
            in >> g.nbr[i][j];
        }
    }

    return g;
}

static Graph reorder_pattern(const Graph &g) {
    Graph r;
    r.n = g.n;
    r.label.resize(g.n);
    r.nbr.assign(g.n, {});
    r.deg.resize(g.n);

    unordered_map<int, int> label_freq;
    label_freq.reserve(g.n * 2 + 1);
    for (int x : g.label) {
        ++label_freq[x];
    }

    vector<int> order(g.n);
    iota(order.begin(), order.end(), 0);
    stable_sort(order.begin(), order.end(), [&](int a, int b) {
        if (g.deg[a] != g.deg[b]) return g.deg[a] > g.deg[b];
        int fa = label_freq[g.label[a]];
        int fb = label_freq[g.label[b]];
        if (fa != fb) return fa < fb;
        return a < b;
    });

    vector<int> pos(g.n);
    for (int i = 0; i < g.n; ++i) {
        pos[order[i]] = i;
    }

    for (int nu = 0; nu < g.n; ++nu) {
        int ou = order[nu];
        r.label[nu] = g.label[ou];
        r.deg[nu] = g.deg[ou];
        r.nbr[nu].reserve(g.nbr[ou].size());
        for (int ov : g.nbr[ou]) {
            r.nbr[nu].push_back(pos[ov]);
        }
        sort(r.nbr[nu].begin(), r.nbr[nu].end());
    }

    return r;
}

struct TargetBits {
    int n = 0;
    int words = 0;
    vector<int> label;
    vector<int> deg;
    vector<vector<int>> nbr;
    vector<uint64_t> adj;
};

static TargetBits build_target_bits(const Graph &g) {
    TargetBits t;
    t.n = g.n;
    t.words = (g.n + 63) >> 6;
    t.label = g.label;
    t.deg = g.deg;
    t.nbr = g.nbr;
    t.adj.assign(static_cast<size_t>(t.n) * t.words, 0ULL);

    for (int u = 0; u < t.n; ++u) {
        uint64_t *row = t.adj.data() + static_cast<size_t>(u) * t.words;
        for (int v : g.nbr[u]) {
            row[v >> 6] |= (1ULL << (v & 63));
        }
    }

    return t;
}

struct State {
    int m = 0;
    int n = 0;
    int words = 0;
    vector<uint64_t> dom;
    vector<int> dsize;
};

static inline uint64_t *domain_ptr(State &st, int u) {
    return st.dom.data() + static_cast<size_t>(u) * st.words;
}

static inline const uint64_t *domain_ptr(const State &st, int u) {
    return st.dom.data() + static_cast<size_t>(u) * st.words;
}

static int first_set_bit(const uint64_t *p, int words) {
    for (int i = 0; i < words; ++i) {
        if (p[i]) {
            return (i << 6) + __builtin_ctzll(p[i]);
        }
    }
    return -1;
}

struct Recorder {
    int m = 0;
    int words = 0;
    vector<int> changed;
    vector<int> old_size;
    vector<uint64_t> old_words;
    vector<unsigned char> saved;

    Recorder() = default;
    Recorder(int m_, int words_) : m(m_), words(words_), saved(m_, 0) {}

    void clear() {
        fill(saved.begin(), saved.end(), 0);
        changed.clear();
        old_size.clear();
        old_words.clear();
    }

    void save(int var, const State &st) {
        if (saved[var]) return;
        saved[var] = 1;
        changed.push_back(var);
        old_size.push_back(st.dsize[var]);
        const uint64_t *p = domain_ptr(st, var);
        old_words.insert(old_words.end(), p, p + words);
    }

    void restore(State &st) const {
        for (int i = static_cast<int>(changed.size()) - 1; i >= 0; --i) {
            int var = changed[i];
            st.dsize[var] = old_size[i];
            uint64_t *dst = domain_ptr(st, var);
            const uint64_t *src = old_words.data() + static_cast<size_t>(i) * words;
            memcpy(dst, src, sizeof(uint64_t) * words);
        }
    }
};

static int revise_from_neighbor(
    int u,
    int v,
    State &st,
    const TargetBits &tg,
    Recorder &rec,
    vector<uint64_t> &support
) {
    const uint64_t *Dv = domain_ptr(st, v);
    fill(support.begin(), support.end(), 0ULL);

    for (int w = 0; w < st.words; ++w) {
        uint64_t bits = Dv[w];
        while (bits) {
            int b = __builtin_ctzll(bits);
            int tv = (w << 6) + b;
            const uint64_t *adj_row = tg.adj.data() + static_cast<size_t>(tv) * st.words;
            for (int k = 0; k < st.words; ++k) {
                support[k] |= adj_row[k];
            }
            bits &= bits - 1;
        }
    }

    uint64_t *Du = domain_ptr(st, u);
    bool changed = false;
    for (int k = 0; k < st.words; ++k) {
        if (Du[k] & ~support[k]) {
            changed = true;
            break;
        }
    }

    if (!changed) return 0;

    rec.save(u, st);
    int sz = 0;
    for (int k = 0; k < st.words; ++k) {
        Du[k] &= support[k];
        sz += __builtin_popcountll(Du[k]);
    }
    st.dsize[u] = sz;

    return (sz == 0) ? -1 : 1;
}

static bool assign_singleton(State &st, int u, int value, Recorder &rec) {
    uint64_t *Du = domain_ptr(st, u);
    const int word = value >> 6;
    const uint64_t mask = 1ULL << (value & 63);
    if ((Du[word] & mask) == 0ULL) return false;
    if (st.dsize[u] == 1 && first_set_bit(Du, st.words) == value) return true;

    rec.save(u, st);
    memset(Du, 0, sizeof(uint64_t) * st.words);
    Du[word] = mask;
    st.dsize[u] = 1;
    return true;
}

static bool propagate(
    State &st,
    const Graph &pattern,
    const TargetBits &tg,
    const vector<int> &initial,
    Recorder &rec,
    vector<uint64_t> &support
) {
    vector<int> queue;
    queue.reserve(pattern.n * 2);
    vector<unsigned char> in_queue(pattern.n, 0);

    for (int x : initial) {
        if (!in_queue[x]) {
            in_queue[x] = 1;
            queue.push_back(x);
        }
    }

    for (size_t head = 0; head < queue.size(); ++head) {
        int x = queue[head];
        in_queue[x] = 0;

        if (st.dsize[x] == 0) return false;

        if (st.dsize[x] == 1) {
            int value = first_set_bit(domain_ptr(st, x), st.words);
            int w = value >> 6;
            uint64_t mask = 1ULL << (value & 63);

            for (int y = 0; y < pattern.n; ++y) {
                if (y == x || st.dsize[y] == 0) continue;
                uint64_t *Dy = domain_ptr(st, y);
                if (Dy[w] & mask) {
                    rec.save(y, st);
                    Dy[w] &= ~mask;
                    --st.dsize[y];
                    if (st.dsize[y] == 0) return false;
                    if (!in_queue[y]) {
                        in_queue[y] = 1;
                        queue.push_back(y);
                    }
                }
            }
        }

        for (int u : pattern.nbr[x]) {
            int res = revise_from_neighbor(u, x, st, tg, rec, support);
            if (res < 0) return false;
            if (res > 0 && !in_queue[u]) {
                in_queue[u] = 1;
                queue.push_back(u);
            }
        }
    }

    return true;
}

static string to_string_u128(unsigned __int128 x) {
    if (x == 0) return "0";
    string s;
    while (x > 0) {
        unsigned digit = static_cast<unsigned>(x % 10);
        s.push_back(static_cast<char>('0' + digit));
        x /= 10;
    }
    reverse(s.begin(), s.end());
    return s;
}

static void dfs(
    State &st,
    const Graph &pattern,
    const TargetBits &tg,
    unsigned __int128 &answer
) {
    int pick = -1;
    int best_size = numeric_limits<int>::max();
    int best_tie = -1;
    bool complete = true;

    for (int u = 0; u < pattern.n; ++u) {
        int sz = st.dsize[u];
        if (sz == 0) return;
        if (sz > 1) {
            complete = false;
            int tie = pattern.deg[u];
            if (sz < best_size || (sz == best_size && tie > best_tie)) {
                best_size = sz;
                best_tie = tie;
                pick = u;
            }
        }
    }

    if (complete) {
        ++answer;
        return;
    }

    vector<int> values;
    values.reserve(st.dsize[pick]);
    const uint64_t *Dp = domain_ptr(st, pick);
    for (int w = 0; w < st.words; ++w) {
        uint64_t bits = Dp[w];
        while (bits) {
            int b = __builtin_ctzll(bits);
            values.push_back((w << 6) + b);
            bits &= bits - 1;
        }
    }

    sort(values.begin(), values.end(), [&](int a, int b) {
        if (tg.deg[a] != tg.deg[b]) return tg.deg[a] < tg.deg[b];
        return a < b;
    });

    Recorder rec(st.m, st.words);
    vector<uint64_t> support(st.words);
    vector<int> initial(1, pick);

    for (int v : values) {
        rec.clear();
        bool ok = assign_singleton(st, pick, v, rec);
        if (ok) ok = propagate(st, pattern, tg, initial, rec, support);
        if (ok) dfs(st, pattern, tg, answer);
        rec.restore(st);
    }
}

int main(int argc, char **argv) {
    if (argc != 3) {
        return 1;
    }

    Graph pattern_raw = read_lad(argv[1]);
    Graph target_raw = read_lad(argv[2]);

    Graph pattern = reorder_pattern(pattern_raw);
    TargetBits target = build_target_bits(target_raw);

    if (pattern.n == 0) {
        cout << 1 << '\n';
        return 0;
    }
    if (target.n == 0) {
        cout << 0 << '\n';
        return 0;
    }
    if (pattern.n > target.n) {
        cout << 0 << '\n';
        return 0;
    }

    unordered_map<int, vector<int>> target_by_label;
    target_by_label.reserve(target.n * 2 + 1);
    for (int v = 0; v < target.n; ++v) {
        target_by_label[target.label[v]].push_back(v);
    }

    unordered_map<int, int> pattern_label_count;
    pattern_label_count.reserve(pattern.n * 2 + 1);
    for (int x : pattern.label) {
        ++pattern_label_count[x];
    }
    for (const auto &kv : pattern_label_count) {
        auto it = target_by_label.find(kv.first);
        int have = (it == target_by_label.end()) ? 0 : static_cast<int>(it->second.size());
        if (have < kv.second) {
            cout << 0 << '\n';
            return 0;
        }
    }

    vector<int> pattern_labels_unique;
    pattern_labels_unique.reserve(pattern_label_count.size());
    unordered_map<int, int> pattern_label_index;
    pattern_label_index.reserve(pattern_label_count.size() * 2 + 1);
    for (const auto &kv : pattern_label_count) {
        int idx = static_cast<int>(pattern_labels_unique.size());
        pattern_labels_unique.push_back(kv.first);
        pattern_label_index[kv.first] = idx;
    }
    const int L = static_cast<int>(pattern_labels_unique.size());

    vector<int> pattern_neighbor_label_count(static_cast<size_t>(pattern.n) * L, 0);
    for (int u = 0; u < pattern.n; ++u) {
        int *row = pattern_neighbor_label_count.data() + static_cast<size_t>(u) * L;
        for (int v : pattern.nbr[u]) {
            ++row[pattern_label_index[pattern.label[v]]];
        }
    }

    vector<int> target_neighbor_label_count(static_cast<size_t>(target.n) * L, 0);
    for (int u = 0; u < target.n; ++u) {
        int *row = target_neighbor_label_count.data() + static_cast<size_t>(u) * L;
        for (int v : target.nbr[u]) {
            auto it = pattern_label_index.find(target.label[v]);
            if (it != pattern_label_index.end()) {
                ++row[it->second];
            }
        }
    }

    State st;
    st.m = pattern.n;
    st.n = target.n;
    st.words = target.words;
    st.dom.assign(static_cast<size_t>(st.m) * st.words, 0ULL);
    st.dsize.assign(st.m, 0);

    for (int u = 0; u < pattern.n; ++u) {
        auto it = target_by_label.find(pattern.label[u]);
        if (it == target_by_label.end()) {
            cout << 0 << '\n';
            return 0;
        }

        uint64_t *Du = domain_ptr(st, u);
        const int *need = pattern_neighbor_label_count.data() + static_cast<size_t>(u) * L;

        for (int tv : it->second) {
            if (target.deg[tv] < pattern.deg[u]) continue;
            const int *have = target_neighbor_label_count.data() + static_cast<size_t>(tv) * L;
            bool ok = true;
            for (int i = 0; i < L; ++i) {
                if (have[i] < need[i]) {
                    ok = false;
                    break;
                }
            }
            if (!ok) continue;
            Du[tv >> 6] |= (1ULL << (tv & 63));
            ++st.dsize[u];
        }

        if (st.dsize[u] == 0) {
            cout << 0 << '\n';
            return 0;
        }
    }

    Recorder init_rec(st.m, st.words);
    vector<uint64_t> support(st.words);
    vector<int> initial(pattern.n);
    iota(initial.begin(), initial.end(), 0);
    if (!propagate(st, pattern, target, initial, init_rec, support)) {
        cout << 0 << '\n';
        return 0;
    }

    unsigned __int128 answer = 0;
    dfs(st, pattern, target, answer);
    cout << to_string_u128(answer) << '\n';
    return 0;
}