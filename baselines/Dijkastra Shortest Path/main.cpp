//Main.cpp file created by Noah Gerlach for Dijkstra baseline testing purposes
#include <iostream>
#include <vector>
#include <string>
#include "dijkstra.h"

int main() {
    // Graph with vertices 0..4 (five vertices total)
    // edges = {u, v, w,  u, v, w,  ...}
    std::vector<int> edges = {
        0, 1, 4,
        0, 2, 1,
        2, 1, 2,
        1, 3, 1,
        2, 3, 5,
        3, 4, 3
    };

    int vsize  = 5;   // number of vertices (IDs 0..vsize-1)
    int start  = 0;   // start vertex ID
    int target = 4;   // end vertex ID

    std::string result = dijkstra(edges, vsize, start, target);
    std::cout << result << "\n";   // e.g., "8; 0 2 1 3 4"
}
