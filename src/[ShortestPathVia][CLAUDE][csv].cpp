#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
#include <queue>
#include <limits>
#include <algorithm>

using namespace std;

static const long long INF = numeric_limits<long long>::max();

struct Edge {
    int to;
    long long w;
};

using Graph = vector<vector<Edge>>;

struct State {
    long long dist;
    int node;
    bool operator>(const State& o) const { return dist > o.dist; }
};

vector<long long> dijkstra(const Graph& g, int src, vector<int>& prev) {
    int n = g.size();
    vector<long long> d(n, INF);
    prev.assign(n, -1);
    d[src] = 0;
    priority_queue<State, vector<State>, greater<State>> pq;
    pq.push({0, src});
    while (!pq.empty()) {
        auto [dd, u] = pq.top(); pq.pop();
        if (dd > d[u]) continue;
        for (auto& e : g[u]) {
            if (d[u] + e.w < d[e.to]) {
                d[e.to] = d[u] + e.w;
                prev[e.to] = u;
                pq.push({d[e.to], e.to});
            }
        }
    }
    return d;
}

vector<int> reconstruct(const vector<int>& prev, int src, int dst) {
    vector<int> path;
    for (int v = dst; v != -1; v = prev[v]) {
        path.push_back(v);
        if (v == src) break;
    }
    reverse(path.begin(), path.end());
    if (path.empty() || path[0] != src) return {};
    return path;
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        cout << "INF; (no path)\n";
        return 0;
    }
    string filename = argv[1];
    string via_label = argv[2];

    ifstream fin(filename);
    if (!fin) {
        cout << "INF; (no path)\n";
        return 0;
    }

    string start_label, target_label;
    string line;

    // Parse header comment
    if (getline(fin, line)) {
        // # start=A target=E via=C
        auto get_val = [&](const string& key) -> string {
            string kk = key + "=";
            auto pos = line.find(kk);
            if (pos == string::npos) return "";
            pos += kk.size();
            auto end = line.find_first_of(" \t\r\n", pos);
            return line.substr(pos, end == string::npos ? string::npos : end - pos);
        };
        start_label = get_val("start");
        target_label = get_val("target");
        if (via_label.empty()) via_label = get_val("via");
    }

    // Skip CSV header
    getline(fin, line);

    // Node id mapping
    unordered_map<string, int> id_map;
    int node_count = 0;
    auto get_id = [&](const string& s) -> int {
        auto it = id_map.find(s);
        if (it != id_map.end()) return it->second;
        id_map[s] = node_count++;
        return node_count - 1;
    };

    // Pre-register known nodes
    get_id(start_label);
    get_id(target_label);
    get_id(via_label);

    // Read edges into a temp list
    vector<tuple<int,int,long long>> edges;
    while (getline(fin, line)) {
        if (line.empty() || line[0] == '#') continue;
        istringstream ss(line);
        string src_s, dst_s, w_s;
        if (!getline(ss, src_s, ',')) continue;
        if (!getline(ss, dst_s, ',')) continue;
        if (!getline(ss, w_s, ',')) continue;
        // trim
        auto trim = [](string& s) {
            size_t a = s.find_first_not_of(" \t\r\n");
            size_t b = s.find_last_not_of(" \t\r\n");
            s = (a == string::npos) ? "" : s.substr(a, b-a+1);
        };
        trim(src_s); trim(dst_s); trim(w_s);
        long long w = stoll(w_s);
        int u = get_id(src_s);
        int v = get_id(dst_s);
        edges.emplace_back(u, v, w);
    }

    // Build graph with minimum weight per arc
    // Use map to deduplicate
    unordered_map<long long, long long> arc_min;
    for (auto& [u, v, w] : edges) {
        long long key = (long long)u * 1000000LL + v;
        // handle node_count > 1000000
        // use a safer key
        auto it = arc_min.find((long long)u * node_count + v);
        if (it == arc_min.end()) arc_min[(long long)u * node_count + v] = w;
        else it->second = min(it->second, w);
    }

    Graph g(node_count);
    for (auto& [key, w] : arc_min) {
        int u = key / node_count;
        int v = key % node_count;
        g[u].push_back({v, w});
    }

    int start_id = id_map.count(start_label) ? id_map[start_label] : -1;
    int target_id = id_map.count(target_label) ? id_map[target_label] : -1;
    int via_id = id_map.count(via_label) ? id_map[via_label] : -1;

    if (start_id < 0 || target_id < 0 || via_id < 0) {
        cout << "INF; (no path)\n";
        return 0;
    }

    // Dijkstra from start
    vector<int> prev1;
    auto d1 = dijkstra(g, start_id, prev1);

    // Dijkstra from via
    vector<int> prev2;
    auto d2 = dijkstra(g, via_id, prev2);

    if (d1[via_id] == INF || d2[target_id] == INF) {
        cout << "INF; (no path)\n";
        return 0;
    }

    long long total = d1[via_id] + d2[target_id];

    // Reconstruct path: start -> via, then via -> target
    auto path1 = reconstruct(prev1, start_id, via_id);
    auto path2 = reconstruct(prev2, via_id, target_id);

    if (path1.empty() || path2.empty()) {
        cout << "INF; (no path)\n";
        return 0;
    }

    // Build reverse map
    vector<string> id_to_label(node_count);
    for (auto& [label, id] : id_map) id_to_label[id] = label;

    // Combine paths (avoid duplicating via node)
    cout << total << "; ";
    for (int i = 0; i < (int)path1.size(); i++) {
        if (i) cout << ' ';
        cout << id_to_label[path1[i]];
    }
    for (int i = 1; i < (int)path2.size(); i++) {
        cout << ' ' << id_to_label[path2[i]];
    }
    cout << '\n';

    return 0;
}