#include <iostream>
#include <vector>
#include <algorithm>
#include <queue>
#include <utility>
#include <chrono>   // Added for timing
#include <iomanip>  // Added for formatting output

using namespace std;

struct Graph {
    int n;
    vector<vector<int> > out_edges;
    vector<vector<int> > in_edges;
    Graph(int n): n(n), out_edges(n), in_edges(n) {}

    void add_edge(int u, int v) {
        out_edges[u].push_back(v);
        in_edges[v].push_back(u);
    }

    // This function checks for weak connectivity in the subgraph.
    bool is_connected_subgraph(const vector<int>& nodes) const {
        if (nodes.empty()) return true;
        vector<bool> in_set(n, false);
        for (size_t i = 0; i < nodes.size(); ++i)
            in_set[nodes[i]] = true;

        vector<bool> visited(n, false);
        queue<int> q;
        q.push(nodes[0]);
        visited[nodes[0]] = true;
        int visited_count = 0;

        while (!q.empty()) {
            int u = q.front(); q.pop();
            ++visited_count;

            // Check neighbors in both directions (weak connectivity)
            for (size_t i = 0; i < out_edges[u].size(); ++i) {
                int v = out_edges[u][i];
                if (in_set[v] && !visited[v]) {
                    visited[v] = true;
                    q.push(v);
                }
            }
            for (size_t i = 0; i < in_edges[u].size(); ++i) {
                int v = in_edges[u][i];
                if (in_set[v] && !visited[v]) {
                    visited[v] = true;
                    q.push(v);
                }
            }
        }

        return visited_count == (int)nodes.size();
    }
};

class VF3 {
public:
    VF3(const Graph& pattern, const Graph& target)
        : P(pattern), T(target), mapping(P.n, -1), used_target(T.n, false), 
          count(0), first_solution_found(false) {}

    void match_all() {
        count = 0;
        first_solution_found = false;

        // Start total time clock
        start_time = std::chrono::steady_clock::now();

        backtrack(0);

        // End total time clock
        end_time = std::chrono::steady_clock::now();

        // Calculate durations
        double time_to_all_ms = std::chrono::duration<double, std::milli>(end_time - start_time).count();
        double time_to_first_ms = -1.0;

        if (first_solution_found) {
            time_to_first_ms = std::chrono::duration<double, std::milli>(first_solution_time - start_time).count();
        }

        // Output in the requested format
        cout << fixed << setprecision(4); // Format timing output
        cout << count << " " << time_to_first_ms << " " << time_to_all_ms << "\n";
    }

private:
    const Graph& P;
    const Graph& T;
    vector<int> mapping;
    vector<bool> used_target;
    long long count;

    // Timing variables
    std::chrono::steady_clock::time_point start_time;
    std::chrono::steady_clock::time_point first_solution_time;
    std::chrono::steady_clock::time_point end_time;
    bool first_solution_found;

    bool feasible(int p, int t) {
        // Basic degree check
        if (P.out_edges[p].size() > T.out_edges[t].size()) return false;
        if (P.in_edges[p].size()  > T.in_edges[t].size())  return false;
        // NOTE: A true VF algorithm would have more complex lookaheads here
        return true;
    }

    bool consistent(int p, int t) {
        // This function must check for isomorphism consistency.
        // It must check that for all *already mapped* nodes 'pn',
        // the relationship (p, pn) in P is identical to (t, tn) in T.
        
        for (int pn = 0; pn < P.n; ++pn) {
            int tn = mapping[pn];
            if (tn == -1) continue; // Skip unmapped nodes

            // --- Check 1: P-edges must exist in T ---
            // p -> pn
            if (find(P.out_edges[p].begin(), P.out_edges[p].end(), pn) != P.out_edges[p].end()) {
                if (find(T.out_edges[t].begin(), T.out_edges[t].end(), tn) == T.out_edges[t].end())
                    return false; // Edge p->pn exists, but t->tn does not.
            }
            // pn -> p
            if (find(P.in_edges[p].begin(), P.in_edges[p].end(), pn) != P.in_edges[p].end()) {
                if (find(T.in_edges[t].begin(), T.in_edges[t].end(), tn) == T.in_edges[t].end())
                    return false; // Edge pn->p exists, but tn->t does not.
            }

            // --- Check 2: T-edges must exist in P (Correctness fix) ---
            // This is required for isomorphism, otherwise it's only monomorphism.
            // t -> tn
            if (find(T.out_edges[t].begin(), T.out_edges[t].end(), tn) != T.out_edges[t].end()) {
                if (find(P.out_edges[p].begin(), P.out_edges[p].end(), pn) == P.out_edges[p].end())
                    return false; // Edge t->tn exists, but p->pn does not.
            }
            // tn -> t
            if (find(T.in_edges[t].begin(), T.in_edges[t].end(), tn) != T.in_edges[t].end()) {
                if (find(P.in_edges[p].begin(), P.in_edges[p].end(), pn) == P.in_edges[p].end())
                    return false; // Edge tn->t exists, but pn->p does not.
            }
        }
        return true;
    }

    void backtrack(int depth) {
        if (depth == P.n) {
            // Found a complete mapping.
            // We must still verify the connectivity, as per the original logic.
            vector<int> mapped_nodes;
            for (int i = 0; i < P.n; ++i)
                mapped_nodes.push_back(mapping[i]);

            // Note: This check is redundant if P is connected and `consistent` is correct.
            // But we keep it to preserve the original algorithm's structure.
            if (T.is_connected_subgraph(mapped_nodes)) {
                // This is a valid solution
                
                // If this is the first solution, record the time.
                if (!first_solution_found) {
                    first_solution_time = std::chrono::steady_clock::now();
                    first_solution_found = true;
                }
                ++count;
                
                // We no longer print every mapping
                // cout << "Found mapping: ";
                // for (int i = 0; i < P.n; ++i)
                //     cout << i << "->" << mapping[i] << " ";
                // cout << "\n";
            }
            return;
        }

        // Find the next unmapped pattern node 'p'
        int p = -1;
        for (int i = 0; i < P.n; ++i)
            if (mapping[i] == -1) { p = i; break; }
        
        // This is a simple node selection. 
        // NOTE: VF-algorithms use specific ordering heuristics here for efficiency.

        // Try mapping 'p' to every unused target node 't'
        for (int t = 0; t < T.n; ++t) {
            if (used_target[t]) continue;
            
            // Pruning: check feasibility and consistency
            if (!feasible(p, t)) continue;
            if (!consistent(p, t)) continue;

            // Recurse
            mapping[p] = t;
            used_target[t] = true;

            backtrack(depth + 1);

            // Backtrack
            mapping[p] = -1;
            used_target[t] = false;
        }
    }
};

int main() {
    // Pattern: directed triangle (0→1→2→0)
    Graph P(3);
    P.add_edge(0,1);
    P.add_edge(1,2);
    P.add_edge(2,0);

    // Target: bowtie of two directed triangles sharing node 2
    Graph T(5);
    vector<pair<int,int> > edges;
    // Left triangle 0→1→2→0
    edges.push_back(make_pair(0,1));
    edges.push_back(make_pair(1,2));
    edges.push_back(make_pair(2,0));
    // Right triangle 2→3→4→2
    edges.push_back(make_pair(2,3));
    edges.push_back(make_pair(3,4));
    edges.push_back(make_pair(4,2));

    for (size_t i = 0; i < edges.size(); ++i)
        T.add_edge(edges[i].first, edges[i].second);

    VF3 matcher(P, T);
    
    // This will now print in the format: [count] [time_first_ms] [time_all_ms]
    matcher.match_all();

    return 0;
}