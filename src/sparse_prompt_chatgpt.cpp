#include <iostream>
#include <vector>
#include <fstream>
#include <algorithm>
#include <numeric>
#include <functional>
#include <string>

using namespace std;

using ll = long long;

struct Graph {
    int n;
    vector<int> label;
    vector<vector<int>> out, in;
    vector<vector<bool>> adj; // adjacency matrix
};

Graph read_graph(const string &filename) {
    ifstream fin(filename);
    Graph g;
    fin >> g.n;

    g.label.resize(g.n);
    for (int i = 0; i < g.n; i++) {
        int id, lab;
        fin >> id >> lab;
        g.label[id] = lab;
    }

    g.out.assign(g.n, {});
    g.in.assign(g.n, {});
    g.adj.assign(g.n, vector<bool>(g.n, false));

    for (int i = 0; i < g.n; i++) {
        int k;
        fin >> k;
        for (int j = 0; j < k; j++) {
            int u, v;
            fin >> u >> v;
            g.out[u].push_back(v);
            g.in[v].push_back(u);
            g.adj[u][v] = true;
        }
    }

    return g;
}

int main(int argc, char** argv) {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    Graph H = read_graph(argv[1]);
    Graph G = read_graph(argv[2]);

    int n = H.n, m = G.n;

    // Degree arrays
    vector<int> H_out(n), H_in(n), G_out(m), G_in(m);
    for (int i = 0; i < n; i++) {
        H_out[i] = static_cast<int>(H.out[i].size());
        H_in[i] = static_cast<int>(H.in[i].size());
    }
    for (int i = 0; i < m; i++) {
        G_out[i] = static_cast<int>(G.out[i].size());
        G_in[i] = static_cast<int>(G.in[i].size());
    }

    // Initial candidate sets
    vector<vector<int>> cand(n);
    for (int u = 0; u < n; u++) {
        for (int v = 0; v < m; v++) {
            if (H.label[u] != G.label[v]) continue;
            if (H_out[u] > G_out[v]) continue;
            if (H_in[u] > G_in[v]) continue;
            cand[u].push_back(v);
        }
    }

    // Order pattern nodes
    vector<int> order(n);
    iota(order.begin(), order.end(), 0);

    sort(order.begin(), order.end(), [&](int a, int b) {
        if (cand[a].size() != cand[b].size())
            return cand[a].size() < cand[b].size();
        return (H_out[a] + H_in[a]) > (H_out[b] + H_in[b]);
    });

    vector<int> mapping(n, -1);
    vector<bool> used(m, false);

    ll count = 0;

    function<void(int)> dfs = [&](int depth) {
        if (depth == n) {
            count++;
            return;
        }

        int u = order[depth];

        for (int v : cand[u]) {
            if (used[v]) continue;

            bool ok = true;

            // Check consistency with already mapped nodes
            for (int i = 0; i < depth && ok; i++) {
                int w = order[i];
                int fw = mapping[w];

                // Edge preservation
                if (H.adj[u][w] && !G.adj[v][fw]) ok = false;
                if (H.adj[w][u] && !G.adj[fw][v]) ok = false;

                // Node-induced constraint
                if (G.adj[v][fw] && !H.adj[u][w]) ok = false;
                if (G.adj[fw][v] && !H.adj[w][u]) ok = false;
            }

            if (!ok) continue;

            mapping[u] = v;
            used[v] = true;

            dfs(depth + 1);

            mapping[u] = -1;
            used[v] = false;
        }
    };

    dfs(0);

    cout << count << "\n";
    return 0;
}