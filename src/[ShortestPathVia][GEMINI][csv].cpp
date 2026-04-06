#include <algorithm>
#include <cctype>
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

namespace {

struct Edge {
    int to;
    int weight;
};

struct InputData {
    int start = -1;
    int target = -1;
    int via = -1;
    std::vector<std::vector<Edge>> adj;
    std::vector<std::string> labels;
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
    while (end < raw.size() && raw[end] != ',' && raw[end] != ';' && !std::isspace(static_cast<unsigned char>(raw[end]))) {
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
    return data;
}

std::pair<std::vector<long long>, std::vector<int>> run_shortest(const std::vector<std::vector<Edge>>& adj, int start) {
    const long long INF = std::numeric_limits<long long>::max() / 4;
    const int n = static_cast<int>(adj.size());
    std::vector<long long> dist(n, INF);
    std::vector<int> parent(n, -1);

    int max_w = 0;
    for (const auto& row : adj) {
        for (const Edge& e : row) {
            if (e.weight < 0) {
                using QItem = std::pair<long long, int>;
                std::priority_queue<QItem, std::vector<QItem>, std::greater<QItem>> pq;
                dist.assign(n, INF);
                parent.assign(n, -1);
                dist[start] = 0;
                pq.emplace(0, start);
                while (!pq.empty()) {
                    auto [d, u] = pq.top();
                    pq.pop();
                    if (d != dist[u]) {
                        continue;
                    }
                    for (const Edge& de : adj[u]) {
                        long long nd = d + static_cast<long long>(de.weight);
                        if (nd < dist[de.to]) {
                            dist[de.to] = nd;
                            parent[de.to] = u;
                            pq.emplace(nd, de.to);
                        }
                    }
                }
                return {std::move(dist), std::move(parent)};
            }
            if (e.weight > max_w) {
                max_w = e.weight;
            }
        }
    }

    dist[start] = 0;
    std::vector<std::vector<int>> buckets(1);
    buckets[0].push_back(start);
    std::size_t current = 0;

    while (current < buckets.size()) {
        while (current < buckets.size() && buckets[current].empty()) {
            ++current;
        }
        if (current >= buckets.size()) {
            break;
        }
        int u = buckets[current].back();
        buckets[current].pop_back();
        if (dist[u] != static_cast<long long>(current)) {
            continue;
        }
        for (const Edge& e : adj[u]) {
            long long nd = dist[u] + static_cast<long long>(e.weight);
            if (nd < dist[e.to]) {
                if (nd > 5000000) {
                    using QItem = std::pair<long long, int>;
                    std::priority_queue<QItem, std::vector<QItem>, std::greater<QItem>> pq;
                    dist.assign(n, INF);
                    parent.assign(n, -1);
                    dist[start] = 0;
                    pq.emplace(0, start);
                    while (!pq.empty()) {
                        auto [d, x] = pq.top();
                        pq.pop();
                        if (d != dist[x]) {
                            continue;
                        }
                        for (const Edge& de : adj[x]) {
                            long long d2 = d + static_cast<long long>(de.weight);
                            if (d2 < dist[de.to]) {
                                dist[de.to] = d2;
                                parent[de.to] = x;
                                pq.emplace(d2, de.to);
                            }
                        }
                    }
                    return {std::move(dist), std::move(parent)};
                }
                dist[e.to] = nd;
                parent[e.to] = u;
                std::size_t bi = static_cast<std::size_t>(nd);
                if (bi >= buckets.size()) {
                    buckets.resize(bi + 1);
                }
                buckets[bi].push_back(e.to);
            }
        }
    }

    return {std::move(dist), std::move(parent)};
}

std::vector<int> reconstruct_path(int start, int target, const std::vector<int>& parent) {
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

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input-file> [via-label]\n";
        return 1;
    }

    try {
        std::string via_cli = argc >= 3 ? std::string(argv[2]) : std::string();
        InputData in = parse_input(argv[1], via_cli);
        auto [dist_s, parent_s] = run_shortest(in.adj, in.start);
        auto [dist_v, parent_v] = run_shortest(in.adj, in.via);

        const long long INF = std::numeric_limits<long long>::max() / 4;
        if (dist_s[in.via] >= INF || dist_v[in.target] >= INF) {
            std::cout << "INF; (no path)\n";
            return 0;
        }

        std::vector<int> p1 = reconstruct_path(in.start, in.via, parent_s);
        std::vector<int> p2 = reconstruct_path(in.via, in.target, parent_v);
        if (p1.empty() || p2.empty()) {
            std::cout << "INF; (no path)\n";
            return 0;
        }

        std::vector<int> full = p1;
        for (std::size_t i = 1; i < p2.size(); ++i) {
            full.push_back(p2[i]);
        }

        long long total = dist_s[in.via] + dist_v[in.target];
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
