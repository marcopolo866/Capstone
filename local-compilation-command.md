# Local Compilation Command

Run from the repository root. These commands compile the binaries used by the current native benchmarking / GitHub artifact pipeline outputs.

## Windows (Git Bash / MSYS2 MinGW64)

```bash
git submodule update --init --recursive && g++ -std=c++17 -O3 -I "baselines/nyaan-library" "baselines/dijkstra_main.cpp" -o "baselines/dijkstra" && g++ -std=c++17 -O3 "src/[CHATGPT] Shortest Path.cpp" -o "src/dijkstra_llm" && g++ -std=c++17 -O3 "src/[GEMINI] Shortest Path.cpp" -o "src/dijkstra_gemini" && make -C baselines/vf3lib vf3 CFLAGS="-std=c++11 -O3 -DNDEBUG -Wno-deprecated" && g++ -std=c++17 -O3 "src/[GEMINI] Subgraph Isomorphism.cpp" -o "src/vf3" && g++ -std=c++17 -O3 "src/[CHATGPT] Subgraph Isomorphism.cpp" -o "src/chatvf3" && g++ -std=c++17 -O3 "src/[CHATGPT] Glasgow.cpp" -o "src/glasgow_chatgpt" && g++ -std=c++17 -O3 "src/[GEMINI] Glasgow.cpp" -o "src/glasgow_gemini" && cmake -S baselines/glasgow-subgraph-solver -B baselines/glasgow-subgraph-solver/build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-O3" && cmake --build baselines/glasgow-subgraph-solver/build --config Release --parallel
```

## macOS

```bash
git submodule update --init --recursive && g++ -std=c++17 -O3 -I "baselines/nyaan-library" "baselines/dijkstra_main.cpp" -o "baselines/dijkstra" && g++ -std=c++17 -O3 "src/[CHATGPT] Shortest Path.cpp" -o "src/dijkstra_llm" && g++ -std=c++17 -O3 "src/[GEMINI] Shortest Path.cpp" -o "src/dijkstra_gemini" && make -C baselines/vf3lib vf3 CFLAGS="-std=c++11 -O3 -DNDEBUG -Wno-deprecated" && g++ -std=c++17 -O3 "src/[GEMINI] Subgraph Isomorphism.cpp" -o "src/vf3" && g++ -std=c++17 -O3 "src/[CHATGPT] Subgraph Isomorphism.cpp" -o "src/chatvf3" && g++ -std=c++17 -O3 "src/[CHATGPT] Glasgow.cpp" -o "src/glasgow_chatgpt" && g++ -std=c++17 -O3 "src/[GEMINI] Glasgow.cpp" -o "src/glasgow_gemini" && cmake -S baselines/glasgow-subgraph-solver -B baselines/glasgow-subgraph-solver/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-O3" && cmake --build baselines/glasgow-subgraph-solver/build --config Release --parallel
```

## Linux

```bash
git submodule update --init --recursive && g++ -std=c++17 -O3 -I "baselines/nyaan-library" "baselines/dijkstra_main.cpp" -o "baselines/dijkstra" && g++ -std=c++17 -O3 "src/[CHATGPT] Shortest Path.cpp" -o "src/dijkstra_llm" && g++ -std=c++17 -O3 "src/[GEMINI] Shortest Path.cpp" -o "src/dijkstra_gemini" && make -C baselines/vf3lib vf3 CFLAGS="-std=c++11 -O3 -DNDEBUG -Wno-deprecated" && g++ -std=c++17 -O3 "src/[GEMINI] Subgraph Isomorphism.cpp" -o "src/vf3" && g++ -std=c++17 -O3 "src/[CHATGPT] Subgraph Isomorphism.cpp" -o "src/chatvf3" && g++ -std=c++17 -O3 "src/[CHATGPT] Glasgow.cpp" -o "src/glasgow_chatgpt" && g++ -std=c++17 -O3 "src/[GEMINI] Glasgow.cpp" -o "src/glasgow_gemini" && cmake -S baselines/glasgow-subgraph-solver -B baselines/glasgow-subgraph-solver/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-O3" && cmake --build baselines/glasgow-subgraph-solver/build --config Release --parallel
```
