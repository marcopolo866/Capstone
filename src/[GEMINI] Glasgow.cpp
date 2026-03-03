#include <iostream>
#include <vector>
#include <string>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>

using namespace std;

// Optimized structure for fast adjacency checks
struct Graph {
    int n;
    vector<vector<int>> adj;
    vector<vector<bool>> matrix;
    vector<int> label;
};

// Parse ints from a text line into vals. Returns number of ints parsed.
static int parse_ints(const char *line, vector<int> &vals) {
    vals.clear();
    const char *p = line;
    while (*p) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (!*p) break;
        bool neg = (*p == '-');
        if (neg) p++;
        if (*p < '0' || *p > '9') break;
        int v = 0;
        while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        vals.push_back(neg ? -v : v);
    }
    return (int)vals.size();
}

// Parser for .lad format
bool read_lad(const string& filename, Graph& g) {
    FILE *f = fopen(filename.c_str(), "r");
    if (!f) return false;

    char line[65536];
    // Skip comment/bracket lines
    while (true) {
        int c = fgetc(f);
        if (c == EOF) { fclose(f); return false; }
        if (c == '[' || c == '\r' || c == '\n') {
            // consume rest of line
            while (c != '\n' && c != EOF) c = fgetc(f);
        } else {
            ungetc(c, f);
            break;
        }
    }

    if (fscanf(f, "%d", &g.n) != 1) { fclose(f); return false; }
    fgets(line, sizeof(line), f); // consume rest of n line

    g.adj.resize(g.n);
    g.matrix.assign(g.n, vector<bool>(g.n, false));
    g.label.assign(g.n, 0);

    vector<int> vals;
    for (int i = 0; i < g.n; ++i) {
        if (!fgets(line, sizeof(line), f)) break;
        if (parse_ints(line, vals) == 0) continue;

        int start = 1;
        int count = 0;
        if ((int)vals.size() >= 2 && vals[1] == (int)vals.size() - 2) {
            g.label[i] = vals[0];
            count = vals[1];
            start = 2;
        } else {
            count = vals[0];
        }
        for (int j = 0; j < count && start + j < (int)vals.size(); ++j) {
            int neighbor = vals[start + j];
            if (neighbor >= 0 && neighbor < g.n && neighbor != i) {
                g.adj[i].push_back(neighbor);
                g.matrix[i][neighbor] = true;
            }
        }
    }
    fclose(f);
    return true;
}

// Parser for .grf format
bool read_grf(const string& filename, Graph& g) {
    FILE *f = fopen(filename.c_str(), "r");
    if (!f) return false;
    if (fscanf(f, "%d", &g.n) != 1) { fclose(f); return false; }
    g.adj.resize(g.n);
    g.matrix.assign(g.n, vector<bool>(g.n, false));
    g.label.assign(g.n, 0);
    int u, v;
    while (fscanf(f, "%d %d", &u, &v) == 2) {
        if (u < g.n && v < g.n) {
            g.adj[u].push_back(v);
            g.matrix[u][v] = true;
            g.adj[v].push_back(u);
            g.matrix[v][u] = true;
        }
    }
    fclose(f);
    return true;
}

int total_instances = 0;
vector<int> mapping;
vector<bool> used;

void backtrack(int p_idx, const Graph& p, const Graph& t) {
    if (p_idx == p.n) {
        total_instances++;
        cout << "Mapping: ";
        for (int i = 0; i < p.n; ++i) {
            cout << "(" << i << " -> " << mapping[i] << ")" << (i == p.n - 1 ? "" : " ");
        }
        cout << endl;
        return;
    }

    for (int v = 0; v < t.n; ++v) {
        if (!used[v]) {
            if (p.label[p_idx] != t.label[v]) continue;
            // Advanced Pruning: Degree constraint (pattern node degree <= target node degree)
            if (t.adj[v].size() < p.adj[p_idx].size()) continue;

            bool ok = true;
            // Constraint-based filtering: Check if existing mappings preserve edges (non-induced)
            for (int prev_p = 0; prev_p < p_idx; ++prev_p) {
                if (p.matrix[p_idx][prev_p] && !t.matrix[v][mapping[prev_p]]) { ok = false; break; }
                if (p.matrix[prev_p][p_idx] && !t.matrix[mapping[prev_p]][v]) { ok = false; break; }
            }

            if (ok) {
                used[v] = true;
                mapping[p_idx] = v;
                backtrack(p_idx + 1, p, t);
                used[v] = false;
            }
        }
    }
}

int main(int argc, char** argv) {
    if (argc < 3) return 1;
    Graph pattern, target;
    string p_file = argv[1], t_file = argv[2];

    auto get_ext = [&](string f) {
        size_t dot = f.find_last_of(".");
        return (dot == string::npos) ? "" : f.substr(dot + 1);
    };

    if (get_ext(p_file) == "lad") read_lad(p_file, pattern); else read_grf(p_file, pattern);
    if (get_ext(t_file) == "lad") read_lad(t_file, target); else read_grf(t_file, target);

    mapping.resize(pattern.n);
    used.assign(target.n, false);

    auto start = chrono::high_resolution_clock::now();
    backtrack(0, pattern, target);
    auto end = chrono::high_resolution_clock::now();

    auto duration = chrono::duration_cast<chrono::milliseconds>(end - start).count();

    cout << total_instances << endl;
    cout << "Time: " << duration << endl;

    return 0;
}
