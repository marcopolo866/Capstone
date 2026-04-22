#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

using namespace std;

struct Graph {
    int n = 0;
    vector<int> labels;
    vector<vector<int>> adj;
    vector<int> degree;
};

static Graph read_vertex_labelled_lad(const string& path) {
    ifstream in(path);
    if (!in) {
        throw runtime_error("failed to open input file: " + path);
    }

    Graph g;
    if (!(in >> g.n) || g.n < 0) {
        throw runtime_error("invalid LAD vertex count in: " + path);
    }

    g.labels.assign(g.n, 0);
    g.adj.assign(g.n, {});

    for (int v = 0; v < g.n; ++v) {
        int d = 0;
        if (!(in >> g.labels[v] >> d) || d < 0) {
            throw runtime_error("invalid LAD row in: " + path);
        }

        g.adj[v].reserve(static_cast<size_t>(d));
        for (int i = 0; i < d; ++i) {
            int u = -1;
            if (!(in >> u)) {
                throw runtime_error("truncated LAD adjacency in: " + path);
            }
            if (0 <= u && u < g.n && u != v) {
                g.adj[v].push_back(u);
            }
        }
    }

    g.degree.resize(g.n);
    for (int v = 0; v < g.n; ++v) {
        auto& neighbors = g.adj[v];
        sort(neighbors.begin(), neighbors.end());
        neighbors.erase(unique(neighbors.begin(), neighbors.end()), neighbors.end());
        g.degree[v] = static_cast<int>(neighbors.size());
    }

    return g;
}

static bool has_edge(const Graph& g, int u, int v) {
    const auto& neighbors = g.adj[u];
    return binary_search(neighbors.begin(), neighbors.end(), v);
}

static string to_decimal(unsigned __int128 value) {
    if (value == 0) {
        return "0";
    }

    string result;
    while (value > 0) {
        result.push_back(static_cast<char>('0' + value % 10));
        value /= 10;
    }
    reverse(result.begin(), result.end());
    return result;
}

class Solver {
public:
    Solver(const Graph& pattern, const Graph& target)
        : p_(pattern),
          t_(target),
          candidates_(static_cast<size_t>(pattern.n)),
          order_(static_cast<size_t>(pattern.n)),
          map_p_to_t_(static_cast<size_t>(pattern.n), -1),
          map_t_to_p_(static_cast<size_t>(target.n), -1) {}

    unsigned __int128 solve() {
        if (p_.n > t_.n) {
            return 0;
        }

        build_candidates();
        for (const auto& list : candidates_) {
            if (list.empty()) {
                return 0;
            }
        }

        build_order();
        search(0);
        return count_;
    }

private:
    const Graph& p_;
    const Graph& t_;
    vector<vector<int>> candidates_;
    vector<int> order_;
    vector<int> map_p_to_t_;
    vector<int> map_t_to_p_;
    unsigned __int128 count_ = 0;

    void build_candidates() {
        for (int pv = 0; pv < p_.n; ++pv) {
            auto& list = candidates_[pv];
            for (int tv = 0; tv < t_.n; ++tv) {
                if (p_.labels[pv] == t_.labels[tv] && p_.degree[pv] <= t_.degree[tv]) {
                    list.push_back(tv);
                }
            }
        }
    }

    void build_order() {
        iota(order_.begin(), order_.end(), 0);
        sort(order_.begin(), order_.end(), [&](int a, int b) {
            if (candidates_[a].size() != candidates_[b].size()) {
                return candidates_[a].size() < candidates_[b].size();
            }
            if (p_.degree[a] != p_.degree[b]) {
                return p_.degree[a] > p_.degree[b];
            }
            if (p_.labels[a] != p_.labels[b]) {
                return p_.labels[a] < p_.labels[b];
            }
            return a < b;
        });
    }

    bool has_unmapped_neighbor_support(int pv, int tv) const {
        for (int pn : p_.adj[pv]) {
            if (map_p_to_t_[pn] != -1) {
                continue;
            }

            bool supported = false;
            for (int tn : candidates_[pn]) {
                if (map_t_to_p_[tn] == -1 && has_edge(t_, tv, tn)) {
                    supported = true;
                    break;
                }
            }
            if (!supported) {
                return false;
            }
        }
        return true;
    }

    bool feasible(int pv, int tv) const {
        if (map_t_to_p_[tv] != -1) {
            return false;
        }

        for (int pn : p_.adj[pv]) {
            int mapped_neighbor = map_p_to_t_[pn];
            if (mapped_neighbor != -1 && !has_edge(t_, tv, mapped_neighbor)) {
                return false;
            }
        }

        return has_unmapped_neighbor_support(pv, tv);
    }

    bool future_vertex_has_support(int pv) const {
        for (int tv : candidates_[pv]) {
            if (map_t_to_p_[tv] != -1) {
                continue;
            }

            bool ok = true;
            for (int pn : p_.adj[pv]) {
                int mapped_neighbor = map_p_to_t_[pn];
                if (mapped_neighbor != -1 && !has_edge(t_, tv, mapped_neighbor)) {
                    ok = false;
                    break;
                }
            }
            if (ok) {
                return true;
            }
        }
        return false;
    }

    bool future_vertices_have_support(int next_depth) const {
        for (int depth = next_depth; depth < p_.n; ++depth) {
            if (!future_vertex_has_support(order_[depth])) {
                return false;
            }
        }
        return true;
    }

    void search(int depth) {
        if (depth == p_.n) {
            ++count_;
            return;
        }

        int pv = order_[depth];
        for (int tv : candidates_[pv]) {
            if (!feasible(pv, tv)) {
                continue;
            }

            map_p_to_t_[pv] = tv;
            map_t_to_p_[tv] = pv;

            if (future_vertices_have_support(depth + 1)) {
                search(depth + 1);
            }

            map_t_to_p_[tv] = -1;
            map_p_to_t_[pv] = -1;
        }
    }
};

int main(int argc, char** argv) {
    if (argc != 3) {
        cerr << "usage: " << argv[0] << " pattern.lad target.lad\n";
        return 1;
    }

    try {
        Graph pattern = read_vertex_labelled_lad(argv[1]);
        Graph target = read_vertex_labelled_lad(argv[2]);
        Solver solver(pattern, target);
        cout << to_decimal(solver.solve()) << '\n';
    } catch (const exception& exc) {
        cerr << exc.what() << '\n';
        return 1;
    }

    return 0;
}
