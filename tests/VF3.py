import subprocess
import re
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
import os

# --- Configuration ---
ENTITY_A_BIN = "./../src/VF3_GEM" 
ENTITY_B_BIN = "./../src/VF3_GPT" 
ENTITY_C_BIN = "./../baselines/vf3lib/bin/vf3"

PATTERN = "./../data/VF3_SUB_400.grf"
TARGET = "./../data/VF3_400.grf"
ITERATIONS = 50 

def run_benchmark(binary_path, label, is_baseline_c=False):
    times = []
    memory_kb = []
    print(f"\nBenchmarking {label} ({binary_path})...")
    
    for i in range(1, ITERATIONS + 1):
        if is_baseline_c:
            cmd = f"/usr/bin/time -l {binary_path} -r 0 {PATTERN} {TARGET}"
        else:
            cmd = f"/usr/bin/time -l {binary_path} {PATTERN} {TARGET}"
            
        process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        # --- Time Extraction ---
        if is_baseline_c:
            for line in process.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        times.append(float(parts[2]) * 1000)
                    except ValueError: continue
        else:
            time_match = re.findall(r"^[0-9]+\.[0-9]+$", process.stdout, re.MULTILINE)
            if time_match:
                times.append(float(time_match[-1]))
            
        # --- Memory Extraction ---
        mem_match = re.search(r"(\d+)\s+maximum resident set size", process.stderr)
        if mem_match:
            memory_kb.append(int(mem_match.group(1)) / 1024)

        if i % 10 == 0:
            print(f"  Progress: {i}/{ITERATIONS}...")

    return np.array(times), np.array(memory_kb)

def get_stats(data):
    """Returns mean and 95% CI margin of error."""
    if len(data) < 2: return 0, 0
    mean = np.mean(data)
    std_err = stats.sem(data)
    ci = std_err * stats.t.ppf((1 + 0.95) / 2., len(data) - 1)
    return mean, ci

def analyze_and_compare(data_a, data_b, data_c):
    # Process Stats
    t_mean_a, t_ci_a = get_stats(data_a[0])
    t_mean_b, t_ci_b = get_stats(data_b[0])
    t_mean_c, t_ci_c = get_stats(data_c[0])
    
    m_mean_a, m_ci_a = get_stats(data_a[1])
    m_mean_b, m_ci_b = get_stats(data_b[1])
    m_mean_c, m_ci_c = get_stats(data_c[1])

    # Print Summary Table (Now including Memory CI)
    # 
    header = f"{'Algorithm':<15} | {'Time (ms)':<18} | {'Memory (kB)':<18}"
    sep = "-" * len(header)
    print("\n" + "=" * len(header))
    print(header)
    print(sep)
    print(f"{'Gemini':<15} | {t_mean_a:>7.3f} ±{t_ci_a:.3f} | {m_mean_a:>8.1f} ±{m_ci_a:.2f}")
    print(f"{'GPT':<15} | {t_mean_b:>7.3f} ±{t_ci_b:.3f} | {m_mean_b:>8.1f} ±{m_ci_b:.2f}")
    print(f"{'VFLib (Baseline)':<15} | {t_mean_c:>7.3f} ±{t_ci_c:.3f} | {m_mean_c:>8.1f} ±{m_ci_c:.2f}")
    print("=" * len(header) + "\n")

    # Plotting
    labels = ['Gemini', 'GPT', 'VFLib (Baseline)']
    plt.figure(figsize=(15, 7))
    
    # Subplot 1: Time
    ax1 = plt.subplot(1, 2, 1)
    ax1.bar(labels, [t_mean_a, t_mean_b, t_mean_c], yerr=[t_ci_a, t_ci_b, t_ci_c], 
            capsize=10, color=['#5dade2', '#58d68d', '#f4d03f'], alpha=0.8)
    ax1.set_ylabel("Execution Time (ms)")
    ax1.set_title("Runtime Efficiency (95% CI)")
    ax1.grid(axis='y', alpha=0.3)

    # Subplot 2: Memory
    ax2 = plt.subplot(1, 2, 2)
    ax2.bar(labels, [m_mean_a, m_mean_b, m_mean_c], yerr=[m_ci_a, m_ci_b, m_ci_c], 
            capsize=10, color=['#5dade2', '#58d68d', '#f4d03f'], alpha=0.8)
    ax2.set_ylabel("Peak RAM Usage (kB)")
    ax2.set_title("Memory Footprint (95% CI)")
    ax2.grid(axis='y', alpha=0.3)

    n_value = os.path.basename(PATTERN).split('_')[-1].split('.')[0]
    plt.suptitle(f"Head-to-Head Performance (N={n_value})", fontsize=16)
    plt.savefig("final_comparison_report.png")
    plt.show()

if __name__ == "__main__":
    res_a = run_benchmark(ENTITY_A_BIN, "Entity A")
    res_b = run_benchmark(ENTITY_B_BIN, "Entity B")
    res_c = run_benchmark(ENTITY_C_BIN, "Entity C (Baseline)", is_baseline_c=True)
    
    if all(len(r[0]) > 0 for r in [res_a, res_b, res_c]):
        analyze_and_compare(res_a, res_b, res_c)