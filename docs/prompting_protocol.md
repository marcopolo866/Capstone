# Prompting Protocol for LLM Graph Algorithm Evaluation

**Version:** 1.0
**Date:** 10/09/2025

This document outlines the standardized methodology for interacting with ChatGPT to ensure reproducibility and consistency.

## 1.0 LLM Configuration

- **Model:** GPT-4-Turbo (via the standard ChatGPT web interface)
- **Temperature:** 0.7 (default value that cannot be changed as a free user; in between "creative" outputs and "factual" outputs)
- **Conversation Context:** Each of the three problems (Shortest Path, Via-Node Path, Subgraph Isomorphism) will be handled in a completely separate, new conversation thread. This prevents the model from using context from one problem to influence its solution for another.

## 2.0 Prompting Strategy

Our interaction with the LLM will follow a three-stage process:

1.  **Seed Prompt:** A detailed initial prompt to generate the first draft of the C++ code.
2.  **Remediation Prompts:** Follow-up prompts to ask the LLM to fix specific compilation or runtime errors.
3.  **Optimization Prompts:** Follow-up prompts to ask the LLM for performance improvements after the code is proven correct.

## 3.0 Seed Prompt Templates

The following templates will be used to generate the initial code.

### 3.1 Seed Prompt: Single-Pair Shortest Path (Dijkstra's)

    Act as an expert C++ programmer specializing in high-performance graph algorithms.

    Write a single, complete C++20 function that finds the shortest path between two nodes in a weighted, directed graph using Dijkstra's algorithm.

    The function signature must be:
    `double shortest_path(const std::unordered_map<int, std::vector<std::pair<int, double>>>& graph, int start_node, int end_node);`

    **Constraints:**
    1.  The priority queue must be `std::priority_queue`.
    2.  Use only standard C++20 libraries. Do not use external libraries like Boost.
    3.  Return the total weight of the shortest path, or `std::numeric_limits<double>::infinity()` if no path exists.
    4.  Add comments explaining the main parts of the algorithm.

*(You will create a third prompt for the Via-Node Path problem following this same structure.)*

### 3.2 Seed Prompt: Subgraph Isomorphism (Backtracking)

    Act as an expert C++ programmer specializing in high-performance graph algorithms.

    Write a single, complete C++20 function that solves the subgraph isomorphism problem for two unlabeled, directed graphs using a backtracking search algorithm.

    The function signature must be:
    `bool has_subgraph_isomorphism(const std::unordered_map<int, std::vector<int>>& target_graph, const std::unordered_map<int, std::vector<int>>& pattern_graph);`

    **Constraints:**
    1.  The algorithm must recursively build a mapping and backtrack when a dead end is reached.
    2.  The function should stop and return `true` as soon as the first valid mapping is found. Return `false` if no mapping exists.
    3.  Use only standard C++20 libraries.
    4.  Add comments explaining the core backtracking logic.

## 4.0 Follow-up Prompt Templates

- **For Remediation:** "The previous code failed to compile with the error: `[paste full compiler error here]`. Please fix the code to resolve this specific error."
- **For Optimization:** "The current implementation is correct but may be slow. Can you refactor the code to [describe a specific change, e.g., 'use a different data structure for the visited set'] and explain the performance trade-offs?"