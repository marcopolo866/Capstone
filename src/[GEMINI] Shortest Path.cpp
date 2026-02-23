/*
Prompt was given with djiskstas_weighted_graph_1.csv and djiskstas_weighted_graph_2.csv for reference

PROMPT USED:
Write a program in C++ that finds the shortest path from a starting node to an ending node that can take inputs like the provided files.
Input files will look very similar to this. The key idea is the fastest runtime as possible, so take every shortcut possible. 
Just output the code as a block to copy and paste, nothing else. Also be sure to output how long the program took to run as precise as possible without losing accuracy.

The output should only be two lines:
<The weight of the path>; <the path taken>
"Runtime:" <time the program ran precisely>
*/

#include <iostream>
#include <vector>
#include <string>
#include <queue>
#include <unordered_map>
#include <chrono>
#include <algorithm>
#include <sstream>

using namespace std;

/**
 * Dijkstra's algorithm implementation optimized for performance.
 * This program reads a weighted graph from a CSV-like format and outputs the shortest path.
 */

struct Edge {
    int to;
    int weight;
};

struct State {
    int u;
    long long dist;
    bool operator>(const State& other) const {
        return dist > other.dist;
    }
};

int main() {
    // Start timing as early as possible
    auto start_time = chrono::high_resolution_clock::now();

    // Fast I/O
    ios::sync_with_stdio(false);
    cin.tie(NULL);

    string line;
    if (!getline(cin, line)) return 0;

    // Parse the metadata line: # start=A target=C
    string start_node_name, target_node_name;
    size_t s_idx = line.find("start=");
    size_t t_idx = line.find("target=");
    if (s_idx != string::npos && t_idx != string::npos) {
        size_t s_end = line.find_first_of(" \r\n", s_idx);
        start_node_name = line.substr(s_idx + 6, s_end - (s_idx + 6));
        size_t t_end = line.find_first_of(" \r\n", t_idx);
        target_node_name = line.substr(t_idx + 7, t_end - (t_idx + 7));
    }

    // Skip the header line (e.g., source,target,weight)
    getline(cin, line);

    unordered_map<string, int> name_to_id;
    vector<string> id_to_name;
    auto get_id = [&](const string& name) {
        auto it = name_to_id.find(name);
        if (it == name_to_id.end()) {
            int id = (int)id_to_name.size();
            id_to_name.push_back(name);
            return name_to_id[name] = id;
        }
        return it->second;
    };

    vector<vector<Edge>> adj;
    while (getline(cin, line)) {
        if (line.empty() || line[0] == '\r' || line[0] == '\n') continue;
        
        size_t c1 = line.find(',');
        size_t c2 = line.find(',', c1 + 1);
        if (c1 == string::npos || c2 == string::npos) continue;

        string u_name = line.substr(0, c1);
        string v_name = line.substr(c1 + 1, c2 - c1 - 1);
        int weight = stoi(line.substr(c2 + 1));

        int u = get_id(u_name);
        int v = get_id(v_name);

        if (max(u, v) >= (int)adj.size()) adj.resize(max(u, v) + 1);
        adj[u].push_back({v, weight});
    }

    int start_id = name_to_id[start_node_name];
    int target_id = name_to_id[target_node_name];

    int n = (int)id_to_name.size();
    vector<long long> dist(n, -1);
    vector<int> parent(n, -1);
    priority_queue<State, vector<State>, greater<State>> pq;

    dist[start_id] = 0;
    pq.push({start_id, 0});

    while (!pq.empty()) {
        State top = pq.top();
        pq.pop();

        if (dist[top.u] != -1 && top.dist > dist[top.u]) continue;
        if (top.u == target_id) break;

        for (const auto& e : adj[top.u]) {
            if (dist[e.to] == -1 || dist[top.u] + e.weight < dist[e.to]) {
                dist[e.to] = dist[top.u] + e.weight;
                parent[e.to] = top.u;
                pq.push({e.to, dist[e.to]});
            }
        }
    }

    // Output Path and Weight
    if (dist[target_id] == -1) {
        cout << "-1; Path not found" << endl;
    } else {
        vector<int> path;
        for (int v = target_id; v != -1; v = parent[v]) path.push_back(v);
        reverse(path.begin(), path.end());

        cout << dist[target_id] << ";";
        for (int i = 0; i < (int)path.size(); ++i) {
            cout << " " << id_to_name[path[i]];
        }
        cout << endl;
    }

    // Measure and output precise runtime
    auto end_time = chrono::high_resolution_clock::now();
    chrono::duration<double> duration = end_time - start_time;
    cout << "Runtime: " << fixed << duration.count() << "s" << endl;

    return 0;
}