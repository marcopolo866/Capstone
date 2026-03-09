#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <numeric>
#include <string>
#include <vector>

struct Graph {
    int n = 0;
    std::vector<int> label;
    std::vector<int> degree;
    std::vector<std::vector<int>> adj;
};

static bool has_edge(const Graph &g, int u, int v) {
    const auto &a = g.adj[u];
    return std::binary_search(a.begin(), a.end(), v);
}

static int parse_line_ints(const char *line, std::vector<int> &vals) {
    vals.clear();
    const char *p = line;
    while (*p) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') ++p;
        if (!*p) break;
        bool neg = (*p == '-');
        if (neg) ++p;
        if (*p < '0' || *p > '9') break;
        int v = 0;
        while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        vals.push_back(neg ? -v : v);
    }
    return static_cast<int>(vals.size());
}

static void finalize_graph(Graph &g) {
    for (int u = 0; u < g.n; ++u) {
        std::sort(g.adj[u].begin(), g.adj[u].end());
        g.adj[u].erase(std::unique(g.adj[u].begin(), g.adj[u].end()), g.adj[u].end());
    }
    for (int u = 0; u < g.n; ++u) {
        for (int v : g.adj[u]) {
            if (v >= 0 && v < g.n && v != u) g.adj[v].push_back(u);
        }
    }
    for (int u = 0; u < g.n; ++u) {
        std::sort(g.adj[u].begin(), g.adj[u].end());
        g.adj[u].erase(std::unique(g.adj[u].begin(), g.adj[u].end()), g.adj[u].end());
    }
    g.degree.assign(g.n, 0);
    for (int u = 0; u < g.n; ++u) g.degree[u] = static_cast<int>(g.adj[u].size());
}

static bool read_lad(const std::string &filename, Graph &g) {
    FILE *f = std::fopen(filename.c_str(), "r");
    if (!f) return false;

    g = Graph{};
    char line[65536];
    std::vector<int> vals;

    while (std::fgets(line, sizeof(line), f)) {
        if (parse_line_ints(line, vals) > 0) {
            g.n = vals[0];
            break;
        }
    }
    if (g.n <= 0) {
        std::fclose(f);
        return false;
    }

    g.label.assign(g.n, 0);
    g.adj.assign(g.n, {});

    std::vector<std::vector<int>> rows(g.n);
    int got = 0;
    while (got < g.n && std::fgets(line, sizeof(line), f)) {
        if (parse_line_ints(line, vals) <= 0) continue;
        rows[got++] = vals;
    }
    std::fclose(f);

    int vertex_votes = 0;
    int standard_votes = 0;
    for (int i = 0; i < g.n; ++i) {
        const auto &row = rows[i];
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
        for (int i = 0; i < g.n; ++i) {
            if (!rows[i].empty() && rows[i][0] != static_cast<int>(rows[i].size()) - 1) {
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
            g.label[u] = row[0];
            count = (row.size() >= 2) ? row[1] : 0;
            start = 2;
        }
        for (int j = 0; j < count && start + j < static_cast<int>(row.size()); ++j) {
            int v = row[start + j];
            if (v >= 0 && v < g.n && v != u) g.adj[u].push_back(v);
        }
    }

    finalize_graph(g);
    return true;
}

static bool read_grf(const std::string &filename, Graph &g) {
    FILE *f = std::fopen(filename.c_str(), "r");
    if (!f) return false;

    g = Graph{};
    if (std::fscanf(f, "%d", &g.n) != 1 || g.n <= 0) {
        std::fclose(f);
        return false;
    }

    g.label.assign(g.n, 0);
    g.adj.assign(g.n, {});

    int u = -1, v = -1;
    while (std::fscanf(f, "%d %d", &u, &v) == 2) {
        if (u >= 0 && u < g.n && v >= 0 && v < g.n && u != v) g.adj[u].push_back(v);
    }
    std::fclose(f);

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
    bool print_mappings = false;
    std::vector<std::string> positional;
    positional.reserve(static_cast<size_t>(argc));
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i] ? std::string(argv[i]) : std::string();
        if (arg == "--print-mappings") {
            print_mappings = true;
            continue;
        }
        positional.push_back(arg);
    }
    if (positional.size() < 2) return 1;
    const auto started = std::chrono::high_resolution_clock::now();

    Graph pattern, target;
    if (!read_graph(positional[0], pattern) || !read_graph(positional[1], target)) return 1;

    if (pattern.n > target.n) {
        const auto done = std::chrono::high_resolution_clock::now();
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(done - started).count();
        std::cout << "solution_count=0" << '\n';
        std::cout << 0 << '\n';
        std::cout << "Time: " << ms << '\n';
        return 0;
    }

    std::vector<int> order(pattern.n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        if (pattern.degree[a] != pattern.degree[b]) return pattern.degree[a] > pattern.degree[b];
        return a < b;
    });

    std::vector<int> map_p_to_t(pattern.n, -1);
    std::vector<unsigned char> used_t(target.n, 0);
    long long total_instances = 0;

    std::function<void(int)> dfs = [&](int depth) {
        if (depth == pattern.n) {
            ++total_instances;
            if (print_mappings) {
                std::cout << "Mapping: ";
                for (int p = 0; p < pattern.n; ++p) {
                    if (p) std::cout << ' ';
                    std::cout << '(' << p << " -> " << map_p_to_t[p] << ')';
                }
                std::cout << '\n';
            }
            return;
        }

        const int p = order[depth];
        for (int t = 0; t < target.n; ++t) {
            if (used_t[t]) continue;
            if (pattern.label[p] != target.label[t]) continue;
            if (pattern.degree[p] > target.degree[t]) continue;

            bool ok = true;
            for (int i = 0; i < depth; ++i) {
                const int pp = order[i];
                const int tt = map_p_to_t[pp];
                if (has_edge(pattern, p, pp) && !has_edge(target, t, tt)) {
                    ok = false;
                    break;
                }
            }
            if (!ok) continue;

            used_t[t] = 1;
            map_p_to_t[p] = t;
            dfs(depth + 1);
            map_p_to_t[p] = -1;
            used_t[t] = 0;
        }
    };

    dfs(0);

    const auto done = std::chrono::high_resolution_clock::now();
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(done - started).count();
    std::cout << "solution_count=" << total_instances << '\n';
    std::cout << total_instances << '\n';
    std::cout << "Time: " << ms << '\n';
    return 0;
}
