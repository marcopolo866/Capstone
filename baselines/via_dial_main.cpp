#include <algorithm>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <optional>
#include <queue>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <CXXGraph/Edge/DirectedWeightedEdge.h>
#include <CXXGraph/Graph/Graph.h>
#include <CXXGraph/Node/Node.h>

namespace {

constexpr long long INF_DIST = std::numeric_limits<long long>::max() / 4;
constexpr long long MAX_DIAL_BUCKETS = 5'000'000LL;

struct Edge {
    int to;
    int weight;
};

struct InputData {
    int start = -1;
    int target = -1;
    int via = -1;
    std::vector<std::vector<Edge>> adj;
    std::vector<std::vector<Edge>> rev_adj;
    std::vector<std::string> labels;
    int max_weight = 0;
    bool has_negative_weight = false;
};

struct ShortestPathResult {
    std::vector<long long> dist;
    std::vector<int> parent;
};

struct CxxGraphView {
    CXXGraph::Graph<int> graph;
    std::vector<std::shared_ptr<const CXXGraph::Node<int>>> nodes;
};

std::string trim(const std::string& s) {
    std::size_t a = 0;
    std::size_t b = s.size();
    while (a < b && std::isspace(static_cast<unsigned char>(s[a]))) {
        ++a;
    }
    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) {
        --b;
    }
    return s.substr(a, b - a);
}

std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    for (char c : line) {
        if (c == ';') {
            c = ',';
        }
        if (c == ',') {
            out.push_back(trim(cur));
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    out.push_back(trim(cur));
    return out;
}

std::optional<std::string> extract_key(const std::string& raw, const std::string& key) {
    std::string line = raw;
    std::transform(line.begin(), line.end(), line.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    std::size_t pos = line.find(key);
    if (pos == std::string::npos) {
        return std::nullopt;
    }
    pos += key.size();
    while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos]))) {
        ++pos;
    }
    if (pos >= line.size() || (line[pos] != '=' && line[pos] != ':')) {
        return std::nullopt;
    }
    ++pos;
    while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos]))) {
        ++pos;
    }
    std::size_t end = pos;
    while (end < raw.size() && raw[end] != ',' && raw[end] != ';' &&
           !std::isspace(static_cast<unsigned char>(raw[end]))) {
        ++end;
    }
    if (end <= pos) {
        return std::nullopt;
    }
    return trim(raw.substr(pos, end - pos));
}

InputData parse_input(const std::string& path, const std::string& via_cli) {
    std::ifstream in(path);
    if (!in.is_open()) {
        throw std::runtime_error("Failed to open input file: " + path);
    }

    std::unordered_map<std::string, int> id_of;
    std::vector<std::string> labels;
    std::vector<std::vector<Edge>> adj;

    auto get_id = [&](const std::string& label) {
        auto it = id_of.find(label);
        if (it != id_of.end()) {
            return it->second;
        }
        int id = static_cast<int>(id_of.size());
        id_of.emplace(label, id);
        labels.push_back(label);
        adj.emplace_back();
        return id;
    };

    std::optional<std::string> start_label;
    std::optional<std::string> target_label;
    std::optional<std::string> via_label;
    std::optional<std::string> first_source;
    std::optional<std::string> last_target;

    bool header_consumed = false;
    int max_weight = 0;
    bool has_negative_weight = false;
    std::string raw;
    while (std::getline(in, raw)) {
        std::string line = trim(raw);
        if (line.empty()) {
            continue;
        }
        if (!line.empty() && line[0] == '#') {
            std::string body = trim(line.substr(1));
            if (!start_label) {
                start_label = extract_key(body, "start");
            }
            if (!target_label) {
                target_label = extract_key(body, "target");
            }
            if (!target_label) {
                target_label = extract_key(body, "end");
            }
            if (!via_label) {
                via_label = extract_key(body, "via");
            }
            continue;
        }

        const std::size_t hash = line.find('#');
        if (hash != std::string::npos) {
            line = trim(line.substr(0, hash));
            if (line.empty()) {
                continue;
            }
        }

        std::vector<std::string> cells = split_csv(line);
        if (cells.size() != 3) {
            continue;
        }

        int weight = 0;
        try {
            std::size_t parsed = 0;
            weight = std::stoi(cells[2], &parsed);
            if (parsed != cells[2].size()) {
                throw std::invalid_argument("junk");
            }
        } catch (const std::exception&) {
            if (!header_consumed) {
                header_consumed = true;
                continue;
            }
            throw std::runtime_error("Invalid edge weight: " + cells[2]);
        }

        int u = get_id(cells[0]);
        int v = get_id(cells[1]);
        adj[u].push_back(Edge{v, weight});
        if (weight < 0) {
            has_negative_weight = true;
        } else if (weight > max_weight) {
            max_weight = weight;
        }
        if (!first_source) {
            first_source = cells[0];
        }
        last_target = cells[1];
    }

    if (labels.empty()) {
        throw std::runtime_error("No edges were parsed from input");
    }

    std::string start = start_label.value_or(first_source.value_or(std::string{}));
    std::string target = target_label.value_or(last_target.value_or(std::string{}));

    std::string via = via_cli;
    if (via.empty()) {
        via = via_label.value_or(std::string{});
    }
    if (via.empty()) {
        for (const std::string& label : labels) {
            if (label != start && label != target) {
                via = label;
                break;
            }
        }
    }

    auto it_start = id_of.find(start);
    auto it_target = id_of.find(target);
    auto it_via = id_of.find(via);
    if (it_start == id_of.end() || it_target == id_of.end()) {
        throw std::runtime_error("Start/target labels are missing from graph nodes");
    }
    if (it_via == id_of.end()) {
        throw std::runtime_error("Via label is missing from graph nodes: " + via);
    }

    InputData data;
    data.start = it_start->second;
    data.target = it_target->second;
    data.via = it_via->second;
    data.adj = std::move(adj);
    data.labels = std::move(labels);
    data.max_weight = max_weight;
    data.has_negative_weight = has_negative_weight;
    data.rev_adj.assign(static_cast<std::size_t>(id_of.size()), {});
    for (int u = 0; u < static_cast<int>(data.adj.size()); ++u) {
        for (const Edge& e : data.adj[u]) {
            if (e.to >= 0 && e.to < static_cast<int>(data.rev_adj.size())) {
                data.rev_adj[e.to].push_back(Edge{u, e.weight});
            }
        }
    }
    return data;
}

CxxGraphView build_cxxgraph(const InputData& input) {
    CxxGraphView view;
    view.nodes.reserve(input.labels.size());
    for (int i = 0; i < static_cast<int>(input.labels.size()); ++i) {
        view.nodes.push_back(std::make_shared<CXXGraph::Node<int>>(input.labels[i], i));
    }

    CXXGraph::T_EdgeSet<int> edge_set;
    std::size_t edge_id = 0;
    for (int u = 0; u < static_cast<int>(input.adj.size()); ++u) {
        for (const Edge& e : input.adj[u]) {
            if (e.to < 0 || e.to >= static_cast<int>(input.labels.size())) {
                continue;
            }
            edge_set.insert(std::make_shared<CXXGraph::DirectedWeightedEdge<int>>(
                std::to_string(edge_id++), view.nodes[u], view.nodes[e.to], static_cast<double>(e.weight)));
        }
    }
    view.graph = CXXGraph::Graph<int>(edge_set);
    return view;
}

ShortestPathResult run_dijkstra_fallback(const std::vector<std::vector<Edge>>& adj, int start) {
    const int n = static_cast<int>(adj.size());
    std::vector<long long> dist(n, INF_DIST);
    std::vector<int> parent(n, -1);
    using QItem = std::pair<long long, int>;
    std::priority_queue<QItem, std::vector<QItem>, std::greater<QItem>> pq;

    dist[start] = 0;
    pq.emplace(0, start);
    while (!pq.empty()) {
        auto [d, u] = pq.top();
        pq.pop();
        if (d != dist[u]) {
            continue;
        }
        for (const Edge& e : adj[u]) {
            long long nd = d + static_cast<long long>(e.weight);
            if (nd < dist[e.to]) {
                dist[e.to] = nd;
                parent[e.to] = u;
                pq.emplace(nd, e.to);
            }
        }
    }
    return {std::move(dist), std::move(parent)};
}

std::optional<std::vector<long long>> try_run_cxxgraph_dial(
    const InputData& input,
    const CxxGraphView& graph_view,
    int start) {
    if (input.has_negative_weight) {
        return std::nullopt;
    }

    const long long bucket_count =
        static_cast<long long>(std::max(1, input.max_weight)) * static_cast<long long>(input.labels.size());
    if (bucket_count <= 0 || bucket_count > MAX_DIAL_BUCKETS) {
        return std::nullopt;
    }

    const auto dial_result = graph_view.graph.dial(*graph_view.nodes[start], std::max(1, input.max_weight));
    if (!dial_result.success) {
        return std::nullopt;
    }

    std::vector<long long> dist(input.labels.size(), INF_DIST);
    for (int i = 0; i < static_cast<int>(input.labels.size()); ++i) {
        const auto it = dial_result.minDistanceMap.find(graph_view.nodes[i]->getId());
        if (it == dial_result.minDistanceMap.end()) {
            continue;
        }
        const long long value = static_cast<long long>(it->second);
        if (value >= 0 && value < INF_DIST) {
            dist[i] = value;
        }
    }
    dist[start] = 0;
    return dist;
}

std::vector<int> reconstruct_path_from_parent(int start, int target, const std::vector<int>& parent) {
    std::vector<int> path;
    for (int cur = target; cur != -1; cur = parent[cur]) {
        path.push_back(cur);
        if (cur == start) {
            break;
        }
    }
    if (path.empty() || path.back() != start) {
        return {};
    }
    std::reverse(path.begin(), path.end());
    return path;
}

std::vector<int> reconstruct_path_from_dist(
    int start,
    int target,
    const std::vector<long long>& dist,
    const std::vector<std::vector<Edge>>& rev_adj) {
    if (target < 0 || target >= static_cast<int>(dist.size()) || dist[target] >= INF_DIST) {
        return {};
    }
    std::vector<int> reverse_path;
    std::vector<char> seen(dist.size(), 0);
    int cur = target;
    while (true) {
        reverse_path.push_back(cur);
        if (cur == start) {
            break;
        }
        if (cur < 0 || cur >= static_cast<int>(rev_adj.size()) || seen[cur]) {
            return {};
        }
        seen[cur] = 1;

        int prev = -1;
        for (const Edge& incoming : rev_adj[cur]) {
            if (incoming.to < 0 || incoming.to >= static_cast<int>(dist.size())) {
                continue;
            }
            if (dist[incoming.to] >= INF_DIST) {
                continue;
            }
            if (dist[incoming.to] + static_cast<long long>(incoming.weight) == dist[cur]) {
                prev = incoming.to;
                break;
            }
        }
        if (prev == -1) {
            return {};
        }
        cur = prev;
    }
    std::reverse(reverse_path.begin(), reverse_path.end());
    return reverse_path;
}

std::pair<std::vector<long long>, std::vector<int>> run_shortest(
    const InputData& input,
    const CxxGraphView& graph_view,
    int start,
    int target) {
    const auto dial_dist = try_run_cxxgraph_dial(input, graph_view, start);
    if (dial_dist) {
        const std::vector<int> path = reconstruct_path_from_dist(start, target, *dial_dist, input.rev_adj);
        return {*dial_dist, path};
    }
    const ShortestPathResult fallback = run_dijkstra_fallback(input.adj, start);
    const std::vector<int> path = reconstruct_path_from_parent(start, target, fallback.parent);
    return {fallback.dist, path};
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input-file> [via-label]\n";
        return 1;
    }

    try {
        std::string via_cli = argc >= 3 ? std::string(argv[2]) : std::string();
        InputData in = parse_input(argv[1], via_cli);
        CxxGraphView graph_view = build_cxxgraph(in);

        auto [dist_s, path_s] = run_shortest(in, graph_view, in.start, in.via);
        auto [dist_v, path_v] = run_shortest(in, graph_view, in.via, in.target);

        if (dist_s[in.via] >= INF_DIST || dist_v[in.target] >= INF_DIST || path_s.empty() || path_v.empty()) {
            std::cout << "INF; (no path)\n";
            return 0;
        }

        std::vector<int> full = path_s;
        for (std::size_t i = 1; i < path_v.size(); ++i) {
            full.push_back(path_v[i]);
        }

        const long long total = dist_s[in.via] + dist_v[in.target];
        std::cout << total << ';';
        for (int node : full) {
            if (node < 0 || node >= static_cast<int>(in.labels.size())) {
                continue;
            }
            std::cout << ' ' << in.labels[node];
        }
        std::cout << "\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }
}
