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

std::vector<int> parseLineOfInts(const std::string& line) {
    std::string normalized;
    normalized.reserve(line.size());
    for (char c : line) {
        if (c == ',' || c == ';') {
            normalized.push_back(' ');
        } else {
            normalized.push_back(c);
        }
    }

    std::istringstream ss(normalized);
    std::vector<int> values;
    int value;
    while (ss >> value) {
        values.push_back(value);
    }
    return values;
}

InputData parseInputFile(const std::string& path) {
    std::ifstream in(path);
    if (!in.is_open()) {
        throw std::runtime_error("Failed to open input file: " + path);
    }

    auto readNextValues = [&](std::size_t expectedCount = 0) -> std::vector<int> {
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) {
                continue;
            }
            // Strip simple comments starting with '#'
            auto hashPos = line.find('#');
            if (hashPos != std::string::npos) {
                line = line.substr(0, hashPos);
            }
            std::vector<int> values = parseLineOfInts(line);
            if (!values.empty()) {
                if (expectedCount && values.size() != expectedCount) {
                    std::ostringstream err;
                    err << "Expected " << expectedCount << " value(s), found " << values.size();
                    throw std::runtime_error(err.str());
                }
                return values;
            }
        }
        if (expectedCount) {
            std::ostringstream err;
            err << "Input file missing a line with " << expectedCount << " value(s)";
            throw std::runtime_error(err.str());
        }
        return {};
    };

    InputData data;
    auto header = readNextValues(1);
    data.vertexCount = header[0];

    auto endpoints = readNextValues(2);
    data.startVertex = endpoints[0];
    data.targetVertex = endpoints[1];

    while (true) {
        auto edgeValues = readNextValues();
        if (edgeValues.empty()) {
            break;
        }
        if (edgeValues.size() != 3) {
            throw std::runtime_error("Edge lines must contain exactly three integers");
        }
        data.edges.insert(data.edges.end(), edgeValues.begin(), edgeValues.end());
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
