/**
 * Prompt: Alright I have 2 graphs. The first graph is a subgraph of the second graph. 
 * This subgraph is a triangle. The second graph is a bowtie (2 triangles). 
 * I want you to build me an algorithm in C++ that outputs: 
 * [number of solutions found] [time to find the first solution] [time to find all the solutions]
*/

#include <iostream>
#include <vector>
#include <chrono>

// Use namespaces for clarity and brevity
using std::vector;
using std::cout;
using std::endl;
using std::chrono::high_resolution_clock;
using std::chrono::duration_cast;
using std::chrono::nanoseconds; // Changed from microseconds

// --- Global Variables ---

// Graph representations (adjacency matrices)
vector<vector<bool>> pattern_graph;
vector<vector<bool>> target_graph;

// State for backtracking
// mapping[p] = t means pattern node 'p' is mapped to target node 't'
vector<int> mapping; 
// used_target_nodes[t] = true means target node 't' is in the current partial mapping
vector<bool> used_target_nodes;

// Statistics
int solution_count = 0;
high_resolution_clock::time_point start_time;
high_resolution_clock::time_point first_solution_time;
bool first_solution_found = false;

int num_pattern_nodes;
int num_target_nodes;

/**
 * @brief Helper function to add an undirected edge to an adjacency matrix.
 * @param graph The graph to modify.
 * @param u The source node.
 * @param v The destination node.
 */
void add_edge(vector<vector<bool>>& graph, int u, int v) {
    graph[u][v] = true;
    // graph[v][u] = true; // Remove this line to make edges directed
}

/**
 * @brief The recursive backtracking function to find subgraph isomorphisms.
 * @param p_node The current pattern node we are trying to map (from 0 to num_pattern_nodes-1).
 */
void solve(int p_node) {
    // Base Case: We have successfully mapped all pattern nodes.
    if (p_node == num_pattern_nodes) {
        // If this is the very first solution, record the time.
        if (!first_solution_found) {
            first_solution_time = high_resolution_clock::now();
            first_solution_found = true;
        }
        solution_count++;
        return; // Backtrack from here
    }

    // Recursive Step: Try to map pattern node 'p_node' to each target node 't_node'.
    for (int t_node = 0; t_node < num_target_nodes; ++t_node) {
        
        // --- Pruning Condition 1 ---
        // Check if the target node 't_node' is already used in the current mapping.
        if (used_target_nodes[t_node]) {
            continue; // Try the next target node
        }

        // --- Pruning Condition 2 ---
        // Check if this new mapping (p_node -> t_node) is consistent with the
        // existing partial mapping (all prev_p_node -> prev_t_node).
        bool is_feasible = true;
        for (int prev_p_node = 0; prev_p_node < p_node; ++prev_p_node) {
            int prev_t_node = mapping[prev_p_node];

            // --- Pruning Condition 2 (Modified for Directed Graphs) ---
            // We must check for edges in both directions.

            // Check 1: Edge from current pattern node (p_node) to previous (prev_p_node)
            if (pattern_graph[p_node][prev_p_node]) {
                // ...then the corresponding edge (t_node -> prev_t_node) *must*
                // exist in the target graph.
                if (!target_graph[t_node][prev_t_node]) {
                    is_feasible = false;
                    break; // This mapping is invalid
                }
            }

            // Check 2: Edge from previous pattern node (prev_p_node) to current (p_node)
            if (pattern_graph[prev_p_node][p_node]) {
                // ...then the corresponding edge (prev_t_node -> t_node) *must*
                // exist in the target graph.
                if (!target_graph[prev_t_node][t_node]) {
                    is_feasible = false;
                    break; // This mapping is invalid
                }
            }
        }

        // If both pruning conditions pass, this mapping is feasible so far.
        if (is_feasible) {
            // --- Recurse ---
            // 1. Add (p_node -> t_node) to our partial solution.
            mapping[p_node] = t_node;
            used_target_nodes[t_node] = true;

            // 2. Move to the next pattern node.
            solve(p_node + 1);

            // --- Backtrack ---
            // 3. Remove (p_node -> t_node) from our partial solution
            //    to explore other possibilities.
            used_target_nodes[t_node] = false;
            mapping[p_node] = -1; // Reset mapping (optional, but good practice)
        }
    }
}


int main() {
    // --- 1. Define Pattern Graph (Directed Triangle Cycle) ---
    num_pattern_nodes = 3;
    pattern_graph.resize(num_pattern_nodes, vector<bool>(num_pattern_nodes, false));
    // Create a cycle: 0 -> 1 -> 2 -> 0
    add_edge(pattern_graph, 0, 1);
    add_edge(pattern_graph, 1, 2);
    add_edge(pattern_graph, 2, 0); // Changed from (0, 2) to (2, 0) for a cycle

    // --- 2. Define Target Graph (Directed Bowtie) ---
    num_target_nodes = 5;
    target_graph.resize(num_target_nodes, vector<bool>(num_target_nodes, false));
    
    // First triangle cycle: (A, B, C) or (0 -> 1 -> 2 -> 0)
    add_edge(target_graph, 0, 1);
    add_edge(target_graph, 1, 2);
    add_edge(target_graph, 2, 0); // Changed from (0, 2) to (2, 0) for a cycle

    // Second triangle cycle: (C, D, E) or (2 -> 3 -> 4 -> 2)
    add_edge(target_graph, 2, 3);
    add_edge(target_graph, 3, 4);
    add_edge(target_graph, 4, 2); // Changed from (2, 4) to (4, 2) for a cycle

    // --- 3. Initialize State ---
    mapping.resize(num_pattern_nodes, -1);
    used_target_nodes.resize(num_target_nodes, false);

    // --- 4. Run and Time Algorithm ---
    start_time = high_resolution_clock::now();
    
    solve(0); // Start the recursive search from the first pattern node (node 0)

    high_resolution_clock::time_point end_time = high_resolution_clock::now();

    // --- 5. Calculate and Print Results ---
    
    // Calculate time to first solution (in nanoseconds)
    long long time_to_first_ns = 0;
    if (first_solution_found) {
        time_to_first_ns = duration_cast<nanoseconds>(first_solution_time - start_time).count();
    }
    
    // Calculate time to find all solutions (in nanoseconds)
    long long time_to_all_ns = duration_cast<nanoseconds>(end_time - start_time).count();

    // Output in the format: [num solutions] [time to first (ns)] [time to all (ns)]
    cout << solution_count << " " 
         << time_to_first_ns << " " 
         << time_to_all_ns << endl;

    return 0;
}