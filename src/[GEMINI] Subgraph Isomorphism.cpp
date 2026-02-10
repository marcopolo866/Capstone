/**
 *  Prompt:
    Write a program in C++ that, given a large target graph, can find all instances of a smaller 
    pattern within it, or otherwise confirm there are no instances inputs like the provided files, 
    should work with both .lad and .grf files. Input files will look very similar to this. The key idea is the 
    fastest runtime as possible, so take every shortcut possible. Just output the code as a block to copy and paste, nothing else. 
    Also be sure to output how long the program took to run as precise as possible without losing accuracy in milliseconds.
    The code should also be as portable and universal as possible, so use common C++ libraries.   
    The output should only be these lines:  
    The nodes of the target graph that create the pattern, if multiple, one numbered list on each line if possible, otherwise wraparound with brackets. 
    How many instances exist of the smaller graph in the bigger target graph as a whole integer number
    The last line should be the execution time of the program in milliseconds.
*/

/*
 * Subgraph Isomorphism Solver (VF2-Light approach)
 * Supports .lad and .grf formats.
 * Optimized for speed: Fast I/O, Adjacency sorting, heuristic matching order.
 */

#include <iostream>
#include <vector>
#include <fstream>
#include <sstream>
#include <string>
#include <chrono>
#include <algorithm>
#include <iomanip>
#include <numeric>

using namespace std;

static inline bool is_blank_or_comment_line(const string& line) {
    const auto pos = line.find_first_not_of(" \t\r\n");
    if (pos == string::npos) {
        return true;
    }
    return line[pos] == '#';
}

// --- Graph Structure ---
struct Graph {
    int n;
    // Node labels: needed for .grf, default 0 for .lad
    vector<int> label;
    // Adjacency lists (outgoing)
    vector<vector<int>> adj;
    // Inverse adjacency (incoming) - crucial for directed checking
    vector<vector<int>> radj;

    Graph(int nodes) : n(nodes), label(nodes, 0), adj(nodes), radj(nodes) {}

    void add_edge(int u, int v) {
        if (u >= n || v >= n) return;
        adj[u].push_back(v);
        radj[v].push_back(u);
    }

    void sort_edges() {
        for (auto& neighbors : adj) sort(neighbors.begin(), neighbors.end());
        for (auto& neighbors : radj) sort(neighbors.begin(), neighbors.end());
    }

    bool has_edge(int u, int v) const {
        const auto& neighbors = adj[u];
        return binary_search(neighbors.begin(), neighbors.end(), v);
    }
};

// --- Parsers ---

bool is_grf(const string& filename) {
    return filename.length() >= 4 && filename.substr(filename.length() - 4) == ".grf";
}

bool is_vf(const string& filename) {
    return filename.length() >= 3 && filename.substr(filename.length() - 3) == ".vf";
}

Graph parse_lad(const string& filename) {
    ifstream f(filename);
    if (!f) { cerr << "Error opening " << filename << endl; exit(1); }
    
    int n;
    f >> n;
    Graph g(n);

    vector<vector<int>> adj(n);
    
    // .lad format: lines of "degree neighbor neighbor ..."
    // Treat LAD as undirected adjacency lists.
    for (int i = 0; i < n; ++i) {
        int deg;
        f >> deg;
        for (int k = 0; k < deg; ++k) {
            int neighbor;
            f >> neighbor;
            if (neighbor >= 0 && neighbor < n) {
                adj[i].push_back(neighbor);
            }
        }
    }

    for (int u = 0; u < n; ++u) {
        for (int v : adj[u]) {
            if (v >= 0 && v < n) {
                adj[v].push_back(u);
            }
        }
    }

    g.adj.assign(n, {});
    g.radj.assign(n, {});
    for (int i = 0; i < n; ++i) {
        auto& vec = adj[i];
        sort(vec.begin(), vec.end());
        vec.erase(unique(vec.begin(), vec.end()), vec.end());
        g.adj[i] = vec;
        g.radj[i] = vec;
    }
    return g;
}

Graph parse_vf(const string& filename) {
    ifstream f(filename);
    if (!f) { cerr << "Error opening " << filename << endl; exit(1); }

    string line;
    int n = 0;
    while (getline(f, line)) {
        if (is_blank_or_comment_line(line)) continue;
        stringstream ss(line);
        if (ss >> n) break;
    }

    Graph g(n);

    // Read node labels: "id label"
    int read_nodes = 0;
    while (read_nodes < n && getline(f, line)) {
        if (is_blank_or_comment_line(line)) continue;
        stringstream ss(line);
        int id, lbl;
        if (!(ss >> id >> lbl)) continue;
        if (id >= 0 && id < n) {
            g.label[id] = lbl;
            read_nodes++;
        }
    }

    // Read edges: for each node, line with edge count, then that many "src dst attr" lines
    for (int i = 0; i < n; ++i) {
        int edge_count = 0;
        while (getline(f, line)) {
            if (is_blank_or_comment_line(line)) continue;
            stringstream ss(line);
            if (ss >> edge_count) break;
        }

        for (int k = 0; k < edge_count; ++k) {
            if (!getline(f, line)) break;
            if (is_blank_or_comment_line(line)) { k--; continue; }
            stringstream ss(line);
            int u, v;
            if (!(ss >> u >> v)) continue;
            if (u >= 0 && u < n && v >= 0 && v < n) {
                g.add_edge(u, v);
            }
        }
    }

    g.sort_edges();
    return g;
}

Graph parse_grf(const string& filename) {
    ifstream f(filename);
    if (!f) { cerr << "Error opening " << filename << endl; exit(1); }
    
    // Skip comments/headers if any, but prompt format implies straight data often.
    // However, prompt example shows:
    // # Number of nodes
    // 3
    // We need to handle potential headers.
    
    string line;
    int n = 0;
    
    // Find number of nodes
    while (getline(f, line)) {
        if (is_blank_or_comment_line(line)) continue;
        stringstream ss(line);
        if (ss >> n) break;
    }
    
    Graph g(n);
    
    // Read Node Labels: "id label"
    for (int i = 0; i < n; ++i) {
        // Skip comments
        while (getline(f, line)) {
            if (is_blank_or_comment_line(line)) continue;
            break;
        }
        stringstream ss(line);
        int id, lbl;
        ss >> id >> lbl;
        g.label[id] = lbl;
    }
    
    // Read Edges
    // Format: For each node, Read edge count E, then E lines of "src tgt"
    for (int i = 0; i < n; ++i) {
        int edge_count = 0;
        while (getline(f, line)) {
            if (is_blank_or_comment_line(line)) continue;
            break;
        }
        stringstream ss(line);
        ss >> edge_count;
        
        for (int k = 0; k < edge_count; ++k) {
            int u, v;
            f >> u >> v;
            g.add_edge(u, v);
        }
    }
    g.sort_edges();
    return g;
}

Graph load_graph(const string& filename) {
    if (is_vf(filename)) return parse_vf(filename);
    if (is_grf(filename)) return parse_grf(filename);
    return parse_lad(filename);
}

// --- Solver State ---

struct State {
    int core_len; // Number of nodes matched so far
    vector<int> core_1; // Mapping Pattern -> Target
    vector<int> core_2; // Mapping Target -> Pattern
    vector<bool> used_target; // Bitset for used targets
    
    State(int n_pattern, int n_target) 
        : core_len(0), 
          core_1(n_pattern, -1), 
          core_2(n_target, -1), 
          used_target(n_target, false) {}
};

long long match_count = 0;
bool first_only_mode = false;
bool induced_mode = true;
double first_solution_sec = -1.0;
chrono::steady_clock::time_point solve_start_time;

// --- Feasibility Check ---

bool check_feasibility(const Graph& pat, const Graph& tar, int u, int v, const State& s) {
    // 1. Label Check
    if (pat.label[u] != tar.label[v]) return false;
    
    // 2. Loop Check (Self-loops)
    bool u_self = pat.has_edge(u, u);
    bool v_self = tar.has_edge(v, v);
    if (induced_mode) {
        if (u_self != v_self) return false;
    } else {
        if (u_self && !v_self) return false;
    }

    // 3. Adjacency Consistency (induced) with already mapped nodes
    for (int u_mapped = 0; u_mapped < pat.n; ++u_mapped) {
        int v_mapped = s.core_1[u_mapped];
        if (v_mapped == -1) continue;
        if (u_mapped == u) continue;

        bool pat_out = pat.has_edge(u, u_mapped);
        bool tar_out = tar.has_edge(v, v_mapped);
        if (induced_mode) {
            if (pat_out != tar_out) return false;
        } else {
            if (pat_out && !tar_out) return false;
        }

        bool pat_in = pat.has_edge(u_mapped, u);
        bool tar_in = tar.has_edge(v_mapped, v);
        if (induced_mode) {
            if (pat_in != tar_in) return false;
        } else {
            if (pat_in && !tar_in) return false;
        }
    }
    
    // 4. Lookahead / Degree filtering (Shortcut)
    // The target node v must have at least as many neighbors as u
    if (tar.adj[v].size() < pat.adj[u].size()) return false;
    if (tar.radj[v].size() < pat.radj[u].size()) return false;

    return true;
}

// --- Recursive Solver ---

void solve(const Graph& pat, const Graph& tar, State& s, const vector<int>& order) {
    if (first_only_mode && match_count > 0) {
        return;
    }
    if (s.core_len == pat.n) {
        if (match_count == 0) {
            auto now = chrono::steady_clock::now();
            first_solution_sec = chrono::duration<double>(now - solve_start_time).count();
        }
        match_count++;
        return;
    }

    int u = order[s.core_len]; // Get next pattern node from heuristic order

    // Candidate selection: 
    // Optimization: If u is connected to a previously matched node u_prev,
    // we only need to check neighbors of M(u_prev) in target.
    // Otherwise, check all unused v.
    
    // Find a 'parent' in the matching order that is already connected to u
    // This constrains the search space significantly.
    int connected_parent = -1;
    bool direction_out = true; // true if parent->u, false if u->parent

    for (int i = 0; i < s.core_len; ++i) {
        int u_prev = order[i];
        if (pat.has_edge(u_prev, u)) {
            connected_parent = u_prev;
            direction_out = true;
            break;
        }
        if (pat.has_edge(u, u_prev)) {
            connected_parent = u_prev;
            direction_out = false;
            break;
        }
    }

    if (connected_parent != -1) {
        int v_parent = s.core_1[connected_parent];
        const vector<int>& candidates = (direction_out) ? tar.adj[v_parent] : tar.radj[v_parent];
        
        for (int v : candidates) {
            if (!s.used_target[v]) {
                if (check_feasibility(pat, tar, u, v, s)) {
                    // Add mapping
                    s.core_1[u] = v;
                    s.core_2[v] = u;
                    s.used_target[v] = true;
                    s.core_len++;
                    
                    solve(pat, tar, s, order);
                    
                    // Backtrack
                    s.core_len--;
                    s.used_target[v] = false;
                    s.core_2[v] = -1;
                    s.core_1[u] = -1;
                }
            }
        }
    } else {
        // Fallback: Disconnected component or first node. Try all unused targets.
        // Optimization: Filter by label and degree before detailed check
        for (int v = 0; v < tar.n; ++v) {
            if (!s.used_target[v]) {
                 // Quick pre-check
                if (pat.label[u] != tar.label[v]) continue;
                if (tar.adj[v].size() < pat.adj[u].size()) continue;

                if (check_feasibility(pat, tar, u, v, s)) {
                    s.core_1[u] = v;
                    s.core_2[v] = u;
                    s.used_target[v] = true;
                    s.core_len++;
                    
                    solve(pat, tar, s, order);
                    
                    s.core_len--;
                    s.used_target[v] = false;
                    s.core_2[v] = -1;
                    s.core_1[u] = -1;
                }
            }
        }
    }
}

// --- Main ---

int main(int argc, char** argv) {
    // Fast IO
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);

    bool first_only = false;
    bool induced = true;
    vector<string> positional;
    positional.reserve(static_cast<size_t>(max(0, argc - 1)));
    for (int i = 1; i < argc; ++i) {
        string arg = argv[i];
        if (arg == "--first-only" || arg == "-F") {
            first_only = true;
            continue;
        }
        if (arg == "--non-induced" || arg == "--noninduced") {
            induced = false;
            continue;
        }
        if (arg == "--induced") {
            induced = true;
            continue;
        }
        positional.push_back(std::move(arg));
    }
    if (positional.size() != 2) {
        cerr << "Usage: " << argv[0] << " [--first-only|-F] [--induced|--non-induced] <pattern_file> <target_file>" << endl;
        return 1;
    }

    const string pat_file = positional[0];
    const string tar_file = positional[1];
    first_only_mode = first_only;
    induced_mode = induced;
    match_count = 0;

    Graph pat = load_graph(pat_file);
    Graph tar = load_graph(tar_file);

    solve_start_time = chrono::steady_clock::now();
    first_solution_sec = -1.0;

    // Heuristic: Determine matching order (Node Ordering)
    // Greedy approach: Start with node with max degree, then BFS/DFS
    vector<int> order;
    vector<bool> visited(pat.n, false);
    
    // Find node with max degree + distinct label rarity (simplified to max degree here)
    int start_node = 0;
    int max_deg = -1;
    for(int i=0; i<pat.n; ++i) {
        int d = pat.adj[i].size() + pat.radj[i].size();
        if(d > max_deg) {
            max_deg = d;
            start_node = i;
        }
    }

    // BFS to build order for connectivity
    vector<int> q;
    q.push_back(start_node);
    visited[start_node] = true;
    int head = 0;
    while(head < q.size()){
        int u = q[head++];
        order.push_back(u);
        // Neighbors
        vector<int> neighbors = pat.adj[u];
        neighbors.insert(neighbors.end(), pat.radj[u].begin(), pat.radj[u].end());
        // Sort neighbors by degree desc to keep heuristic strong
        sort(neighbors.begin(), neighbors.end(), [&](int a, int b){
            return (pat.adj[a].size() + pat.radj[a].size()) > (pat.adj[b].size() + pat.radj[b].size());
        });

        for(int v : neighbors){
            if(!visited[v]){
                visited[v] = true;
                q.push_back(v);
            }
        }
    }
    // Add any disconnected components
    for(int i=0; i<pat.n; ++i){
        if(!visited[i]) order.push_back(i);
    }

    State state(pat.n, tar.n);
    solve(pat, tar, state, order);

    auto end_time = chrono::steady_clock::now();
    double all_sec = chrono::duration<double>(end_time - solve_start_time).count();
    if (first_solution_sec < 0.0) {
        first_solution_sec = all_sec;
    }

    cout.setf(std::ios::fixed);
    cout << setprecision(6) << match_count << " " << first_solution_sec << " " << all_sec << endl;

    return 0;
}
