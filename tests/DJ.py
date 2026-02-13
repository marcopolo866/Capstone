import subprocess
import re
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
import os

# --- Configuration ---
# All entities are now treated as native binaries
CONFIG = {
    "Gemini": {"path": "./../src/DJ_GEM", "use_stdin": True, "color": "skyblue"},
    "GPT": {"path": "./../src/DJ_GPT", "use_stdin": False, "color": "lightgreen"},
    "Nyaan (Baseline)": {"path": "./../baselines/dijkstra", "use_stdin": False, "color": "yellow"}
}
DATA_FILE = "./../data/dijkstra_weighted_graph_2.csv"
ITERATIONS = 100

def run_single_benchmark(label, path, use_stdin):
    times = []
    memory_kb = []
    print(f"Starting {ITERATIONS} runs for {label}...")
    
    for i in range(1, ITERATIONS + 1):
        # Build command based on how the specific binary accepts the input file
        if use_stdin:
            cmd = f"/usr/bin/time -l {path} < {DATA_FILE}"
        else:
            cmd = f"/usr/bin/time -l {path} {DATA_FILE}"
            
        process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        # 1. Extract Internal Time (seconds to ms)
        # Matches the "Runtime: 0.000s" format added to all three source files
        time_match = re.search(r"Runtime:\s+([\d.]+)", process.stdout)
        if time_match:
            times.append(float(time_match.group(1)) * 1000)
            
        # 2. Extract Max RSS (macOS bytes to KB)
        mem_match = re.search(r"(\d+)\s+maximum resident set size", process.stderr)
        if mem_match:
            memory_kb.append(int(mem_match.group(1)) / 1024)

        if i % 25 == 0:
            print(f"  {label} Progress: {i}/{ITERATIONS}...")

    return np.array(times), np.array(memory_kb)

def get_stats(data):
    if len(data) == 0: return 0, 0
    mean = np.mean(data)
    std_err = stats.sem(data)
    ci = std_err * stats.t.ppf((1 + 0.95) / 2., len(data) - 1)
    return mean, ci

def compare_and_plot(results):
    labels = list(results.keys())
    colors = [results[l]['color'] for l in labels]
    
    means_t, cis_t = zip(*[get_stats(results[l]['times']) for l in labels])
    means_m, cis_m = zip(*[get_stats(results[l]['memory']) for l in labels])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8))
    plt.subplots_adjust(wspace=0.3)

    # --- Plot 1: Internal Execution Time ---
    bars1 = ax1.bar(labels, means_t, yerr=cis_t, capsize=10, 
                    color=colors, edgecolor='black', alpha=0.8)
    ax1.set_ylabel("Execution Time (ms)")
    ax1.set_title(f"Runtime Efficiency (95% CI)")
    ax1.grid(axis='y', linestyle='--', alpha=0.6)
    
    for bar, m, c in zip(bars1, means_t, cis_t):
        ax1.text(bar.get_x() + bar.get_width()/2, m + c, f"{m:.4f} ms\n±{c:.4f}", 
                 ha='center', va='bottom', fontweight='bold')

    # --- Plot 2: Peak RAM Usage ---
    bars2 = ax2.bar(labels, means_m, yerr=cis_m, capsize=10, 
                    color=colors, edgecolor='black', alpha=0.8)
    ax2.set_ylabel("Peak RAM Usage (kb)")
    ax2.set_title(f"Memory Footprint (95% CI)")
    ax2.grid(axis='y', linestyle='--', alpha=0.6)

    for bar, m, c in zip(bars2, means_m, cis_m):
        ax2.text(bar.get_x() + bar.get_width()/2, m + c, f"{m:.1f} KB\n±{c:.2f}", 
                 ha='center', va='bottom', fontweight='bold')

    plt.suptitle(f"Head-to-Head Performance (N=7)", fontsize=16)
    plt.savefig("dijkstra_native_comparison.png")
    print(f"\nBenchmark complete. Image saved to 'dijkstra_native_comparison.png'")
    plt.show()

if __name__ == "__main__":
    all_results = {}
    for label, info in CONFIG.items():
        t, m = run_single_benchmark(label, info['path'], info['use_stdin'])
        if len(t) > 0:
            all_results[label] = {'times': t, 'memory': m, 'color': info['color']}
    
    if len(all_results) > 0:
        compare_and_plot(all_results)