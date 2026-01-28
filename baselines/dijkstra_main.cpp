#include <algorithm>
#include <cctype>
#include <fstream>
#include <iostream>
#include <iterator>
#include <optional>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <type_traits>
#include <vector>

using namespace std;

#include "shortest-path/dijkstra-skew-heap.hpp"

namespace {

struct InputData {
    int vertexCount = 0;
    int startVertex = 0;
    int targetVertex = 0;
    std::vector<int> edges;
    std::vector<std::string> labels;
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

std::string trim(const std::string& text) {
    const auto first = std::find_if_not(text.begin(), text.end(), [](unsigned char c) { return std::isspace(c); });
    if (first == text.end()) {
        return {};
    }
    const auto last = std::find_if_not(text.rbegin(), text.rend(), [](unsigned char c) { return std::isspace(c); }).base();
    return std::string(first, last);
}

std::vector<std::string> splitCsvLine(const std::string& line) {
    std::string cleaned;
    cleaned.reserve(line.size());
    for (char c : line) {
        cleaned.push_back(c == ';' ? ',' : c);
    }

    std::vector<std::string> cells;
    std::stringstream ss(cleaned);
    std::string cell;
    while (std::getline(ss, cell, ',')) {
        cells.push_back(trim(cell));
    }
    return cells;
}

bool isIntegerToken(const std::string& token) {
    if (token.empty()) {
        return false;
    }
    std::size_t index = 0;
    if (token[index] == '+' || token[index] == '-') {
        ++index;
    }
    bool hasDigit = false;
    for (; index < token.size(); ++index) {
        if (!std::isdigit(static_cast<unsigned char>(token[index]))) {
            return false;
        }
        hasDigit = true;
    }
    return hasDigit;
}

std::optional<std::string> extractLabelFromComments(const std::vector<std::string>& comments,
                                                    const std::string& key) {
    std::string loweredKey = key;
    std::transform(loweredKey.begin(), loweredKey.end(), loweredKey.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    for (const std::string& line : comments) {
        std::string loweredLine = line;
        std::transform(loweredLine.begin(), loweredLine.end(), loweredLine.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

        std::size_t searchPos = 0;
        while (true) {
            std::size_t pos = loweredLine.find(loweredKey, searchPos);
            if (pos == std::string::npos) {
                break;
            }
            std::size_t cursor = pos + loweredKey.size();
            while (cursor < loweredLine.size() &&
                   std::isspace(static_cast<unsigned char>(loweredLine[cursor]))) {
                ++cursor;
            }
            if (cursor >= loweredLine.size()) {
                break;
            }
            if (loweredLine[cursor] != '=' && loweredLine[cursor] != ':') {
                searchPos = pos + loweredKey.size();
                continue;
            }
            ++cursor;
            while (cursor < loweredLine.size() &&
                   std::isspace(static_cast<unsigned char>(loweredLine[cursor]))) {
                ++cursor;
            }
            if (cursor >= loweredLine.size()) {
                break;
            }
            std::size_t end = cursor;
            while (end < loweredLine.size() && loweredLine[end] != ',' && loweredLine[end] != ';' &&
                   !std::isspace(static_cast<unsigned char>(loweredLine[end]))) {
                ++end;
            }
            if (end == cursor) {
                searchPos = pos + loweredKey.size();
                continue;
            }
            return trim(line.substr(cursor, end - cursor));
        }
    }
    return std::nullopt;
}

InputData parseNumericFormat(const std::vector<std::string>& lines) {
    if (lines.size() < 3) {
        throw std::runtime_error("Numeric format input must have at least three non-empty lines");
    }

    InputData data;

    auto vertexValues = parseLineOfInts(lines[0]);
    if (vertexValues.size() != 1) {
        throw std::runtime_error("Vertex count line must contain exactly one integer");
    }
    data.vertexCount = vertexValues[0];

    auto endpoints = parseLineOfInts(lines[1]);
    if (endpoints.size() != 2) {
        throw std::runtime_error("Start/target line must contain exactly two integers");
    }
    data.startVertex = endpoints[0];
    data.targetVertex = endpoints[1];

    for (std::size_t i = 2; i < lines.size(); ++i) {
        auto edgeValues = parseLineOfInts(lines[i]);
        if (edgeValues.empty()) {
            continue;
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

InputData parseCsvFormat(const std::vector<std::string>& lines,
                         const std::vector<std::string>& comments) {
    InputData data;

    if (lines.empty()) {
        throw std::runtime_error("CSV input file contains no data rows");
    }

    std::unordered_map<std::string, int> idMap;
    std::vector<std::string> idOrder;

    auto getOrCreateId = [&](const std::string& label) -> int {
        auto it = idMap.find(label);
        if (it != idMap.end()) {
            return it->second;
        }
        int id = static_cast<int>(idMap.size());
        idMap.emplace(label, id);
        idOrder.push_back(label);
        return id;
    };

    auto findExistingId = [&](const std::string& label) -> std::optional<int> {
        auto it = idMap.find(label);
        if (it == idMap.end()) {
            return std::nullopt;
        }
        return it->second;
    };

    std::optional<std::string> startLabel = extractLabelFromComments(comments, "start");
    std::optional<std::string> targetLabel = extractLabelFromComments(comments, "target");
    std::optional<std::string> defaultStartLabel;
    std::optional<std::string> defaultTargetLabel;

    bool headerConsumed = false;

    for (const std::string& rawLine : lines) {
        std::vector<std::string> cells = splitCsvLine(rawLine);
        if (cells.empty()) {
            continue;
        }
        if (cells.size() != 3) {
            std::ostringstream err;
            err << "Each edge row must contain exactly three fields, found " << cells.size()
                << " in line: " << rawLine;
            throw std::runtime_error(err.str());
        }

        int weight = 0;
        try {
            std::size_t parsed = 0;
            weight = std::stoi(cells[2], &parsed);
            if (parsed != cells[2].size()) {
                throw std::invalid_argument("extra characters");
            }
        } catch (const std::exception&) {
            if (!headerConsumed) {
                headerConsumed = true;
                continue;
            }
            std::ostringstream err;
            err << "Edge weight \"" << cells[2] << "\" is not a valid integer";
            throw std::runtime_error(err.str());
        }

        int sourceId = getOrCreateId(cells[0]);
        int targetId = getOrCreateId(cells[1]);

        if (!defaultStartLabel) {
            defaultStartLabel = cells[0];
        }
        defaultTargetLabel = cells[1];

        data.edges.push_back(sourceId);
        data.edges.push_back(targetId);
        data.edges.push_back(weight);
    }

    if (data.edges.empty()) {
        throw std::runtime_error("CSV input produced no edges");
    }

    data.vertexCount = static_cast<int>(idMap.size());
    data.labels = idOrder;

    std::string chosenStartLabel =
        startLabel.value_or(defaultStartLabel.value_or(std::string{}));
    std::string chosenTargetLabel =
        targetLabel.value_or(defaultTargetLabel.value_or(std::string{}));

    if (chosenStartLabel.empty() || chosenTargetLabel.empty()) {
        throw std::runtime_error("Unable to determine start/target vertices from CSV input. "
                                 "Add a comment like \"# start=A target=D\" or ensure edges exist.");
    }

    auto startId = findExistingId(chosenStartLabel);
    auto targetId = findExistingId(chosenTargetLabel);

    if (!startId) {
        std::ostringstream err;
        err << "Start vertex \"" << chosenStartLabel << "\" does not appear in the edge list";
        throw std::runtime_error(err.str());
    }
    if (!targetId) {
        std::ostringstream err;
        err << "Target vertex \"" << chosenTargetLabel << "\" does not appear in the edge list";
        throw std::runtime_error(err.str());
    }

    data.startVertex = *startId;
    data.targetVertex = *targetId;

    return data;
}

InputData parseInputFile(const std::string& path) {
    std::ifstream in(path);
    if (!in.is_open()) {
        throw std::runtime_error("Failed to open input file: " + path);
    }

    std::vector<std::string> comments;
    std::vector<std::string> dataLines;

    std::string rawLine;
    while (std::getline(in, rawLine)) {
        std::string trimmed = trim(rawLine);
        if (trimmed.empty()) {
            continue;
        }
        if (!trimmed.empty() && trimmed[0] == '#') {
            comments.push_back(trim(trimmed.substr(1)));
            continue;
        }
        std::size_t hashPos = trimmed.find('#');
        if (hashPos != std::string::npos) {
            trimmed = trim(trimmed.substr(0, hashPos));
            if (trimmed.empty()) {
                continue;
            }
        }
        dataLines.push_back(trimmed);
    }

    if (dataLines.empty()) {
        throw std::runtime_error("Input file contains no usable data");
    }

    std::vector<int> firstValues = parseLineOfInts(dataLines.front());
    if (firstValues.size() == 1) {
        return parseNumericFormat(dataLines);
    }
    return parseCsvFormat(dataLines, comments);
}

std::string runDijkstra(const InputData& data) {
    if (data.vertexCount <= 0) {
        throw std::runtime_error("Vertex count must be positive");
    }

    int maxId = data.vertexCount;
    if (data.vertexCount < 0) {
        maxId = 0;
    }
    for (std::size_t i = 0; i + 2 < data.edges.size(); i += 3) {
        maxId = std::max(maxId, data.edges[i]);
        maxId = std::max(maxId, data.edges[i + 1]);
    }
    if (maxId < 0) {
        throw std::runtime_error("Graph contains negative vertex ids");
    }

    const std::size_t edgeCount = data.edges.size() / 3;
    StaticGraph<long long> graph(maxId + 1, static_cast<int>(edgeCount));
    for (std::size_t i = 0; i + 2 < data.edges.size(); i += 3) {
        int from = data.edges[i];
        int to = data.edges[i + 1];
        long long weight = static_cast<long long>(data.edges[i + 2]);
        if (from < 0 || to < 0) {
            throw std::runtime_error("Graph contains negative vertex ids");
        }
        if (from >= static_cast<int>(graph.size()) ||
            to >= static_cast<int>(graph.size())) {
            throw std::runtime_error("Graph contains vertex ids outside declared size");
        }
        graph.add_edge(from, to, weight);
    }

    if (data.startVertex < 0 || data.startVertex >= static_cast<int>(graph.size()) ||
        data.targetVertex < 0 || data.targetVertex >= static_cast<int>(graph.size())) {
        throw std::runtime_error("Start/target vertex out of range");
    }

    auto distPrev = dijkstra_restore<long long>(graph, data.startVertex);
    long long dist = distPrev[data.targetVertex].first;
    if (dist < 0) {
        return "INF; (no path)";
    }

    std::vector<int> path;
    int cur = data.targetVertex;
    while (cur != -1) {
        path.push_back(cur);
        if (cur == data.startVertex) {
            break;
        }
        cur = distPrev[cur].second;
    }
    if (path.empty() || path.back() != data.startVertex) {
        return "INF; (no path)";
    }
    std::reverse(path.begin(), path.end());

    std::ostringstream output;
    output << dist << ';';
    for (int vertex : path) {
        output << ' ' << vertex;
    }
    return output.str();
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input-file>\n";
        return 1;
    }

    try {
        InputData data = parseInputFile(argv[1]);
        std::string output = runDijkstra(data);

        if (!data.labels.empty()) {
            std::size_t semiPos = output.find(';');
            if (semiPos != std::string::npos) {
                std::string prefix = output.substr(0, semiPos + 1);
                std::string pathPart = output.substr(semiPos + 1);
                std::istringstream pathStream(pathPart);
                std::ostringstream convertedPath;
                bool conversionOk = true;
                int vertexId = 0;
                while (pathStream >> vertexId) {
                    if (vertexId < 0 || vertexId >= static_cast<int>(data.labels.size())) {
                        conversionOk = false;
                        break;
                    }
                    convertedPath << ' ' << data.labels[vertexId];
                }
                if (conversionOk && !convertedPath.str().empty()) {
                    output = prefix + convertedPath.str();
                }
            }
        }

        std::cout << output << "\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }
}
