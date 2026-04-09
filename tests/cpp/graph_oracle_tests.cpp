#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <optional>
#include <queue>
#include <random>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

using WeightedAdj = std::vector<std::vector<std::pair<int, int>>>;
using UndirectedAdj = std::vector<std::vector<int>>;
using DistResult = std::pair<std::vector<long long>, std::vector<int>>;

constexpr long long kInf = std::numeric_limits<long long>::max() / 4;

int g_failures = 0;

void expect(bool condition, const std::string& message) {
  if (condition) {
    return;
  }
  ++g_failures;
  std::cerr << "[FAIL] " << message << '\n';
}

DistResult dijkstra_oracle(const WeightedAdj& adj, int source) {
  const int n = static_cast<int>(adj.size());
  std::vector<long long> dist(n, kInf);
  std::vector<int> parent(n, -1);

  using Node = std::pair<long long, int>;
  std::priority_queue<Node, std::vector<Node>, std::greater<Node>> pq;
  dist[source] = 0;
  pq.emplace(0, source);

  while (!pq.empty()) {
    const auto [d, u] = pq.top();
    pq.pop();
    if (d != dist[u]) {
      continue;
    }
    for (const auto [v, w] : adj[u]) {
      if (w < 0) {
        // Negative weights are outside Dijkstra assumptions; ignore in this oracle.
        continue;
      }
      const long long cand = d + static_cast<long long>(w);
      if (cand < dist[v]) {
        dist[v] = cand;
        parent[v] = u;
        pq.emplace(cand, v);
      }
    }
  }
  return {dist, parent};
}

std::optional<std::vector<int>> reconstruct_path(
    int source,
    int target,
    const std::vector<int>& parent
) {
  std::vector<int> rev;
  int cur = target;
  while (cur >= 0) {
    rev.push_back(cur);
    if (cur == source) {
      break;
    }
    cur = parent[cur];
  }
  if (rev.empty() || rev.back() != source) {
    return std::nullopt;
  }
  std::reverse(rev.begin(), rev.end());
  return rev;
}

std::optional<long long> shortest_path_via_oracle(
    const WeightedAdj& adj,
    int source,
    int via,
    int target
) {
  const auto [dist_s, parent_s] = dijkstra_oracle(adj, source);
  const auto [dist_v, parent_v] = dijkstra_oracle(adj, via);
  if (dist_s[via] >= kInf || dist_v[target] >= kInf) {
    return std::nullopt;
  }
  const auto left = reconstruct_path(source, via, parent_s);
  const auto right = reconstruct_path(via, target, parent_v);
  if (!left.has_value() || !right.has_value()) {
    return std::nullopt;
  }
  return dist_s[via] + dist_v[target];
}

bool has_undirected_edge(const UndirectedAdj& adj, int u, int v) {
  const auto& row = adj[u];
  return std::find(row.begin(), row.end(), v) != row.end();
}

bool is_valid_subgraph_mapping(
    const UndirectedAdj& pattern,
    const UndirectedAdj& target,
    const std::vector<int>& mapping
) {
  const int p_n = static_cast<int>(pattern.size());
  const int t_n = static_cast<int>(target.size());
  if (static_cast<int>(mapping.size()) != p_n) {
    return false;
  }
  std::unordered_set<int> used;
  used.reserve(static_cast<size_t>(p_n) * 2);
  for (int p = 0; p < p_n; ++p) {
    const int t = mapping[p];
    if (t < 0 || t >= t_n) {
      return false;
    }
    if (!used.insert(t).second) {
      return false;
    }
  }
  for (int u = 0; u < p_n; ++u) {
    for (int v : pattern[u]) {
      if (v < 0 || v >= p_n || v == u) {
        continue;
      }
      if (!has_undirected_edge(target, mapping[u], mapping[v])) {
        return false;
      }
    }
  }
  return true;
}

long long path_weight(const WeightedAdj& adj, const std::vector<int>& path) {
  long long total = 0;
  for (size_t i = 1; i < path.size(); ++i) {
    const int u = path[i - 1];
    const int v = path[i];
    int best = std::numeric_limits<int>::max();
    for (const auto [to, w] : adj[u]) {
      if (to == v && w >= 0 && w < best) {
        best = w;
      }
    }
    if (best == std::numeric_limits<int>::max()) {
      return kInf;
    }
    total += best;
  }
  return total;
}

void add_undirected_edge(UndirectedAdj& adj, int u, int v) {
  if (u == v) {
    return;
  }
  if (!has_undirected_edge(adj, u, v)) {
    adj[u].push_back(v);
  }
  if (!has_undirected_edge(adj, v, u)) {
    adj[v].push_back(u);
  }
}

void normalize_undirected(UndirectedAdj& adj) {
  for (auto& row : adj) {
    std::sort(row.begin(), row.end());
    row.erase(std::unique(row.begin(), row.end()), row.end());
  }
}

UndirectedAdj random_undirected_graph(std::mt19937& rng, int n, double edge_prob) {
  std::bernoulli_distribution pick(edge_prob);
  UndirectedAdj adj(static_cast<size_t>(n));
  for (int u = 0; u < n; ++u) {
    for (int v = u + 1; v < n; ++v) {
      if (pick(rng)) {
        add_undirected_edge(adj, u, v);
      }
    }
  }
  normalize_undirected(adj);
  return adj;
}

WeightedAdj random_weighted_graph(std::mt19937& rng, int n, double edge_prob) {
  std::bernoulli_distribution pick(edge_prob);
  std::uniform_int_distribution<int> wdist(1, 20);
  WeightedAdj adj(static_cast<size_t>(n));
  for (int u = 0; u < n; ++u) {
    for (int v = 0; v < n; ++v) {
      if (u == v) {
        continue;
      }
      if (pick(rng)) {
        adj[u].push_back({v, wdist(rng)});
      }
    }
  }
  return adj;
}

void test_shortest_path_edge_cases() {
  {
    // Multi-edge and disconnected check.
    WeightedAdj adj(5);
    adj[0].push_back({1, 7});
    adj[0].push_back({1, 3});
    adj[1].push_back({2, 2});
    adj[3].push_back({4, 1});
    const auto [dist, parent] = dijkstra_oracle(adj, 0);
    expect(dist[2] == 5, "multi-edge case should choose minimum weight edge");
    expect(dist[4] >= kInf, "disconnected target should remain unreachable");
    const auto path = reconstruct_path(0, 2, parent);
    expect(path.has_value(), "reachable node should reconstruct a path");
    if (path.has_value()) {
      expect(path_weight(adj, *path) == dist[2], "reconstructed path weight should match shortest distance");
    }
  }
  {
    // High-degree hub and negative-like trap (negative ignored by oracle).
    WeightedAdj adj(6);
    for (int v = 1; v < 6; ++v) {
      adj[0].push_back({v, 2});
    }
    adj[1].push_back({5, 1});
    adj[0].push_back({5, -100});  // outside non-negative domain; ignored
    const auto [dist, _parent] = dijkstra_oracle(adj, 0);
    expect(dist[5] == 2, "negative-like trap edge should not corrupt non-negative shortest path oracle");
  }
  {
    WeightedAdj adj(6);
    adj[0].push_back({1, 2});
    adj[1].push_back({2, 2});
    adj[2].push_back({5, 2});
    adj[0].push_back({3, 1});
    adj[3].push_back({4, 1});
    adj[4].push_back({5, 1});
    const auto via = shortest_path_via_oracle(adj, 0, 2, 5);
    expect(via.has_value(), "via-node path should exist for reachable via and target");
    if (via.has_value()) {
      expect(*via == 6, "via-node shortest path should be source->via plus via->target");
    }
    const auto no_via = shortest_path_via_oracle(adj, 0, 4, 2);
    expect(!no_via.has_value(), "via-node oracle should report no-path when via->target is unreachable");
  }
}

void test_subgraph_mapping_edge_cases() {
  UndirectedAdj pattern(3);
  add_undirected_edge(pattern, 0, 1);
  add_undirected_edge(pattern, 1, 2);
  add_undirected_edge(pattern, 0, 2);
  normalize_undirected(pattern);

  UndirectedAdj target(5);
  add_undirected_edge(target, 1, 2);
  add_undirected_edge(target, 2, 3);
  add_undirected_edge(target, 1, 3);
  add_undirected_edge(target, 0, 4);
  normalize_undirected(target);

  expect(
      is_valid_subgraph_mapping(pattern, target, {1, 2, 3}),
      "triangle mapping should be valid in target triangle"
  );
  expect(
      !is_valid_subgraph_mapping(pattern, target, {1, 1, 3}),
      "mapping must be injective"
  );
  expect(
      !is_valid_subgraph_mapping(pattern, target, {0, 1, 4}),
      "mapping should fail when required pattern edge is missing in target"
  );
}

void test_shortest_path_property_fuzz() {
  std::mt19937 rng(1337);
  for (int iter = 0; iter < 250; ++iter) {
    const int n = 6 + (iter % 7);
    auto adj = random_weighted_graph(rng, n, 0.22);
    const auto [dist, parent] = dijkstra_oracle(adj, 0);

    // Optimality inequality: dist[v] <= dist[u] + w for all edges (u,v,w).
    for (int u = 0; u < n; ++u) {
      if (dist[u] >= kInf) {
        continue;
      }
      for (const auto [v, w] : adj[u]) {
        if (w < 0) {
          continue;
        }
        expect(
            dist[v] <= dist[u] + static_cast<long long>(w),
            "shortest-path optimality inequality violated on random fuzz graph"
        );
      }
    }

    // Path reconstruction property for reachable targets.
    for (int target = 0; target < n; ++target) {
      if (dist[target] >= kInf) {
        continue;
      }
      const auto path = reconstruct_path(0, target, parent);
      expect(path.has_value(), "reachable target should reconstruct in fuzz case");
      if (!path.has_value()) {
        continue;
      }
      expect(
          path_weight(adj, *path) == dist[target],
          "reconstructed fuzz path weight must equal shortest distance"
      );
    }
  }
}

void test_subgraph_mapping_property_fuzz() {
  std::mt19937 rng(2026);
  for (int iter = 0; iter < 220; ++iter) {
    const int t_n = 8 + (iter % 7);
    const int p_n = 3 + (iter % 3);
    auto target = random_undirected_graph(rng, t_n, 0.35);

    // Ensure target has enough connectivity to embed pattern edges.
    for (int i = 0; i + 1 < t_n; ++i) {
      add_undirected_edge(target, i, i + 1);
    }
    normalize_undirected(target);

    std::vector<int> chosen;
    chosen.reserve(static_cast<size_t>(p_n));
    std::vector<int> pool(t_n);
    for (int i = 0; i < t_n; ++i) {
      pool[i] = i;
    }
    std::shuffle(pool.begin(), pool.end(), rng);
    for (int i = 0; i < p_n; ++i) {
      chosen.push_back(pool[i]);
    }

    UndirectedAdj pattern(static_cast<size_t>(p_n));
    for (int u = 0; u < p_n; ++u) {
      for (int v = u + 1; v < p_n; ++v) {
        if (has_undirected_edge(target, chosen[u], chosen[v])) {
          add_undirected_edge(pattern, u, v);
        }
      }
    }
    // Guarantee at least one edge in pattern.
    if (pattern[0].empty() && p_n > 1) {
      add_undirected_edge(pattern, 0, 1);
      add_undirected_edge(target, chosen[0], chosen[1]);
    }
    normalize_undirected(pattern);
    normalize_undirected(target);

    const std::vector<int> valid_mapping = chosen;
    expect(
        is_valid_subgraph_mapping(pattern, target, valid_mapping),
        "embedded mapping should validate in random property case"
    );

    std::vector<int> duplicate_mapping = valid_mapping;
    if (p_n > 1) {
      duplicate_mapping[1] = duplicate_mapping[0];
      expect(
          !is_valid_subgraph_mapping(pattern, target, duplicate_mapping),
          "duplicate target assignment should fail mapping validation"
      );
    }
  }
}

}  // namespace

int main() {
  test_shortest_path_edge_cases();
  test_subgraph_mapping_edge_cases();
  test_shortest_path_property_fuzz();
  test_subgraph_mapping_property_fuzz();

  if (g_failures != 0) {
    std::cerr << "Graph oracle tests failed: " << g_failures << '\n';
    return 1;
  }
  std::cout << "Graph oracle tests passed.\n";
  return 0;
}
