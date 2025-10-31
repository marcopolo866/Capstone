#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "dijkstra.h"

namespace {

struct InputData {
    int vertexCount = 0;
    int startVertex = 0;
    int targetVertex = 0;
    std::vector<int> edges;
};

InputData parseInputFile(const std::string& path) {
    std::ifstream in(path);
    if (!in.is_open()) {
        throw std::runtime_error("Failed to open input file: " + path);
    }

    InputData data;
    if (!(in >> data.vertexCount)) {
        throw std::runtime_error("Input file missing vertex count");
    }

    if (!(in >> data.startVertex >> data.targetVertex)) {
        throw std::runtime_error("Input file missing start and target vertex IDs");
    }

    int u, v, w;
    while (in >> u >> v >> w) {
        data.edges.push_back(u);
        data.edges.push_back(v);
        data.edges.push_back(w);
    }

    if (data.edges.empty()) {
        throw std::runtime_error("Input file contains no edges");
    }

    return data;
}

} // namespace

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input-file>\n";
        return 1;
    }

    try {
        InputData data = parseInputFile(argv[1]);
        std::string output = dijkstra(data.edges, data.vertexCount, data.startVertex, data.targetVertex);
        std::cout << output << "\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }
}
