#include <algorithm>
#include <chrono>
#include <functional>
#include <fstream>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

struct Graph {
    int n = 0;
    std::vector<int> labels;
    std::vector<std::vector<int>> adj;
    std::vector<std::vector<unsigned char>> matrix;
    std::vector<int> degree;
};

static std::vector<int> parse_ints(const std::string &line) {
    std::vector<int> out;
    std::istringstream iss(line);
    int v = 0;
    while (iss >> v) out.push_back(v);
    return out;
}

static void finalize_graph(Graph &g) {
    g.matrix.assign(g.n, std::vector<unsigned char>(g.n, 0));
    for (int u = 0; u < g.n; ++u) {
        for (int v : g.adj[u]) {
            if (v >= 0 && v < g.n && v != u) {
                g.matrix[u][v] = 1;
                g.matrix[v][u] = 1;
            }
        }
    }
    g.degree.assign(g.n, 0);
    for (int u = 0; u < g.n; ++u) {
        g.adj[u].clear();
        for (int v = 0; v < g.n; ++v) {
            if (g.matrix[u][v]) g.adj[u].push_back(v);
        }
        g.degree[u] = static_cast<int>(g.adj[u].size());
    }
}

static bool read_lad(const std::string &path, Graph &g) {
    std::ifstream in(path);
    if (!in) return false;

    std::string line;
    int n = -1;
    while (std::getline(in, line)) {
        auto vals = parse_ints(line);
        if (vals.empty()) continue;
        n = vals[0];
        break;
    }
    if (n <= 0) return false;

    g = Graph{};
    g.n = n;
    g.labels.assign(g.n, 0);
    g.adj.assign(g.n, {});

    std::vector<std::vector<int>> rows;
    rows.reserve(g.n);
    while (static_cast<int>(rows.size()) < g.n && std::getline(in, line)) {
        auto vals = parse_ints(line);
        if (vals.empty()) continue;
        rows.push_back(std::move(vals));
    }
    while (static_cast<int>(rows.size()) < g.n) rows.push_back({});

    int vertex_votes = 0;
    int standard_votes = 0;
    for (const auto &row : rows) {
        if (row.empty()) continue;
        const bool std_shape =
            row[0] >= 0 && row[0] <= static_cast<int>(row.size()) - 1;
        const bool vtx_shape =
            row.size() >= 2 && row[1] >= 0 && row[1] <= static_cast<int>(row.size()) - 2;
        if (std_shape && !vtx_shape) {
            ++standard_votes;
        } else if (!std_shape && vtx_shape) {
            ++vertex_votes;
        } else if (std_shape && vtx_shape) {
            const bool std_exact = (row[0] == static_cast<int>(row.size()) - 1);
            const bool vtx_exact = (row[1] == static_cast<int>(row.size()) - 2);
            if (std_exact && !vtx_exact) {
                ++standard_votes;
            } else if (!std_exact && vtx_exact) {
                ++vertex_votes;
            }
        }
    }

    bool vertex_labelled = vertex_votes > standard_votes;
    if (vertex_votes == standard_votes) {
        for (const auto &row : rows) {
            if (!row.empty() && row[0] != static_cast<int>(row.size()) - 1) {
                vertex_labelled = true;
                break;
            }
        }
    }

    for (int u = 0; u < g.n; ++u) {
        const auto &row = rows[u];
        if (row.empty()) continue;
        int start = 1;
        int count = row[0];
        if (vertex_labelled) {
            g.labels[u] = row[0];
            count = (row.size() >= 2) ? row[1] : 0;
            start = 2;
        }
        for (int i = 0; i < count && (start + i) < static_cast<int>(row.size()); ++i) {
            const int v = row[start + i];
            if (v >= 0 && v < g.n && v != u) g.adj[u].push_back(v);
        }
    }
    finalize_graph(g);
    return true;
}

static bool read_grf(const std::string &path, Graph &g) {
    std::ifstream in(path);
    if (!in) return false;

    int n = -1;
    if (!(in >> n) || n <= 0) return false;

    g = Graph{};
    g.n = n;
    g.labels.assign(g.n, 0);
    g.adj.assign(g.n, {});

    int u = -1, v = -1;
    while (in >> u >> v) {
        if (u >= 0 && u < g.n && v >= 0 && v < g.n && u != v) {
            g.adj[u].push_back(v);
            g.adj[v].push_back(u);
        }
    }
    finalize_graph(g);
    return true;
}

static bool read_graph(const std::string &path, Graph &g) {
    const auto dot = path.find_last_of('.');
    const std::string ext = (dot == std::string::npos) ? "" : path.substr(dot + 1);
    if (ext == "grf") return read_grf(path, g);
    return read_lad(path, g);
}

int main(int argc, char **argv) {
    if (argc < 3) return 1;
    const auto t0 = std::chrono::high_resolution_clock::now();

    Graph pattern, target;
    if (!read_graph(argv[1], pattern) || !read_graph(argv[2], target)) return 1;

    if (pattern.n > target.n) {
        const auto t1 = std::chrono::high_resolution_clock::now();
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
        std::cout << 0 << '\n';
        std::cout << "Time: " << ms << '\n';
        return 0;
    }

    std::vector<std::vector<int>> domain(pattern.n);
    for (int p = 0; p < pattern.n; ++p) {
        for (int t = 0; t < target.n; ++t) {
            if (pattern.labels[p] == target.labels[t] && pattern.degree[p] <= target.degree[t]) {
                domain[p].push_back(t);
            }
        }
        if (domain[p].empty()) {
            const auto t1 = std::chrono::high_resolution_clock::now();
            const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
            std::cout << 0 << '\n';
            std::cout << "Time: " << ms << '\n';
            return 0;
        }
    }

    std::vector<int> order(pattern.n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        if (domain[a].size() != domain[b].size()) return domain[a].size() < domain[b].size();
        if (pattern.degree[a] != pattern.degree[b]) return pattern.degree[a] > pattern.degree[b];
        return a < b;
    });

    std::vector<int> p_to_t(pattern.n, -1);
    std::vector<unsigned char> used_t(target.n, 0);
    long long total = 0;

    std::function<void(int)> search = [&](int depth) {
        if (depth == pattern.n) {
            ++total;
            std::cout << "Mapping: ";
            for (int p = 0; p < pattern.n; ++p) {
                if (p) std::cout << ' ';
                std::cout << '(' << p << " -> " << p_to_t[p] << ')';
            }
            std::cout << '\n';
            return;
        }

        const int p = order[depth];
        for (int t : domain[p]) {
            if (used_t[t]) continue;

            bool ok = true;
            for (int d = 0; d < depth; ++d) {
                const int pp = order[d];
                const int tt = p_to_t[pp];
                if (pattern.matrix[p][pp] && !target.matrix[t][tt]) {
                    ok = false;
                    break;
                }
            }
            if (!ok) continue;

            p_to_t[p] = t;
            used_t[t] = 1;
            search(depth + 1);
            used_t[t] = 0;
            p_to_t[p] = -1;
        }
    };

    search(0);

    const auto t1 = std::chrono::high_resolution_clock::now();
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
    std::cout << total << '\n';
    std::cout << "Time: " << ms << '\n';
    return 0;
}
