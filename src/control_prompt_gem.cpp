#include <iostream>
#include <vector>
#include <fstream>
#include <algorithm>
#include <numeric>

using namespace std;

struct Graph {
    int n;
    vector<int> labels;
    vector<vector<int>> adj;
    vector<vector<int>> rev_adj;
    vector<vector<bool>> matrix; // For O(1) induced check

    Graph(const string& filename) {
        ifstream infile(filename);
        if (!infile) exit(1);
        infile >> n;
        labels.resize(n);
        adj.resize(n);
        rev_adj.resize(n);
        matrix.resize(n, vector<bool>(n, false));

        for (int i = 0; i < n; ++i) {
            int id, label;
            infile >> id >> label;
            labels[id] = label;
        }
        for (int i = 0; i < n; ++i) {
            int k;
            infile >> k;
            while (k--) {
                int u, v;
                infile >> u >> v;
                adj[u].push_back(v);
                rev_adj[v].push_back(u);
                matrix[u][v] = true;
            }
        }
    }
};

struct Solver {
    const Graph &H, &G;
    long long count = 0;
    vector<int> mapping;     // H node -> G node
    vector<int> reverse_map; // G node -> H node
    vector<int> order;       // Search order of H nodes

    Solver(const Graph& h, const Graph& g) : H(h), G(g) {
        mapping.assign(H.n, -1);
        reverse_map.assign(G.n, -1);
        compute_order();
    }

    // Heuristic: Pick next node with most connections to already picked nodes
    void compute_order() {
        vector<bool> visited(H.n, false);
        for (int i = 0; i < H.n; ++i) {
            int best_node = -1;
            int max_connections = -1;
            int max_degree = -1;

            for (int j = 0; j < H.n; ++j) {
                if (visited[j]) continue;
                int connections = 0;
                for (int neighbor : H.adj[j]) if (visited[neighbor]) connections++;
                for (int neighbor : H.rev_adj[j]) if (visited[neighbor]) connections++;
                
                int degree = (int)H.adj[j].size() + (int)H.rev_adj[j].size();
                if (connections > max_connections || (connections == max_connections && degree > max_degree)) {
                    max_connections = connections;
                    max_degree = degree;
                    best_node = j;
                }
            }
            order.push_back(best_node);
            visited[best_node] = true;
        }
    }

    bool is_feasible(int h_idx, int g_node, int current_depth) {
        int h_node = order[current_depth];

        // Label and Degree Pruning
        if (H.labels[h_node] != G.labels[g_node]) return false;
        if (H.adj[h_node].size() > G.adj[g_node].size()) return false;
        if (H.rev_adj[h_node].size() > G.rev_adj[g_node].size()) return false;

        // Induced Subgraph Check
        for (int i = 0; i < current_depth; ++i) {
            int prev_h = order[i];
            int prev_g = mapping[prev_h];

            // Edge H(prev->curr) must match G(prev->curr)
            if (H.matrix[prev_h][h_node] != G.matrix[prev_g][g_node]) return false;
            // Edge H(curr->prev) must match G(curr->prev)
            if (H.matrix[h_node][prev_h] != G.matrix[g_node][prev_g]) return false;
        }
        return true;
    }

    void backtrack(int depth) {
        if (depth == H.n) {
            count++;
            return;
        }

        int h_node = order[depth];
        
        // Refined candidate selection: 
        // If h_node has an edge from a previously mapped node, only check neighbors of that node in G.
        int anchor_h = -1;
        for(int i=0; i < depth; ++i) {
            if(H.matrix[order[i]][h_node]) { anchor_h = order[i]; break; }
        }

        if (anchor_h != -1) {
            int anchor_g = mapping[anchor_h];
            for (int g_cand : G.adj[anchor_g]) {
                if (reverse_map[g_cand] == -1 && is_feasible(h_node, g_cand, depth)) {
                    mapping[h_node] = g_cand;
                    reverse_map[g_cand] = h_node;
                    backtrack(depth + 1);
                    reverse_map[g_cand] = -1;
                    mapping[h_node] = -1;
                }
            }
        } else {
            // No incoming edges from mapped nodes (could be start of component or isolated)
            for (int g_cand = 0; g_cand < G.n; ++g_cand) {
                if (reverse_map[g_cand] == -1 && is_feasible(h_node, g_cand, depth)) {
                    mapping[h_node] = g_cand;
                    reverse_map[g_cand] = h_node;
                    backtrack(depth + 1);
                    reverse_map[g_cand] = -1;
                    mapping[h_node] = -1;
                }
            }
        }
    }
};

int main(int argc, char** argv) {
    if (argc < 3) return 1;
    Graph H(argv[1]);
    Graph G(argv[2]);

    if (H.n > G.n) {
        cout << 0 << endl;
        return 0;
    }

    Solver solver(H, G);
    solver.backtrack(0);
    cout << solver.count << endl;

    return 0;
}