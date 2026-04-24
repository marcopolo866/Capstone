#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
#include <queue>
#include <limits>
#include <algorithm>

int main(int argc, char* argv[]) {
    if (argc < 2) return 1;

    std::ifstream f(argv[1]);
    if (!f) return 1;

    std::string line, start_label, target_label;

    // Parse header comment
    if (!std::getline(f, line)) return 1;
    {
        auto sp = line.find("start=");
        auto tp = line.find("target=");
        if (sp == std::string::npos || tp == std::string::npos) return 1;
        sp += 6;
        auto sp_end = line.find(' ', sp);
        start_label = line.substr(sp, sp_end == std::string::npos ? std::string::npos : sp_end - sp);
        tp += 7;
        auto tp_end = line.find(' ', tp);
        target_label = line.substr(tp, tp_end == std::string::npos ? std::string::npos : tp_end - tp);
        // trim
        while (!start_label.empty() && (start_label.back() == '\r' || start_label.back() == ' ')) start_label.pop_back();
        while (!target_label.empty() && (target_label.back() == '\r' || target_label.back() == ' ')) target_label.pop_back();
    }

    // Skip CSV header
    std::getline(f, line);

    std::unordered_map<std::string, int> node_id;
    std::vector<std::vector<std::pair<int,int>>> adj;

    auto get_id = [&](const std::string& s) -> int {
        auto it = node_id.find(s);
        if (it != node_id.end()) return it->second;
        int id = (int)adj.size();
        node_id[s] = id;
        adj.push_back({});
        return id;
    };

    // Store raw edges to handle duplicates
    std::unordered_map<long long, int> edge_min;

    while (std::getline(f, line)) {
        if (line.empty()) continue;
        if (line.back() == '\r') line.pop_back();
        auto c1 = line.find(',');
        if (c1 == std::string::npos) continue;
        auto c2 = line.find(',', c1 + 1);
        if (c2 == std::string::npos) continue;
        std::string src = line.substr(0, c1);
        std::string tgt = line.substr(c1 + 1, c2 - c1 - 1);
        int w = std::stoi(line.substr(c2 + 1));
        int sid = get_id(src);
        int tid = get_id(tgt);
        long long key = (long long)sid * 2000000LL + tid;
        auto it = edge_min.find(key);
        if (it == edge_min.end()) edge_min[key] = w;
        else it->second = std::min(it->second, w);
    }

    // Build adjacency list from deduped edges
    for (auto& [key, w] : edge_min) {
        int sid = (int)(key / 2000000LL);
        int tid = (int)(key % 2000000LL);
        adj[sid].push_back({tid, w});
    }

    int n = (int)adj.size();
    auto sit = node_id.find(start_label);
    auto tit = node_id.find(target_label);

    if (sit == node_id.end() || tit == node_id.end()) {
        std::cout << "INF; (no path)\n";
        return 0;
    }

    int S = sit->second, T = tit->second;
    const long long INF = std::numeric_limits<long long>::max();
    std::vector<long long> dist(n, INF);
    std::vector<int> prev(n, -1);
    dist[S] = 0;

    using pli = std::pair<long long, int>;
    std::priority_queue<pli, std::vector<pli>, std::greater<pli>> pq;
    pq.push({0, S});

    while (!pq.empty()) {
        auto [d, u] = pq.top(); pq.pop();
        if (d > dist[u]) continue;
        if (u == T) break;
        for (auto [v, w] : adj[u]) {
            long long nd = d + w;
            if (nd < dist[v]) {
                dist[v] = nd;
                prev[v] = u;
                pq.push({nd, v});
            }
        }
    }

    if (dist[T] == INF) {
        std::cout << "INF; (no path)\n";
    } else {
        std::vector<int> path;
        for (int v = T; v != -1; v = prev[v]) path.push_back(v);
        std::reverse(path.begin(), path.end());
        // Build reverse map
        std::vector<std::string> id_to_name(n);
        for (auto& [name, id] : node_id) id_to_name[id] = name;
        std::cout << dist[T] << "; ";
        for (int i = 0; i < (int)path.size(); i++) {
            if (i) std::cout << ' ';
            std::cout << id_to_name[path[i]];
        }
        std::cout << '\n';
    }
    return 0;
}