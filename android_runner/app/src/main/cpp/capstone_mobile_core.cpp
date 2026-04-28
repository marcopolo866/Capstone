#include <jni.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <functional>
#include <limits>
#include <map>
#include <queue>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace {

struct Graph {
    std::vector<int> labels;
    std::vector<std::vector<int>> adj;
    std::vector<std::set<int>> edge_sets;
};

struct ShortestInput {
    std::string start;
    std::string target;
    std::string via;
    std::vector<std::tuple<std::string, std::string, int64_t>> edges;
};

std::string trim(const std::string& value) {
    size_t first = 0;
    while (first < value.size() && std::isspace(static_cast<unsigned char>(value[first]))) {
        ++first;
    }
    size_t last = value.size();
    while (last > first && std::isspace(static_cast<unsigned char>(value[last - 1]))) {
        --last;
    }
    return value.substr(first, last - first);
}

std::vector<std::string> split_ws(const std::string& line) {
    std::istringstream in(line);
    std::vector<std::string> out;
    std::string token;
    while (in >> token) {
        out.push_back(token);
    }
    return out;
}

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> out;
    std::string current;
    bool quoted = false;
    for (char ch : line) {
        if (ch == '"') {
            quoted = !quoted;
            continue;
        }
        if (ch == ',' && !quoted) {
            out.push_back(trim(current));
            current.clear();
        } else {
            current.push_back(ch);
        }
    }
    out.push_back(trim(current));
    return out;
}

std::string json_escape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 16);
    for (char ch : value) {
        switch (ch) {
            case '\\': out += "\\\\"; break;
            case '"': out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(ch) < 0x20) {
                    out += ' ';
                } else {
                    out.push_back(ch);
                }
        }
    }
    return out;
}

std::string ok_json(
    const std::string& stdout_text,
    const std::string& answer_kind,
    const std::string& answer_value,
    int64_t solution_count,
    const std::string& distance,
    int path_length
) {
    std::ostringstream out;
    out << "{"
        << "\"status\":\"ok\","
        << "\"stdout\":\"" << json_escape(stdout_text) << "\","
        << "\"stderr\":\"\","
        << "\"returnCode\":0,"
        << "\"answerKind\":\"" << json_escape(answer_kind) << "\","
        << "\"answerValue\":\"" << json_escape(answer_value) << "\","
        << "\"solutionCount\":" << solution_count << ","
        << "\"distance\":\"" << json_escape(distance) << "\","
        << "\"pathLength\":" << path_length
        << "}";
    return out.str();
}

std::string error_json(const std::string& message) {
    std::ostringstream out;
    out << "{"
        << "\"status\":\"failed\","
        << "\"stdout\":\"\","
        << "\"stderr\":\"" << json_escape(message) << "\","
        << "\"returnCode\":1,"
        << "\"answerKind\":\"\","
        << "\"answerValue\":\"\","
        << "\"solutionCount\":-1,"
        << "\"distance\":\"\","
        << "\"pathLength\":-1"
        << "}";
    return out.str();
}

std::string read_jstring(JNIEnv* env, jstring value) {
    if (value == nullptr) {
        return "";
    }
    const char* raw = env->GetStringUTFChars(value, nullptr);
    if (raw == nullptr) {
        return "";
    }
    std::string out(raw);
    env->ReleaseStringUTFChars(value, raw);
    return out;
}

Graph finalize_graph(Graph graph) {
    graph.edge_sets.assign(graph.adj.size(), {});
    for (size_t u = 0; u < graph.adj.size(); ++u) {
        std::sort(graph.adj[u].begin(), graph.adj[u].end());
        graph.adj[u].erase(std::unique(graph.adj[u].begin(), graph.adj[u].end()), graph.adj[u].end());
        for (int v : graph.adj[u]) {
            if (v >= 0 && static_cast<size_t>(v) < graph.adj.size() && static_cast<int>(u) != v) {
                graph.edge_sets[u].insert(v);
            }
        }
    }
    return graph;
}

Graph parse_vf_or_grf(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("Unable to open graph file: " + path);
    }
    int n = 0;
    in >> n;
    if (n <= 0) {
        throw std::runtime_error("Invalid graph vertex count in: " + path);
    }
    Graph graph;
    graph.labels.assign(n, 1);
    graph.adj.assign(n, {});
    for (int i = 0; i < n; ++i) {
        int id = 0;
        int label = 1;
        in >> id >> label;
        if (id < 0 || id >= n) {
            throw std::runtime_error("Invalid labelled vertex row in: " + path);
        }
        graph.labels[id] = label;
    }
    for (int i = 0; i < n; ++i) {
        int degree = 0;
        in >> degree;
        if (degree < 0) {
            throw std::runtime_error("Invalid degree in: " + path);
        }
        for (int j = 0; j < degree; ++j) {
            int u = 0;
            int v = 0;
            in >> u >> v;
            if (u >= 0 && u < n && v >= 0 && v < n && u != v) {
                graph.adj[u].push_back(v);
                graph.adj[v].push_back(u);
            }
        }
    }
    return finalize_graph(std::move(graph));
}

Graph parse_lad(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("Unable to open LAD file: " + path);
    }
    std::string line;
    if (!std::getline(in, line)) {
        throw std::runtime_error("Empty LAD file: " + path);
    }
    int n = std::stoi(trim(line));
    if (n <= 0) {
        throw std::runtime_error("Invalid LAD vertex count in: " + path);
    }
    Graph graph;
    graph.labels.assign(n, 1);
    graph.adj.assign(n, {});
    for (int i = 0; i < n; ++i) {
        if (!std::getline(in, line)) {
            throw std::runtime_error("Truncated LAD file: " + path);
        }
        std::vector<std::string> tokens = split_ws(line);
        if (tokens.empty()) {
            continue;
        }
        int cursor = 0;
        int label = 1;
        int degree = 0;
        if (tokens.size() >= 2) {
            int maybe_degree = std::stoi(tokens[1]);
            if (maybe_degree >= 0 && static_cast<size_t>(maybe_degree + 2) == tokens.size()) {
                label = std::stoi(tokens[0]);
                degree = maybe_degree;
                cursor = 2;
            } else {
                degree = std::stoi(tokens[0]);
                cursor = 1;
            }
        } else {
            degree = std::stoi(tokens[0]);
            cursor = 1;
        }
        graph.labels[i] = label;
        for (int j = 0; j < degree && cursor < static_cast<int>(tokens.size()); ++j, ++cursor) {
            int v = std::stoi(tokens[cursor]);
            if (v >= 0 && v < n && v != i) {
                graph.adj[i].push_back(v);
                graph.adj[v].push_back(i);
            }
        }
    }
    return finalize_graph(std::move(graph));
}

int64_t count_subgraph_embeddings(const Graph& pattern, const Graph& target) {
    const int p = static_cast<int>(pattern.adj.size());
    const int t = static_cast<int>(target.adj.size());
    if (p <= 0 || t <= 0 || p > t) {
        return 0;
    }
    std::vector<int> order(p);
    for (int i = 0; i < p; ++i) {
        order[i] = i;
    }
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        if (pattern.adj[a].size() != pattern.adj[b].size()) {
            return pattern.adj[a].size() > pattern.adj[b].size();
        }
        return pattern.labels[a] < pattern.labels[b];
    });

    std::vector<int> assigned(p, -1);
    std::vector<char> used(t, 0);
    int64_t count = 0;

    auto compatible = [&](int pv, int tv) {
        if (pattern.labels[pv] != target.labels[tv]) {
            return false;
        }
        if (pattern.adj[pv].size() > target.adj[tv].size()) {
            return false;
        }
        for (int other_p = 0; other_p < p; ++other_p) {
            int other_t = assigned[other_p];
            if (other_t < 0) {
                continue;
            }
            if (pattern.edge_sets[pv].count(other_p) && !target.edge_sets[tv].count(other_t)) {
                return false;
            }
        }
        return true;
    };

    std::function<void(int)> dfs = [&](int depth) {
        if (depth == p) {
            ++count;
            return;
        }
        int pv = order[depth];
        for (int tv = 0; tv < t; ++tv) {
            if (used[tv]) {
                continue;
            }
            if (!compatible(pv, tv)) {
                continue;
            }
            assigned[pv] = tv;
            used[tv] = 1;
            dfs(depth + 1);
            used[tv] = 0;
            assigned[pv] = -1;
        }
    };
    dfs(0);
    return count;
}

ShortestInput parse_shortest_csv(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("Unable to open CSV file: " + path);
    }
    ShortestInput input;
    std::string line;
    bool header_seen = false;
    while (std::getline(in, line)) {
        std::string stripped = trim(line);
        if (stripped.empty()) {
            continue;
        }
        if (stripped[0] == '#') {
            std::istringstream parts(stripped.substr(1));
            std::string token;
            while (parts >> token) {
                size_t eq = token.find('=');
                if (eq == std::string::npos) {
                    continue;
                }
                std::string key = token.substr(0, eq);
                std::string value = token.substr(eq + 1);
                if (key == "start") input.start = value;
                if (key == "target") input.target = value;
                if (key == "via") input.via = value;
            }
            continue;
        }
        std::vector<std::string> cols = split_csv_line(stripped);
        if (!header_seen) {
            header_seen = true;
            if (cols.size() >= 3 && cols[0] == "source") {
                continue;
            }
        }
        if (cols.size() < 3) {
            continue;
        }
        int64_t weight = std::stoll(cols[2]);
        input.edges.emplace_back(cols[0], cols[1], weight);
        if (input.start.empty()) {
            input.start = cols[0];
        }
        input.target = cols[1];
    }
    if (input.start.empty() || input.target.empty()) {
        throw std::runtime_error("CSV input has no usable start/target labels: " + path);
    }
    return input;
}

std::pair<int64_t, std::vector<int>> dijkstra_path(
    const std::vector<std::vector<std::pair<int, int64_t>>>& adj,
    int start,
    int target
) {
    const int n = static_cast<int>(adj.size());
    const int64_t inf = std::numeric_limits<int64_t>::max() / 4;
    std::vector<int64_t> dist(n, inf);
    std::vector<int> parent(n, -1);
    using Item = std::pair<int64_t, int>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> pq;
    dist[start] = 0;
    pq.push({0, start});
    while (!pq.empty()) {
        auto [d, u] = pq.top();
        pq.pop();
        if (d != dist[u]) continue;
        if (u == target) break;
        for (auto [v, w] : adj[u]) {
            if (w < 0) continue;
            int64_t nd = d + w;
            if (nd < dist[v]) {
                dist[v] = nd;
                parent[v] = u;
                pq.push({nd, v});
            }
        }
    }
    if (dist[target] >= inf) {
        return {inf, {}};
    }
    std::vector<int> path;
    for (int v = target; v >= 0; v = parent[v]) {
        path.push_back(v);
        if (v == start) break;
    }
    std::reverse(path.begin(), path.end());
    return {dist[target], path};
}

std::string run_shortest(const std::string& family, const std::string& input_path) {
    ShortestInput input = parse_shortest_csv(input_path);
    std::map<std::string, int> ids;
    std::vector<std::string> labels;
    auto id_for = [&](const std::string& label) {
        auto found = ids.find(label);
        if (found != ids.end()) return found->second;
        int id = static_cast<int>(ids.size());
        ids[label] = id;
        labels.push_back(label);
        return id;
    };
    for (const auto& [u, v, _w] : input.edges) {
        id_for(u);
        id_for(v);
    }
    int start_id = id_for(input.start);
    int target_id = id_for(input.target);
    int via_id = input.via.empty() ? -1 : id_for(input.via);
    std::vector<std::vector<std::pair<int, int64_t>>> adj(ids.size());
    for (const auto& [u, v, w] : input.edges) {
        adj[ids[u]].push_back({ids[v], w});
    }
    const int64_t inf = std::numeric_limits<int64_t>::max() / 4;
    int64_t total = 0;
    std::vector<int> path;
    if (family == "sp_via" && via_id >= 0) {
        auto first = dijkstra_path(adj, start_id, via_id);
        auto second = dijkstra_path(adj, via_id, target_id);
        if (first.first >= inf || second.first >= inf) {
            total = inf;
        } else {
            total = first.first + second.first;
            path = first.second;
            if (!second.second.empty()) {
                path.insert(path.end(), second.second.begin() + 1, second.second.end());
            }
        }
    } else {
        auto result = dijkstra_path(adj, start_id, target_id);
        total = result.first;
        path = result.second;
    }
    std::ostringstream stdout_text;
    std::string distance = total >= inf ? "unreachable" : std::to_string(total);
    stdout_text << "Distance: " << distance << "\n";
    if (!path.empty()) {
        stdout_text << "Path:";
        for (int id : path) {
            stdout_text << " " << labels[id];
        }
        stdout_text << "\n";
    }
    return ok_json(stdout_text.str(), "distance", distance, -1, distance, static_cast<int>(std::max<size_t>(0, path.size() > 0 ? path.size() - 1 : 0)));
}

std::string run_subgraph(const std::string& variant_id, const std::string& pattern_path, const std::string& target_path) {
    std::string lower = variant_id;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    Graph pattern = lower.find("glasgow") != std::string::npos ? parse_lad(pattern_path) : parse_vf_or_grf(pattern_path);
    Graph target = lower.find("glasgow") != std::string::npos ? parse_lad(target_path) : parse_vf_or_grf(target_path);
    int64_t count = count_subgraph_embeddings(pattern, target);
    std::ostringstream stdout_text;
    stdout_text << "Solution count: " << count << "\n";
    return ok_json(stdout_text.str(), "solution_count", std::to_string(count), count, "", -1);
}

}  // namespace

extern "C" JNIEXPORT jstring JNICALL
Java_edu_uidaho_capstone_androidrunner_engine_CapstoneNative_runSolver(
    JNIEnv* env,
    jclass,
    jstring variant_id_j,
    jstring family_j,
    jstring input_a_j,
    jstring input_b_j,
    jstring lad_format_j
) {
    (void)lad_format_j;
    try {
        std::string variant_id = read_jstring(env, variant_id_j);
        std::string family = read_jstring(env, family_j);
        std::string input_a = read_jstring(env, input_a_j);
        std::string input_b = read_jstring(env, input_b_j);

        std::string result;
        if (family == "dijkstra" || family == "sp_via") {
            result = run_shortest(family, input_a);
        } else if (family == "vf3" || family == "glasgow") {
            result = run_subgraph(variant_id, input_a, input_b);
        } else {
            result = error_json("Unsupported solver family: " + family);
        }
        return env->NewStringUTF(result.c_str());
    } catch (const std::exception& exc) {
        std::string result = error_json(exc.what());
        return env->NewStringUTF(result.c_str());
    } catch (...) {
        std::string result = error_json("Unknown native solver failure");
        return env->NewStringUTF(result.c_str());
    }
}
