#include <algorithm>
#include <cstdint>
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
    vector<int> raw_labels;
    vector<int> labels;
    vector<vector<int>> adj;
    vector<int> degree;
};

static Graph read_graph(const string &path) {
    ifstream in(path);
    Graph g;
    if (!in) {
        return g;
    }
    if (!(in >> g.n)) {
        g.n = 0;
        return g;
    }
    g.raw_labels.resize(g.n);
    g.adj.assign(g.n, {});
    g.degree.resize(g.n);
    for (int v = 0; v < g.n; ++v) {
        int label = 0;
        int deg = 0;
        in >> label >> deg;
        g.raw_labels[v] = label;
        g.degree[v] = deg;
        g.adj[v].resize(deg);
        for (int i = 0; i < deg; ++i) {
            in >> g.adj[v][i];
        }
    }
    return g;
}

struct Solver {
    struct WordChange {
        int index;
        uint64_t old_word;
    };

    struct CountChange {
        int vertex;
        int old_count;
    };

    Graph p;
    Graph t;
    int pn = 0;
    int tn = 0;
    int num_labels = 0;
    int chunks = 0;

    vector<uint64_t> t_adj_bits;
    vector<uint64_t> domains;
    vector<int> domain_count;
    vector<int> assignment;
    vector<unsigned char> assigned;

    vector<vector<int>> pattern_vertices_by_label;
    vector<vector<int>> target_vertices_by_label;
    vector<int> remaining_pattern_by_label;

    vector<vector<pair<int, int>>> p_neigh_label_counts;
    vector<vector<pair<int, int>>> t_neigh_label_counts;

    vector<WordChange> word_trail;
    vector<CountChange> count_trail;

    vector<int> queue_stamp;
    vector<int> singleton_stamp;
    vector<int> label_stamp;
    int propagation_token = 1;

    vector<uint64_t> scratch_union;

    explicit Solver(Graph pattern, Graph target) : p(std::move(pattern)), t(std::move(target)) {
        pn = p.n;
        tn = t.n;
    }

    uint64_t *domain_ptr(int v) {
        return domains.data() + static_cast<size_t>(v) * chunks;
    }

    const uint64_t *domain_ptr(int v) const {
        return domains.data() + static_cast<size_t>(v) * chunks;
    }

    const uint64_t *target_adj_ptr(int v) const {
        return t_adj_bits.data() + static_cast<size_t>(v) * chunks;
    }

    static int popcount64(uint64_t x) {
        return __builtin_popcountll(x);
    }

    void compress_labels() {
        vector<int> all = p.raw_labels;
        all.insert(all.end(), t.raw_labels.begin(), t.raw_labels.end());
        sort(all.begin(), all.end());
        all.erase(unique(all.begin(), all.end()), all.end());
        num_labels = static_cast<int>(all.size());

        auto encode = [&](int raw) {
            return static_cast<int>(lower_bound(all.begin(), all.end(), raw) - all.begin());
        };

        p.labels.resize(pn);
        t.labels.resize(tn);
        for (int i = 0; i < pn; ++i) p.labels[i] = encode(p.raw_labels[i]);
        for (int i = 0; i < tn; ++i) t.labels[i] = encode(t.raw_labels[i]);
    }

    static vector<vector<pair<int, int>>> build_neighbor_label_counts(const Graph &g, int num_labels) {
        vector<vector<pair<int, int>>> result(g.n);
        vector<int> freq(num_labels, 0);
        vector<int> touched;
        touched.reserve(32);

        for (int v = 0; v < g.n; ++v) {
            touched.clear();
            for (int nb : g.adj[v]) {
                int lab = g.labels[nb];
                if (freq[lab] == 0) touched.push_back(lab);
                ++freq[lab];
            }
            auto &out = result[v];
            out.reserve(touched.size());
            sort(touched.begin(), touched.end());
            for (int lab : touched) {
                out.push_back({lab, freq[lab]});
                freq[lab] = 0;
            }
        }
        return result;
    }

    static int get_sparse_count(const vector<pair<int, int>> &counts, int label) {
        auto it = lower_bound(counts.begin(), counts.end(), pair<int, int>{label, numeric_limits<int>::min()});
        if (it != counts.end() && it->first == label) return it->second;
        return 0;
    }

    bool initial_candidate_ok(int pu, int tv) const {
        if (p.labels[pu] != t.labels[tv]) return false;
        if (t.degree[tv] < p.degree[pu]) return false;
        const auto &need = p_neigh_label_counts[pu];
        const auto &have = t_neigh_label_counts[tv];
        for (const auto &[lab, cnt] : need) {
            if (get_sparse_count(have, lab) < cnt) return false;
        }
        return true;
    }

    void build_target_bit_adjacency() {
        chunks = (tn + 63) >> 6;
        t_adj_bits.assign(static_cast<size_t>(tn) * chunks, 0ULL);
        for (int v = 0; v < tn; ++v) {
            uint64_t *row = t_adj_bits.data() + static_cast<size_t>(v) * chunks;
            for (int nb : t.adj[v]) {
                row[nb >> 6] |= (1ULL << (nb & 63));
            }
        }
    }

    void build_label_buckets() {
        pattern_vertices_by_label.assign(num_labels, {});
        target_vertices_by_label.assign(num_labels, {});
        remaining_pattern_by_label.assign(num_labels, 0);
        for (int v = 0; v < pn; ++v) {
            pattern_vertices_by_label[p.labels[v]].push_back(v);
            ++remaining_pattern_by_label[p.labels[v]];
        }
        for (int v = 0; v < tn; ++v) {
            target_vertices_by_label[t.labels[v]].push_back(v);
        }
    }

    bool build_initial_domains() {
        domains.assign(static_cast<size_t>(pn) * chunks, 0ULL);
        domain_count.assign(pn, 0);
        for (int pu = 0; pu < pn; ++pu) {
            uint64_t *dom = domain_ptr(pu);
            for (int tv : target_vertices_by_label[p.labels[pu]]) {
                if (initial_candidate_ok(pu, tv)) {
                    dom[tv >> 6] |= (1ULL << (tv & 63));
                    ++domain_count[pu];
                }
            }
            if (domain_count[pu] == 0) return false;
        }
        return true;
    }

    bool row_intersects_domain(int target_vertex, const uint64_t *dom) const {
        const uint64_t *row = target_adj_ptr(target_vertex);
        for (int i = 0; i < chunks; ++i) {
            if (row[i] & dom[i]) return true;
        }
        return false;
    }

    int singleton_value(int pv) const {
        const uint64_t *dom = domain_ptr(pv);
        for (int i = 0; i < chunks; ++i) {
            uint64_t w = dom[i];
            if (w) return (i << 6) + __builtin_ctzll(w);
        }
        return -1;
    }

    bool remove_candidate(int pv, int tv) {
        uint64_t *dom = domain_ptr(pv);
        int wi = tv >> 6;
        uint64_t bit = 1ULL << (tv & 63);
        if ((dom[wi] & bit) == 0ULL) return false;
        count_trail.push_back({pv, domain_count[pv]});
        word_trail.push_back({pv * chunks + wi, dom[wi]});
        dom[wi] &= ~bit;
        --domain_count[pv];
        return true;
    }

    bool intersect_with_target_neighbors(int pv, int tv) {
        uint64_t *dom = domain_ptr(pv);
        const uint64_t *mask = target_adj_ptr(tv);
        bool changed = false;
        int removed = 0;
        int base = pv * chunks;
        for (int i = 0; i < chunks; ++i) {
            uint64_t old_word = dom[i];
            uint64_t new_word = old_word & mask[i];
            if (new_word != old_word) {
                if (!changed) count_trail.push_back({pv, domain_count[pv]});
                changed = true;
                word_trail.push_back({base + i, old_word});
                dom[i] = new_word;
                removed += popcount64(old_word & ~new_word);
            }
        }
        if (changed) domain_count[pv] -= removed;
        return changed;
    }

    bool revise_by_support(int pv, int changed_neighbor) {
        uint64_t *dom_u = domain_ptr(pv);
        const uint64_t *dom_v = domain_ptr(changed_neighbor);
        bool changed = false;
        int removed = 0;
        int base = pv * chunks;

        for (int i = 0; i < chunks; ++i) {
            uint64_t old_word = dom_u[i];
            uint64_t scan = old_word;
            uint64_t remove_mask = 0ULL;
            while (scan) {
                int b = __builtin_ctzll(scan);
                int tv = (i << 6) + b;
                scan &= (scan - 1);
                if (!row_intersects_domain(tv, dom_v)) {
                    remove_mask |= (1ULL << b);
                }
            }
            if (remove_mask != 0ULL) {
                if (!changed) count_trail.push_back({pv, domain_count[pv]});
                changed = true;
                word_trail.push_back({base + i, old_word});
                dom_u[i] = old_word & ~remove_mask;
                removed += popcount64(remove_mask);
            }
        }

        if (changed) domain_count[pv] -= removed;
        return changed;
    }

    bool check_label_union(int label) {
        int need = remaining_pattern_by_label[label];
        if (need <= 1) return true;
        fill(scratch_union.begin(), scratch_union.end(), 0ULL);
        for (int pv : pattern_vertices_by_label[label]) {
            if (assigned[pv]) continue;
            const uint64_t *dom = domain_ptr(pv);
            for (int i = 0; i < chunks; ++i) scratch_union[i] |= dom[i];
        }
        int have = 0;
        for (uint64_t w : scratch_union) have += popcount64(w);
        return have >= need;
    }

    bool propagate(vector<int> &initial_changed, vector<int> &initial_singletons, vector<int> &initial_labels) {
        ++propagation_token;
        if (propagation_token == numeric_limits<int>::max()) {
            fill(queue_stamp.begin(), queue_stamp.end(), 0);
            fill(singleton_stamp.begin(), singleton_stamp.end(), 0);
            fill(label_stamp.begin(), label_stamp.end(), 0);
            propagation_token = 1;
        }

        vector<int> queue;
        vector<int> singleton_queue;
        vector<int> labels_to_check;
        queue.reserve(pn);
        singleton_queue.reserve(pn);
        labels_to_check.reserve(num_labels);

        auto push_queue = [&](int pv) {
            if (!assigned[pv] && queue_stamp[pv] != propagation_token) {
                queue_stamp[pv] = propagation_token;
                queue.push_back(pv);
            }
        };

        auto push_singleton = [&](int pv) {
            if (!assigned[pv] && domain_count[pv] == 1 && singleton_stamp[pv] != propagation_token) {
                singleton_stamp[pv] = propagation_token;
                singleton_queue.push_back(pv);
            }
        };

        auto touch_label = [&](int label) {
            if (label_stamp[label] != propagation_token) {
                label_stamp[label] = propagation_token;
                labels_to_check.push_back(label);
            }
        };

        for (int pv : initial_changed) push_queue(pv);
        for (int pv : initial_singletons) push_singleton(pv);
        for (int label : initial_labels) touch_label(label);

        while (true) {
            while (!singleton_queue.empty()) {
                int pv = singleton_queue.back();
                singleton_queue.pop_back();
                singleton_stamp[pv] = 0;
                if (assigned[pv] || domain_count[pv] != 1) continue;
                int only_tv = singleton_value(pv);
                int label = p.labels[pv];
                for (int other : pattern_vertices_by_label[label]) {
                    if (other == pv || assigned[other]) continue;
                    if (remove_candidate(other, only_tv)) {
                        if (domain_count[other] == 0) return false;
                        push_queue(other);
                        push_singleton(other);
                        touch_label(label);
                    }
                }
            }

            if (!queue.empty()) {
                int changed = queue.back();
                queue.pop_back();
                queue_stamp[changed] = 0;
                if (assigned[changed]) continue;
                for (int nb : p.adj[changed]) {
                    if (assigned[nb]) continue;
                    if (revise_by_support(nb, changed)) {
                        if (domain_count[nb] == 0) return false;
                        push_queue(nb);
                        push_singleton(nb);
                        touch_label(p.labels[nb]);
                    }
                }
                continue;
            }

            if (!labels_to_check.empty()) {
                vector<int> pending;
                pending.swap(labels_to_check);
                for (int label : pending) {
                    label_stamp[label] = 0;
                    if (!check_label_union(label)) return false;
                }
                continue;
            }

            break;
        }

        return true;
    }

    bool initial_propagation() {
        vector<int> all_vertices;
        vector<int> singleton_vertices;
        vector<int> all_labels(num_labels);
        all_vertices.reserve(pn);
        singleton_vertices.reserve(pn);
        iota(all_labels.begin(), all_labels.end(), 0);
        for (int pv = 0; pv < pn; ++pv) {
            all_vertices.push_back(pv);
            if (domain_count[pv] == 1) singleton_vertices.push_back(pv);
        }
        return propagate(all_vertices, singleton_vertices, all_labels);
    }

    void restore(size_t word_mark, size_t count_mark) {
        while (word_trail.size() > word_mark) {
            const auto &c = word_trail.back();
            domains[c.index] = c.old_word;
            word_trail.pop_back();
        }
        while (count_trail.size() > count_mark) {
            const auto &c = count_trail.back();
            domain_count[c.vertex] = c.old_count;
            count_trail.pop_back();
        }
    }

    int choose_next_vertex() const {
        int best = -1;
        int best_domain = numeric_limits<int>::max();
        int best_assigned_neighbors = -1;
        int best_degree = -1;
        int best_unassigned_neighbors = -1;

        for (int pv = 0; pv < pn; ++pv) {
            if (assigned[pv]) continue;
            int dc = domain_count[pv];
            int assigned_neighbors = 0;
            int unassigned_neighbors = 0;
            for (int nb : p.adj[pv]) {
                if (assigned[nb]) ++assigned_neighbors;
                else ++unassigned_neighbors;
            }

            if (dc < best_domain ||
                (dc == best_domain && assigned_neighbors > best_assigned_neighbors) ||
                (dc == best_domain && assigned_neighbors == best_assigned_neighbors && p.degree[pv] > best_degree) ||
                (dc == best_domain && assigned_neighbors == best_assigned_neighbors && p.degree[pv] == best_degree && unassigned_neighbors > best_unassigned_neighbors)) {
                best = pv;
                best_domain = dc;
                best_assigned_neighbors = assigned_neighbors;
                best_degree = p.degree[pv];
                best_unassigned_neighbors = unassigned_neighbors;
            }
        }

        return best;
    }

    vector<int> enumerate_domain(int pv) const {
        vector<int> out;
        out.reserve(domain_count[pv]);
        const uint64_t *dom = domain_ptr(pv);
        for (int i = 0; i < chunks; ++i) {
            uint64_t w = dom[i];
            while (w) {
                int b = __builtin_ctzll(w);
                out.push_back((i << 6) + b);
                w &= (w - 1);
            }
        }
        return out;
    }

    bool apply_choice(int pv, int tv) {
        vector<int> changed_vertices;
        vector<int> singleton_vertices;
        vector<int> touched_labels;
        changed_vertices.reserve(pn);
        singleton_vertices.reserve(pn);
        touched_labels.reserve(4);

        int label = p.labels[pv];
        touched_labels.push_back(label);

        for (int other : pattern_vertices_by_label[label]) {
            if (other == pv || assigned[other]) continue;
            if (remove_candidate(other, tv)) {
                if (domain_count[other] == 0) return false;
                changed_vertices.push_back(other);
                if (domain_count[other] == 1) singleton_vertices.push_back(other);
            }
        }

        for (int nb : p.adj[pv]) {
            if (assigned[nb]) continue;
            if (intersect_with_target_neighbors(nb, tv)) {
                if (domain_count[nb] == 0) return false;
                changed_vertices.push_back(nb);
                if (domain_count[nb] == 1) singleton_vertices.push_back(nb);
                touched_labels.push_back(p.labels[nb]);
            }
        }

        return propagate(changed_vertices, singleton_vertices, touched_labels);
    }

    unsigned __int128 dfs() {
        int pv = choose_next_vertex();
        if (pv == -1) return 1;

        vector<int> candidates = enumerate_domain(pv);
        unsigned __int128 total = 0;
        int label = p.labels[pv];

        for (int tv : candidates) {
            size_t word_mark = word_trail.size();
            size_t count_mark = count_trail.size();

            assignment[pv] = tv;
            assigned[pv] = 1;
            --remaining_pattern_by_label[label];

            if (apply_choice(pv, tv)) {
                total += dfs();
            }

            ++remaining_pattern_by_label[label];
            assigned[pv] = 0;
            assignment[pv] = -1;
            restore(word_mark, count_mark);
        }

        return total;
    }

    bool prepare() {
        if (pn == 0) return true;
        compress_labels();
        build_label_buckets();
        for (int label = 0; label < num_labels; ++label) {
            if (static_cast<int>(target_vertices_by_label[label].size()) < remaining_pattern_by_label[label]) return false;
        }
        p_neigh_label_counts = build_neighbor_label_counts(p, num_labels);
        t_neigh_label_counts = build_neighbor_label_counts(t, num_labels);
        build_target_bit_adjacency();
        if (!build_initial_domains()) return false;

        assignment.assign(pn, -1);
        assigned.assign(pn, 0);
        queue_stamp.assign(pn, 0);
        singleton_stamp.assign(pn, 0);
        label_stamp.assign(num_labels, 0);
        scratch_union.assign(chunks, 0ULL);

        return initial_propagation();
    }
};

static void print_u128(unsigned __int128 value) {
    if (value == 0) {
        cout << '0';
        return;
    }
    string s;
    while (value > 0) {
        unsigned digit = static_cast<unsigned>(value % 10);
        s.push_back(static_cast<char>('0' + digit));
        value /= 10;
    }
    reverse(s.begin(), s.end());
    cout << s;
}

int main(int argc, char **argv) {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    if (argc != 3) {
        return 1;
    }

    Graph pattern = read_graph(argv[1]);
    Graph target = read_graph(argv[2]);
    if (pattern.n == 0 && target.n == 0) {
        return 1;
    }

    if (pattern.n == 0) {
        cout << 1;
        return 0;
    }

    if (pattern.n > target.n) {
        cout << 0;
        return 0;
    }

    Solver solver(std::move(pattern), std::move(target));
    if (!solver.prepare()) {
        cout << 0;
        return 0;
    }

    unsigned __int128 answer = solver.dfs();
    print_u128(answer);
    return 0;
}