/**
 * Prompt: Alright I have 2 graphs. The first graph is a subgraph of the second graph. 
 * This subgraph is a triangle. The second graph is a bowtie (2 triangles). 
 * I want you to build me an algorithm in C++ that outputs: 
 * [number of solutions found] [time to find the first solution] [time to find all the solutions]
*/

#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <chrono>
#include <iomanip>

using namespace std;
using namespace chrono;

struct Digraph {
    int n;
    vector<vector<int>> adj;
    Digraph(int n): n(n), adj(n) {}
    void addEdge(int u, int v) {
        adj[u].push_back(v);
    }
    bool connected(int u, int v) const {
        return find(adj[u].begin(), adj[u].end(), v) != adj[u].end();
    }
};

// Check if mapping preserves directed edges
bool isSubgraphMatch(const Digraph &sub, const Digraph &big, const vector<int> &mapping) {
    for (int i = 0; i < sub.n; ++i) {
        for (int j = 0; j < sub.n; ++j) {
            if (i == j) continue;
            bool subEdge = sub.connected(i, j);
            bool bigEdge = big.connected(mapping[i], mapping[j]);
            if (subEdge != bigEdge) return false;
        }
    }
    return true;
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    // Directed triangle subgraph: 0→1→2→0
    Digraph sub(3);
    sub.addEdge(0, 1);
    sub.addEdge(1, 2);
    sub.addEdge(2, 0);

    // Directed bowtie: two directed triangles sharing vertex 0
    Digraph big(5);
    // Triangle 1: 0→1→2→0
    big.addEdge(0, 1);
    big.addEdge(1, 2);
    big.addEdge(2, 0);
    // Triangle 2: 0→3→4→0
    big.addEdge(0, 3);
    big.addEdge(3, 4);
    big.addEdge(4, 0);

    int countSolutions = 0;
    double timeToFirst = 0.0;
    auto start = high_resolution_clock::now();

    // Try all possible directed mappings
    for (int a = 0; a < big.n; ++a) {
        for (int b = 0; b < big.n; ++b) {
            if (b == a) continue;
            for (int c = 0; c < big.n; ++c) {
                if (c == a || c == b) continue;
                vector<int> mapping = {a, b, c};
                if (isSubgraphMatch(sub, big, mapping)) {
                    countSolutions++;
                    if (countSolutions == 1) {
                        auto first = high_resolution_clock::now();
                        timeToFirst = duration<double, milli>(first - start).count();
                    }
                }
            }
        }
    }

    auto end = high_resolution_clock::now();
    double totalTime = duration<double, milli>(end - start).count();

    cout << countSolutions << " "
         << fixed << setprecision(3)
         << timeToFirst << " "
         << totalTime << "\n";

    return 0;
}
