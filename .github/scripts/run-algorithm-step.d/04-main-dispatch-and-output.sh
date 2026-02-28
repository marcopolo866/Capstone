EXIT_CODE=0

case "$ALGORITHM" in
  dijkstra)
    dijkstra_baseline_out=""
    dijkstra_baseline_ms_runs=""
    dijkstra_baseline_rss_runs=""
    dijkstra_gemini_out=""
    dijkstra_gemini_ms_runs=""
    dijkstra_gemini_rss_runs=""
    dijkstra_llm_out=""
    dijkstra_llm_ms_runs=""
    dijkstra_llm_rss_runs=""
    dijkstra_gemini_match=0
    dijkstra_gemini_total=0
    dijkstra_gemini_mismatch=0
    dijkstra_first_gemini_mismatch_baseline=""
    dijkstra_first_gemini_mismatch_gemini=""
    dijkstra_first_gemini_mismatch_baseline_norm=""
    dijkstra_first_gemini_mismatch_gemini_norm=""
    dijkstra_match=0
    dijkstra_total=0
    dijkstra_mismatch=0
    dijkstra_first_mismatch_baseline=""
    dijkstra_first_mismatch_llm=""
    dijkstra_first_mismatch_baseline_norm=""
    dijkstra_first_mismatch_llm_norm=""

    # Phase 1: setup + warmup (web UI fills the progress bar once here)
    PROGRESS_STAGE="setup"
    progress_set_phase "Setting up Testing Environment"
    if [ "${WARMUP_REQUESTED:-0}" -gt 0 ]; then
      if [ "$INPUT_MODE" = "generate" ]; then
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          if ! generate_graphs_for_run "dijkstra_baseline_warmup" "w${i}"; then
            EXIT_CODE=1
            break
          fi
          if ! run_capture out dur ./baselines/dijkstra "${FILES[0]}"; then
            echo "[Warmup] Dijkstra baseline failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
        done
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          if ! generate_graphs_for_run "dijkstra_llm_warmup" "w${i}"; then
            EXIT_CODE=1
            break
          fi
          if ! run_capture out dur ./src/dijkstra_llm "${FILES[0]}"; then
            echo "[Warmup] Dijkstra ChatGPT failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
        done
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          if ! generate_graphs_for_run "dijkstra_gemini_warmup" "w${i}"; then
            EXIT_CODE=1
            break
          fi
          if ! run_capture out dur ./src/dijkstra_gemini "${FILES[0]}"; then
            echo "[Warmup] Dijkstra gemini failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
        done
      else
        if ! warmup_only "Dijkstra baseline" ./baselines/dijkstra "${FILES[0]}"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Dijkstra ChatGPT" ./src/dijkstra_llm "${FILES[0]}"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Dijkstra gemini" ./src/dijkstra_gemini "${FILES[0]}"; then
          EXIT_CODE=1
        fi
      fi
    else
      progress_setup_tick
    fi
    PROGRESS_SETUP_DONE="$PROGRESS_SETUP_TOTAL"
    progress_update_check_run "in_progress" || true

    # Phase 2: measured iterations (web UI resets the bar and fills again here)
    if [ "${SUBGRAPH_PHASE:-}" = "glasgow" ]; then
      PROGRESS_STAGE="glasgow"
      PROGRESS_PHASE="Running Glasgow..."
    else
      PROGRESS_STAGE="tests"
      PROGRESS_PHASE=""
    fi
    PROGRESS_DONE_TICKS=0
    progress_update_check_run "in_progress" || true
    WARMUP=0

    progress_set_phase "Dijkstra baseline"
    if [ "$INPUT_MODE" = "generate" ]; then
      dijkstra_baseline_out=""
      dijkstra_baseline_ms_runs=""
      dijkstra_baseline_rss_runs=""
      declare -a dijkstra_generated_files
      declare -a dijkstra_baseline_norm_by_iter
      declare -a dijkstra_baseline_raw_by_iter
      out=""
      dur=""
      rss=""
      times=()
      rsses=()
      out_first=""
      for ((i=1; i<=ITERATIONS; i++)); do
        if ! generate_graphs_for_run "dijkstra_baseline" "$i"; then
          EXIT_CODE=1
          break
        fi
        if ! run_capture_rss out dur rss ./baselines/dijkstra "${FILES[0]}"; then
          EXIT_CODE=1
          echo "[Dijkstra Baseline] failed to run." >> outputs/result.txt
          break
        fi
        dijkstra_generated_files[$i]="${FILES[0]}"
        dijkstra_baseline_raw_by_iter[$i]="$out"
        dijkstra_baseline_norm_by_iter[$i]="$(normalize_dijkstra_answer <<<"$out")"
        if [ $i -eq 1 ]; then
          out_first="$out"
        fi
        times+=("$dur")
        rsses+=("$rss")
        progress_tick
      done
      dijkstra_baseline_out="$out_first"
      dijkstra_baseline_ms_runs="${times[*]}"
      dijkstra_baseline_rss_runs="${rsses[*]}"
    else
      if ! bench_capture_rss_n dijkstra_baseline_out dijkstra_baseline_ms_runs dijkstra_baseline_rss_runs "$ITERATIONS" ./baselines/dijkstra "${FILES[0]}"; then
        EXIT_CODE=1
        echo "[Dijkstra Baseline] failed to run." >> outputs/result.txt
      fi
    fi
    if [ -n "${dijkstra_baseline_ms_runs:-}" ]; then
      read dijkstra_baseline_ms_median dijkstra_baseline_ms_mean dijkstra_baseline_ms_stdev dijkstra_baseline_ms_min dijkstra_baseline_ms_max dijkstra_baseline_ms_n <<< "$(calc_stats_ms $dijkstra_baseline_ms_runs)"
      dijkstra_baseline_ms="$dijkstra_baseline_ms_median"
      if [ -n "${dijkstra_baseline_rss_runs:-}" ]; then
        read dijkstra_baseline_rss_median dijkstra_baseline_rss_mean dijkstra_baseline_rss_stdev dijkstra_baseline_rss_min dijkstra_baseline_rss_max dijkstra_baseline_rss_n <<< "$(calc_stats_kb $dijkstra_baseline_rss_runs)"
        dijkstra_baseline_rss_kb="$dijkstra_baseline_rss_median"
      fi
      {
        echo "[Dijkstra Baseline]"
        echo "$dijkstra_baseline_out"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${dijkstra_baseline_ms_median:-}" ]; then
          echo "Runtime (ms): median=$dijkstra_baseline_ms_median mean=$dijkstra_baseline_ms_mean stdev=$dijkstra_baseline_ms_stdev min=$dijkstra_baseline_ms_min max=$dijkstra_baseline_ms_max"
        fi
        if [ -n "${dijkstra_baseline_rss_median:-}" ]; then
          echo "Max RSS (kB): median=$dijkstra_baseline_rss_median mean=$dijkstra_baseline_rss_mean stdev=$dijkstra_baseline_rss_stdev min=$dijkstra_baseline_rss_min max=$dijkstra_baseline_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi
    progress_set_phase "Dijkstra ChatGPT"
    if [ "$INPUT_MODE" = "generate" ]; then
      dijkstra_llm_out=""
      dijkstra_llm_ms_runs=""
      dijkstra_llm_rss_runs=""
      out=""
      dur=""
      rss=""
      times=()
      rsses=()
      out_first=""
      for ((i=1; i<=ITERATIONS; i++)); do
        dijkstra_input_file="${dijkstra_generated_files[$i]-}"
        if [ -z "$dijkstra_input_file" ] || [ ! -f "$dijkstra_input_file" ]; then
          EXIT_CODE=1
          echo "[Dijkstra ChatGPT] missing generated input for iteration ${i}." >> outputs/result.txt
          break
        fi
        if ! run_capture_rss out dur rss ./src/dijkstra_llm "$dijkstra_input_file"; then
          EXIT_CODE=1
          echo "[Dijkstra ChatGPT] failed to run." >> outputs/result.txt
          break
        fi
        baseline_norm="${dijkstra_baseline_norm_by_iter[$i]-}"
        llm_norm="$(normalize_dijkstra_answer <<<"$out")"
        if [ -n "$baseline_norm" ] || [ -n "$llm_norm" ]; then
          dijkstra_total=$((dijkstra_total + 1))
          if [ -n "$baseline_norm" ] && [ "$baseline_norm" = "$llm_norm" ]; then
            dijkstra_match=$((dijkstra_match + 1))
          else
            dijkstra_mismatch=$((dijkstra_mismatch + 1))
            if [ -z "${dijkstra_first_mismatch_baseline_norm:-}" ] && [ -z "${dijkstra_first_mismatch_llm_norm:-}" ]; then
              dijkstra_first_mismatch_baseline="${dijkstra_baseline_raw_by_iter[$i]-}"
              dijkstra_first_mismatch_llm="$out"
              dijkstra_first_mismatch_baseline_norm="$baseline_norm"
              dijkstra_first_mismatch_llm_norm="$llm_norm"
            fi
          fi
        fi
        if [ $i -eq 1 ]; then
          out_first="$out"
        fi
        times+=("$dur")
        rsses+=("$rss")
        progress_tick
      done
      dijkstra_llm_out="$out_first"
      dijkstra_llm_ms_runs="${times[*]}"
      dijkstra_llm_rss_runs="${rsses[*]}"
    else
      if ! bench_capture_rss_n dijkstra_llm_out dijkstra_llm_ms_runs dijkstra_llm_rss_runs "$ITERATIONS" ./src/dijkstra_llm "${FILES[0]}"; then
        EXIT_CODE=1
        echo "[Dijkstra ChatGPT] failed to run." >> outputs/result.txt
      fi
    fi
    if [ -n "${dijkstra_llm_ms_runs:-}" ]; then
      read dijkstra_llm_ms_median dijkstra_llm_ms_mean dijkstra_llm_ms_stdev dijkstra_llm_ms_min dijkstra_llm_ms_max dijkstra_llm_ms_n <<< "$(calc_stats_ms $dijkstra_llm_ms_runs)"
      dijkstra_llm_ms="$dijkstra_llm_ms_median"
      if [ -n "${dijkstra_llm_rss_runs:-}" ]; then
        read dijkstra_llm_rss_median dijkstra_llm_rss_mean dijkstra_llm_rss_stdev dijkstra_llm_rss_min dijkstra_llm_rss_max dijkstra_llm_rss_n <<< "$(calc_stats_kb $dijkstra_llm_rss_runs)"
        dijkstra_llm_rss_kb="$dijkstra_llm_rss_median"
      fi
      {
        echo "[Dijkstra ChatGPT]"
        echo "$dijkstra_llm_out"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${dijkstra_llm_ms_median:-}" ]; then
          echo "Runtime (ms): median=$dijkstra_llm_ms_median mean=$dijkstra_llm_ms_mean stdev=$dijkstra_llm_ms_stdev min=$dijkstra_llm_ms_min max=$dijkstra_llm_ms_max"
        fi
        if [ -n "${dijkstra_llm_rss_median:-}" ]; then
          echo "Max RSS (kB): median=$dijkstra_llm_rss_median mean=$dijkstra_llm_rss_mean stdev=$dijkstra_llm_rss_stdev min=$dijkstra_llm_rss_min max=$dijkstra_llm_rss_max"
        fi
        if [ -n "${dijkstra_baseline_ms_mean:-}" ] && [ -n "${dijkstra_llm_ms_mean:-}" ]; then
          t_test_line "runtime ms baseline vs ChatGPT" \
            "$dijkstra_baseline_ms_mean" "$dijkstra_baseline_ms_stdev" "$dijkstra_baseline_ms_n" \
            "$dijkstra_llm_ms_mean" "$dijkstra_llm_ms_stdev" "$dijkstra_llm_ms_n"
        fi
        echo
      } >> outputs/result.txt
    fi
    progress_set_phase "Dijkstra gemini"
    if [ "$INPUT_MODE" = "generate" ]; then
      dijkstra_gemini_out=""
      dijkstra_gemini_ms_runs=""
      dijkstra_gemini_rss_runs=""
      out=""
      dur=""
      rss=""
      times=()
      rsses=()
      out_first=""
      for ((i=1; i<=ITERATIONS; i++)); do
        dijkstra_input_file="${dijkstra_generated_files[$i]-}"
        if [ -z "$dijkstra_input_file" ] || [ ! -f "$dijkstra_input_file" ]; then
          EXIT_CODE=1
          echo "[Dijkstra Gemini] missing generated input for iteration ${i}." >> outputs/result.txt
          break
        fi
        if ! run_capture_rss out dur rss ./src/dijkstra_gemini "$dijkstra_input_file"; then
          EXIT_CODE=1
          echo "[Dijkstra Gemini] failed to run." >> outputs/result.txt
          break
        fi
        baseline_norm="${dijkstra_baseline_norm_by_iter[$i]-}"
        gemini_norm="$(normalize_dijkstra_answer <<<"$out")"
        if [ -n "$baseline_norm" ] || [ -n "$gemini_norm" ]; then
          dijkstra_gemini_total=$((dijkstra_gemini_total + 1))
          if [ -n "$baseline_norm" ] && [ "$baseline_norm" = "$gemini_norm" ]; then
            dijkstra_gemini_match=$((dijkstra_gemini_match + 1))
          else
            dijkstra_gemini_mismatch=$((dijkstra_gemini_mismatch + 1))
            if [ -z "${dijkstra_first_gemini_mismatch_baseline_norm:-}" ] && [ -z "${dijkstra_first_gemini_mismatch_gemini_norm:-}" ]; then
              dijkstra_first_gemini_mismatch_baseline="${dijkstra_baseline_raw_by_iter[$i]-}"
              dijkstra_first_gemini_mismatch_gemini="$out"
              dijkstra_first_gemini_mismatch_baseline_norm="$baseline_norm"
              dijkstra_first_gemini_mismatch_gemini_norm="$gemini_norm"
            fi
          fi
        fi
        if [ $i -eq 1 ]; then
          out_first="$out"
        fi
        times+=("$dur")
        rsses+=("$rss")
        progress_tick
      done
      dijkstra_gemini_out="$out_first"
      dijkstra_gemini_ms_runs="${times[*]}"
      dijkstra_gemini_rss_runs="${rsses[*]}"
    else
      if ! bench_capture_rss_n dijkstra_gemini_out dijkstra_gemini_ms_runs dijkstra_gemini_rss_runs "$ITERATIONS" ./src/dijkstra_gemini "${FILES[0]}"; then
        EXIT_CODE=1
        echo "[Dijkstra Gemini] failed to run." >> outputs/result.txt
      fi
    fi
    if [ -n "${dijkstra_gemini_ms_runs:-}" ]; then
      read dijkstra_gemini_ms_median dijkstra_gemini_ms_mean dijkstra_gemini_ms_stdev dijkstra_gemini_ms_min dijkstra_gemini_ms_max dijkstra_gemini_ms_n <<< "$(calc_stats_ms $dijkstra_gemini_ms_runs)"
      dijkstra_gemini_ms="$dijkstra_gemini_ms_median"
      if [ -n "${dijkstra_gemini_rss_runs:-}" ]; then
        read dijkstra_gemini_rss_median dijkstra_gemini_rss_mean dijkstra_gemini_rss_stdev dijkstra_gemini_rss_min dijkstra_gemini_rss_max dijkstra_gemini_rss_n <<< "$(calc_stats_kb $dijkstra_gemini_rss_runs)"
        dijkstra_gemini_rss_kb="$dijkstra_gemini_rss_median"
      fi
      {
        echo "[Dijkstra Gemini]"
        echo "$dijkstra_gemini_out"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${dijkstra_gemini_ms_median:-}" ]; then
          echo "Runtime (ms): median=$dijkstra_gemini_ms_median mean=$dijkstra_gemini_ms_mean stdev=$dijkstra_gemini_ms_stdev min=$dijkstra_gemini_ms_min max=$dijkstra_gemini_ms_max"
        fi
        if [ -n "${dijkstra_gemini_rss_median:-}" ]; then
          echo "Max RSS (kB): median=$dijkstra_gemini_rss_median mean=$dijkstra_gemini_rss_mean stdev=$dijkstra_gemini_rss_stdev min=$dijkstra_gemini_rss_min max=$dijkstra_gemini_rss_max"
        fi
        if [ -n "${dijkstra_baseline_ms_mean:-}" ] && [ -n "${dijkstra_gemini_ms_mean:-}" ]; then
          t_test_line "runtime ms baseline vs Gemini" \
            "$dijkstra_baseline_ms_mean" "$dijkstra_baseline_ms_stdev" "$dijkstra_baseline_ms_n" \
            "$dijkstra_gemini_ms_mean" "$dijkstra_gemini_ms_stdev" "$dijkstra_gemini_ms_n"
        fi
        echo
      } >> outputs/result.txt
    fi
    if [ "${dijkstra_total:-0}" -eq 0 ]; then
      dijkstra_baseline_norm="$(normalize_dijkstra_answer <<<"${dijkstra_baseline_out:-}")"
      dijkstra_llm_norm="$(normalize_dijkstra_answer <<<"${dijkstra_llm_out:-}")"
      if [ -n "$dijkstra_baseline_norm" ] || [ -n "$dijkstra_llm_norm" ]; then
        dijkstra_total=1
        if [ -n "$dijkstra_baseline_norm" ] && [ "$dijkstra_baseline_norm" = "$dijkstra_llm_norm" ]; then
          dijkstra_match=1
          dijkstra_mismatch=0
        else
          dijkstra_match=0
          dijkstra_mismatch=1
          dijkstra_first_mismatch_baseline="${dijkstra_baseline_out:-}"
          dijkstra_first_mismatch_llm="${dijkstra_llm_out:-}"
          dijkstra_first_mismatch_baseline_norm="$dijkstra_baseline_norm"
          dijkstra_first_mismatch_llm_norm="$dijkstra_llm_norm"
        fi
      fi
    fi
    if [ "${dijkstra_gemini_total:-0}" -eq 0 ]; then
      dijkstra_baseline_norm="$(normalize_dijkstra_answer <<<"${dijkstra_baseline_out:-}")"
      dijkstra_gemini_norm="$(normalize_dijkstra_answer <<<"${dijkstra_gemini_out:-}")"
      if [ -n "$dijkstra_baseline_norm" ] || [ -n "$dijkstra_gemini_norm" ]; then
        dijkstra_gemini_total=1
        if [ -n "$dijkstra_baseline_norm" ] && [ "$dijkstra_baseline_norm" = "$dijkstra_gemini_norm" ]; then
          dijkstra_gemini_match=1
          dijkstra_gemini_mismatch=0
        else
          dijkstra_gemini_match=0
          dijkstra_gemini_mismatch=1
          dijkstra_first_gemini_mismatch_baseline="${dijkstra_baseline_out:-}"
          dijkstra_first_gemini_mismatch_gemini="${dijkstra_gemini_out:-}"
          dijkstra_first_gemini_mismatch_baseline_norm="$dijkstra_baseline_norm"
          dijkstra_first_gemini_mismatch_gemini_norm="$dijkstra_gemini_norm"
        fi
      fi
    fi
    if [ "${dijkstra_total:-0}" -gt 0 ]; then
      {
        echo "[Dijkstra ChatGPT Comparison]"
        echo "Matches: ${dijkstra_match}/${dijkstra_total} (mismatches: ${dijkstra_mismatch})"
        if [ "${dijkstra_mismatch:-0}" -gt 0 ]; then
          if [ -n "${dijkstra_first_mismatch_baseline_norm:-}" ] || [ -n "${dijkstra_first_mismatch_llm_norm:-}" ]; then
            echo "Baseline (normalized): ${dijkstra_first_mismatch_baseline_norm:-<empty>}"
            echo "LLM (normalized): ${dijkstra_first_mismatch_llm_norm:-<empty>}"
          fi
        fi
        echo
      } >> outputs/result.txt
    fi
    if [ "${dijkstra_gemini_total:-0}" -gt 0 ]; then
      {
        echo "[Dijkstra Gemini Comparison]"
        echo "Matches: ${dijkstra_gemini_match}/${dijkstra_gemini_total} (mismatches: ${dijkstra_gemini_mismatch})"
        if [ "${dijkstra_gemini_mismatch:-0}" -gt 0 ]; then
          if [ -n "${dijkstra_first_gemini_mismatch_baseline_norm:-}" ] || [ -n "${dijkstra_first_gemini_mismatch_gemini_norm:-}" ]; then
            echo "Baseline (normalized): ${dijkstra_first_gemini_mismatch_baseline_norm:-<empty>}"
            echo "Gemini (normalized): ${dijkstra_first_gemini_mismatch_gemini_norm:-<empty>}"
          fi
        fi
        echo
      } >> outputs/result.txt
    fi
    if [ -n "${dijkstra_baseline_ms_runs:-}" ] || [ -n "${dijkstra_llm_ms_runs:-}" ] || [ -n "${dijkstra_gemini_ms_runs:-}" ]; then
      SOLVER_TIME_MS_TOTAL="$(sum_ms_runs $dijkstra_baseline_ms_runs $dijkstra_llm_ms_runs $dijkstra_gemini_ms_runs)"
    fi
    ;;
  glasgow)
    glasgow_first_out=""
    glasgow_first_ms_runs=""
    glasgow_first_rss_runs=""
    glasgow_all_out=""
    glasgow_all_ms_runs=""
    glasgow_all_rss_runs=""

    glasgow_gemini_first_out=""
    glasgow_gemini_first_ms_runs=""
    glasgow_gemini_first_rss_runs=""
    glasgow_gemini_all_out=""
    glasgow_gemini_all_ms_runs=""
    glasgow_gemini_all_rss_runs=""

    glasgow_chatgpt_first_out=""
    glasgow_chatgpt_first_ms_runs=""
    glasgow_chatgpt_first_rss_runs=""
    glasgow_chatgpt_all_out=""
    glasgow_chatgpt_all_ms_runs=""
    glasgow_chatgpt_all_rss_runs=""

    # Phase 1: setup + warmup (web UI fills the progress bar once here)
    PROGRESS_STAGE="setup"
    progress_set_phase "Setting up Testing Environment"
    if [ "${WARMUP_REQUESTED:-0}" -gt 0 ]; then
      if [ "$INPUT_MODE" = "generate" ]; then
        out=""
        dur=""
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          if ! generate_graphs_for_run "glasgow_warmup" "w${i}"; then
            EXIT_CODE=1
            break
          fi
          if ! run_capture out dur ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --format lad "${FILES[0]}" "${FILES[1]}"; then
            echo "[Warmup] Glasgow first failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --count-solutions --format lad "${FILES[0]}" "${FILES[1]}"; then
            echo "[Warmup] Glasgow all failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./src/glasgow_chatgpt "${FILES[0]}" "${FILES[1]}"; then
            echo "[Warmup] Glasgow ChatGPT run failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          progress_setup_tick
          if ! run_capture out dur ./src/glasgow_gemini "${FILES[0]}" "${FILES[1]}"; then
            echo "[Warmup] Glasgow Gemini run failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          progress_setup_tick
        done
      else
        if ! warmup_only "Glasgow first" ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --format lad "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Glasgow all" ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --count-solutions --format lad "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Glasgow ChatGPT" ./src/glasgow_chatgpt "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
        fi
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          progress_setup_tick
        done
        if ! warmup_only "Glasgow Gemini" ./src/glasgow_gemini "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
        fi
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          progress_setup_tick
        done
      fi
    else
      progress_setup_tick
    fi
    PROGRESS_SETUP_DONE="$PROGRESS_SETUP_TOTAL"
    progress_update_check_run "in_progress" || true

    # Phase 2: measured iterations (web UI resets the bar and fills again here)
    PROGRESS_STAGE="tests"
    PROGRESS_PHASE=""
    PROGRESS_DONE_TICKS=0
    progress_update_check_run "in_progress" || true
    WARMUP=0

    progress_set_phase "Glasgow baseline"
    glasgow_success=0
    glasgow_fail=0
    glasgow_chatgpt_match=0
    glasgow_chatgpt_total=0
    glasgow_chatgpt_mismatch=0
    glasgow_gemini_match=0
    glasgow_gemini_total=0
    glasgow_gemini_mismatch=0

    first_times=()
    first_rsses=()
    all_times=()
    all_rsses=()
    chat_first_times=()
    chat_first_rsses=()
    chat_all_times=()
    chat_all_rsses=()
    gem_first_times=()
    gem_first_rsses=()
    gem_all_times=()
    gem_all_rsses=()
    out=""
    dur=""
    rss=""

    for ((i=1; i<=ITERATIONS; i++)); do
      if [ "$INPUT_MODE" = "generate" ]; then
        if ! generate_graphs_for_run "glasgow_iter" "$i"; then
          EXIT_CODE=1
          break
        fi
      fi

      baseline_ok=1
      progress_set_phase "Glasgow baseline"
      if ! run_capture_rss out dur rss ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --format lad "${FILES[0]}" "${FILES[1]}"; then
        EXIT_CODE=1
        echo "[Glasgow Subgraph Solver] first-solution run failed." >> outputs/result.txt
        baseline_ok=0
      else
        first_times+=("$dur")
        first_rsses+=("$rss")
        progress_tick
      fi
      if [ "$baseline_ok" -eq 1 ]; then
        if ! run_capture_rss out dur rss ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --count-solutions --format lad "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
          echo "[Glasgow Subgraph Solver] all-solutions run failed." >> outputs/result.txt
          baseline_ok=0
        else
          all_times+=("$dur")
          all_rsses+=("$rss")
          progress_tick
          baseline_count="$(extract_solution_count "$out")"
          if [ -z "${baseline_count:-}" ]; then
            echo "[Glasgow Subgraph Solver] could not parse solution count." >> outputs/result.txt
            baseline_ok=0
            EXIT_CODE=1
          fi
        fi
      fi

      if [ "$baseline_ok" -ne 1 ]; then
        glasgow_fail=$((glasgow_fail + 1))
        continue
      fi

      glasgow_success=$((glasgow_success + 1))

      progress_set_phase "Glasgow ChatGPT"
      glasgow_chatgpt_total=$((glasgow_chatgpt_total + 1))
      chat_ok=1
      chat_count=""
      if ! run_capture_rss out dur rss ./src/glasgow_chatgpt "${FILES[0]}" "${FILES[1]}"; then
        EXIT_CODE=1
        echo "[Glasgow ChatGPT] run failed." >> outputs/result.txt
        chat_ok=0
      else
        chat_first_times+=("$dur")
        chat_first_rsses+=("$rss")
        chat_all_times+=("$dur")
        chat_all_rsses+=("$rss")
        progress_tick
        progress_tick
        parsed="$(extract_count_time_ms <<< "$out")"
        if [ -n "${parsed:-}" ]; then
          read chat_count _ _ <<< "$parsed"
        else
          chat_ok=0
          echo "[Glasgow ChatGPT] could not parse solution count/time." >> outputs/result.txt
        fi
      fi
      if [ "$chat_ok" -eq 1 ] && [ -n "${chat_count:-}" ] && [ "$chat_count" = "$baseline_count" ]; then
        glasgow_chatgpt_match=$((glasgow_chatgpt_match + 1))
      else
        glasgow_chatgpt_mismatch=$((glasgow_chatgpt_mismatch + 1))
      fi

      progress_set_phase "Glasgow Gemini"
      glasgow_gemini_total=$((glasgow_gemini_total + 1))
      gem_ok=1
      gem_count=""
      if ! run_capture_rss out dur rss ./src/glasgow_gemini "${FILES[0]}" "${FILES[1]}"; then
        EXIT_CODE=1
        echo "[Glasgow Gemini] run failed." >> outputs/result.txt
        gem_ok=0
      else
        gem_first_times+=("$dur")
        gem_first_rsses+=("$rss")
        gem_all_times+=("$dur")
        gem_all_rsses+=("$rss")
        progress_tick
        progress_tick
        parsed="$(extract_count_time_ms <<< "$out")"
        if [ -n "${parsed:-}" ]; then
          read gem_count _ _ <<< "$parsed"
        else
          gem_ok=0
          echo "[Glasgow Gemini] could not parse solution count/time." >> outputs/result.txt
        fi
      fi
      if [ "$gem_ok" -eq 1 ] && [ -n "${gem_count:-}" ] && [ "$gem_count" = "$baseline_count" ]; then
        glasgow_gemini_match=$((glasgow_gemini_match + 1))
      else
        glasgow_gemini_mismatch=$((glasgow_gemini_mismatch + 1))
      fi
    done

    glasgow_first_ms_runs="${first_times[*]}"
    glasgow_first_rss_runs="${first_rsses[*]}"
    glasgow_all_ms_runs="${all_times[*]}"
    glasgow_all_rss_runs="${all_rsses[*]}"
    glasgow_chatgpt_first_ms_runs="${chat_first_times[*]}"
    glasgow_chatgpt_first_rss_runs="${chat_first_rsses[*]}"
    glasgow_chatgpt_all_ms_runs="${chat_all_times[*]}"
    glasgow_chatgpt_all_rss_runs="${chat_all_rsses[*]}"
    glasgow_gemini_first_ms_runs="${gem_first_times[*]}"
    glasgow_gemini_first_rss_runs="${gem_first_rsses[*]}"
    glasgow_gemini_all_ms_runs="${gem_all_times[*]}"
    glasgow_gemini_all_rss_runs="${gem_all_rsses[*]}"

    if [ -n "${glasgow_first_ms_runs:-}" ]; then
      read glasgow_first_ms_median glasgow_first_ms_mean glasgow_first_ms_stdev glasgow_first_ms_min glasgow_first_ms_max glasgow_first_ms_n <<< "$(calc_stats_ms $glasgow_first_ms_runs)"
      glasgow_first_ms="$glasgow_first_ms_median"
    fi
    if [ -n "${glasgow_all_ms_runs:-}" ]; then
      read glasgow_all_ms_median glasgow_all_ms_mean glasgow_all_ms_stdev glasgow_all_ms_min glasgow_all_ms_max glasgow_all_ms_n <<< "$(calc_stats_ms $glasgow_all_ms_runs)"
      glasgow_all_ms="$glasgow_all_ms_median"
    fi
    if [ -n "${glasgow_first_rss_runs:-}" ]; then
      read glasgow_first_rss_median glasgow_first_rss_mean glasgow_first_rss_stdev glasgow_first_rss_min glasgow_first_rss_max glasgow_first_rss_n <<< "$(calc_stats_kb $glasgow_first_rss_runs)"
      glasgow_first_rss_kb="$glasgow_first_rss_median"
    fi
    if [ -n "${glasgow_all_rss_runs:-}" ]; then
      read glasgow_all_rss_median glasgow_all_rss_mean glasgow_all_rss_stdev glasgow_all_rss_min glasgow_all_rss_max glasgow_all_rss_n <<< "$(calc_stats_kb $glasgow_all_rss_runs)"
      glasgow_all_rss_kb="$glasgow_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ] && [ "$ITERATIONS" -ge 1 ]; then
      glasgow_failure_suffix=""
      if [ "${glasgow_fail:-0}" -gt 0 ]; then
        glasgow_failure_suffix=", ${glasgow_fail} failed"
      fi
      {
        echo "[Glasgow Subgraph Solver]"
        echo "${glasgow_success} iterations ran successfully${glasgow_failure_suffix}"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${glasgow_first_ms_median:-}" ] && [ -n "${glasgow_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$glasgow_first_ms_median" "$glasgow_first_ms_mean" "$glasgow_first_ms_stdev" "$glasgow_first_ms_min" "$glasgow_first_ms_max" \
            "$glasgow_all_ms_median" "$glasgow_all_ms_mean" "$glasgow_all_ms_stdev" "$glasgow_all_ms_min" "$glasgow_all_ms_max"
        fi
        if [ -n "${glasgow_first_rss_median:-}" ] && [ -n "${glasgow_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$glasgow_first_rss_median" "$glasgow_first_rss_mean" "$glasgow_first_rss_stdev" "$glasgow_first_rss_min" "$glasgow_first_rss_max" \
            "$glasgow_all_rss_median" "$glasgow_all_rss_mean" "$glasgow_all_rss_stdev" "$glasgow_all_rss_min" "$glasgow_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${glasgow_chatgpt_first_ms_runs:-}" ]; then
      read glasgow_chatgpt_first_ms_median glasgow_chatgpt_first_ms_mean glasgow_chatgpt_first_ms_stdev glasgow_chatgpt_first_ms_min glasgow_chatgpt_first_ms_max glasgow_chatgpt_first_ms_n <<< "$(calc_stats_ms $glasgow_chatgpt_first_ms_runs)"
      glasgow_chatgpt_first_ms="$glasgow_chatgpt_first_ms_median"
    fi
    if [ -n "${glasgow_chatgpt_all_ms_runs:-}" ]; then
      read glasgow_chatgpt_all_ms_median glasgow_chatgpt_all_ms_mean glasgow_chatgpt_all_ms_stdev glasgow_chatgpt_all_ms_min glasgow_chatgpt_all_ms_max glasgow_chatgpt_all_ms_n <<< "$(calc_stats_ms $glasgow_chatgpt_all_ms_runs)"
      glasgow_chatgpt_all_ms="$glasgow_chatgpt_all_ms_median"
    fi
    if [ -n "${glasgow_chatgpt_first_rss_runs:-}" ]; then
      read glasgow_chatgpt_first_rss_median glasgow_chatgpt_first_rss_mean glasgow_chatgpt_first_rss_stdev glasgow_chatgpt_first_rss_min glasgow_chatgpt_first_rss_max glasgow_chatgpt_first_rss_n <<< "$(calc_stats_kb $glasgow_chatgpt_first_rss_runs)"
      glasgow_chatgpt_first_rss_kb="$glasgow_chatgpt_first_rss_median"
    fi
    if [ -n "${glasgow_chatgpt_all_rss_runs:-}" ]; then
      read glasgow_chatgpt_all_rss_median glasgow_chatgpt_all_rss_mean glasgow_chatgpt_all_rss_stdev glasgow_chatgpt_all_rss_min glasgow_chatgpt_all_rss_max glasgow_chatgpt_all_rss_n <<< "$(calc_stats_kb $glasgow_chatgpt_all_rss_runs)"
      glasgow_chatgpt_all_rss_kb="$glasgow_chatgpt_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ] && [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[Glasgow ChatGPT]"
        echo "Matches: ${glasgow_chatgpt_match}/${glasgow_chatgpt_total} (mismatches: ${glasgow_chatgpt_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${glasgow_chatgpt_first_ms_median:-}" ] && [ -n "${glasgow_chatgpt_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$glasgow_chatgpt_first_ms_median" "$glasgow_chatgpt_first_ms_mean" "$glasgow_chatgpt_first_ms_stdev" "$glasgow_chatgpt_first_ms_min" "$glasgow_chatgpt_first_ms_max" \
            "$glasgow_chatgpt_all_ms_median" "$glasgow_chatgpt_all_ms_mean" "$glasgow_chatgpt_all_ms_stdev" "$glasgow_chatgpt_all_ms_min" "$glasgow_chatgpt_all_ms_max"
        fi
        if [ -n "${glasgow_chatgpt_first_rss_median:-}" ] && [ -n "${glasgow_chatgpt_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$glasgow_chatgpt_first_rss_median" "$glasgow_chatgpt_first_rss_mean" "$glasgow_chatgpt_first_rss_stdev" "$glasgow_chatgpt_first_rss_min" "$glasgow_chatgpt_first_rss_max" \
            "$glasgow_chatgpt_all_rss_median" "$glasgow_chatgpt_all_rss_mean" "$glasgow_chatgpt_all_rss_stdev" "$glasgow_chatgpt_all_rss_min" "$glasgow_chatgpt_all_rss_max"
        fi
        if [ -n "${glasgow_first_ms_mean:-}" ] && [ -n "${glasgow_chatgpt_first_ms_mean:-}" ]; then
          t_test_line "runtime ms first baseline vs ChatGPT" \
            "$glasgow_first_ms_mean" "$glasgow_first_ms_stdev" "$glasgow_first_ms_n" \
            "$glasgow_chatgpt_first_ms_mean" "$glasgow_chatgpt_first_ms_stdev" "$glasgow_chatgpt_first_ms_n"
        fi
        if [ -n "${glasgow_all_ms_mean:-}" ] && [ -n "${glasgow_chatgpt_all_ms_mean:-}" ]; then
          t_test_line "runtime ms all baseline vs ChatGPT" \
            "$glasgow_all_ms_mean" "$glasgow_all_ms_stdev" "$glasgow_all_ms_n" \
            "$glasgow_chatgpt_all_ms_mean" "$glasgow_chatgpt_all_ms_stdev" "$glasgow_chatgpt_all_ms_n"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${glasgow_gemini_first_ms_runs:-}" ]; then
      read glasgow_gemini_first_ms_median glasgow_gemini_first_ms_mean glasgow_gemini_first_ms_stdev glasgow_gemini_first_ms_min glasgow_gemini_first_ms_max glasgow_gemini_first_ms_n <<< "$(calc_stats_ms $glasgow_gemini_first_ms_runs)"
      glasgow_gemini_first_ms="$glasgow_gemini_first_ms_median"
    fi
    if [ -n "${glasgow_gemini_all_ms_runs:-}" ]; then
      read glasgow_gemini_all_ms_median glasgow_gemini_all_ms_mean glasgow_gemini_all_ms_stdev glasgow_gemini_all_ms_min glasgow_gemini_all_ms_max glasgow_gemini_all_ms_n <<< "$(calc_stats_ms $glasgow_gemini_all_ms_runs)"
      glasgow_gemini_all_ms="$glasgow_gemini_all_ms_median"
    fi
    if [ -n "${glasgow_gemini_first_rss_runs:-}" ]; then
      read glasgow_gemini_first_rss_median glasgow_gemini_first_rss_mean glasgow_gemini_first_rss_stdev glasgow_gemini_first_rss_min glasgow_gemini_first_rss_max glasgow_gemini_first_rss_n <<< "$(calc_stats_kb $glasgow_gemini_first_rss_runs)"
      glasgow_gemini_first_rss_kb="$glasgow_gemini_first_rss_median"
    fi
    if [ -n "${glasgow_gemini_all_rss_runs:-}" ]; then
      read glasgow_gemini_all_rss_median glasgow_gemini_all_rss_mean glasgow_gemini_all_rss_stdev glasgow_gemini_all_rss_min glasgow_gemini_all_rss_max glasgow_gemini_all_rss_n <<< "$(calc_stats_kb $glasgow_gemini_all_rss_runs)"
      glasgow_gemini_all_rss_kb="$glasgow_gemini_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ] && [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[Glasgow Gemini]"
        echo "Matches: ${glasgow_gemini_match}/${glasgow_gemini_total} (mismatches: ${glasgow_gemini_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${glasgow_gemini_first_ms_median:-}" ] && [ -n "${glasgow_gemini_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$glasgow_gemini_first_ms_median" "$glasgow_gemini_first_ms_mean" "$glasgow_gemini_first_ms_stdev" "$glasgow_gemini_first_ms_min" "$glasgow_gemini_first_ms_max" \
            "$glasgow_gemini_all_ms_median" "$glasgow_gemini_all_ms_mean" "$glasgow_gemini_all_ms_stdev" "$glasgow_gemini_all_ms_min" "$glasgow_gemini_all_ms_max"
        fi
        if [ -n "${glasgow_gemini_first_rss_median:-}" ] && [ -n "${glasgow_gemini_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$glasgow_gemini_first_rss_median" "$glasgow_gemini_first_rss_mean" "$glasgow_gemini_first_rss_stdev" "$glasgow_gemini_first_rss_min" "$glasgow_gemini_first_rss_max" \
            "$glasgow_gemini_all_rss_median" "$glasgow_gemini_all_rss_mean" "$glasgow_gemini_all_rss_stdev" "$glasgow_gemini_all_rss_min" "$glasgow_gemini_all_rss_max"
        fi
        if [ -n "${glasgow_first_ms_mean:-}" ] && [ -n "${glasgow_gemini_first_ms_mean:-}" ]; then
          t_test_line "runtime ms first baseline vs Gemini" \
            "$glasgow_first_ms_mean" "$glasgow_first_ms_stdev" "$glasgow_first_ms_n" \
            "$glasgow_gemini_first_ms_mean" "$glasgow_gemini_first_ms_stdev" "$glasgow_gemini_first_ms_n"
        fi
        if [ -n "${glasgow_all_ms_mean:-}" ] && [ -n "${glasgow_gemini_all_ms_mean:-}" ]; then
          t_test_line "runtime ms all baseline vs Gemini" \
            "$glasgow_all_ms_mean" "$glasgow_all_ms_stdev" "$glasgow_all_ms_n" \
            "$glasgow_gemini_all_ms_mean" "$glasgow_gemini_all_ms_stdev" "$glasgow_gemini_all_ms_n"
        fi
        echo
      } >> outputs/result.txt
    fi
    if [ -n "${glasgow_first_ms_runs:-}" ] || [ -n "${glasgow_all_ms_runs:-}" ] || [ -n "${glasgow_gemini_first_ms_runs:-}" ] || [ -n "${glasgow_gemini_all_ms_runs:-}" ] || [ -n "${glasgow_chatgpt_first_ms_runs:-}" ] || [ -n "${glasgow_chatgpt_all_ms_runs:-}" ]; then
      SOLVER_TIME_MS_TOTAL="$(sum_ms_runs $glasgow_first_ms_runs $glasgow_all_ms_runs $glasgow_gemini_first_ms_runs $glasgow_gemini_all_ms_runs $glasgow_chatgpt_first_ms_runs $glasgow_chatgpt_all_ms_runs)"
    fi
    ;;
  vf3)
    vf3_base_first_out=""
    vf3_base_first_ms_runs=""
    vf3_base_first_rss_runs=""
    vf3_base_all_out=""
    vf3_base_all_ms_runs=""
    vf3_base_all_rss_runs=""

    vf3_first_out=""
    vf3_first_ms_runs=""
    vf3_first_rss_runs=""
    vf3_all_out=""
    vf3_all_ms_runs=""
    vf3_all_rss_runs=""

    chatvf3_first_out=""
    chatvf3_first_ms_runs=""
    chatvf3_first_rss_runs=""
    chatvf3_all_out=""
    chatvf3_all_ms_runs=""
    chatvf3_all_rss_runs=""

    # Phase 1: setup + warmup (web UI fills the progress bar once here)
    PROGRESS_STAGE="setup"
    progress_set_phase "Setting up Testing Environment"
    if [ "${WARMUP_REQUESTED:-0}" -gt 0 ]; then
      if [ "$INPUT_MODE" = "generate" ]; then
        out=""
        dur=""
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          if ! generate_graphs_for_run "vf3_warmup" "w${i}"; then
            EXIT_CODE=1
            break
          fi
          if ! run_capture out dur ./baselines/vf3lib/bin/vf3 -u -r 0 "${FILES[0]}" "${FILES[1]}"; then
            echo "[Warmup] VF3 baseline all failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./src/chatvf3 "${FILES[0]}" "${FILES[1]}"; then
            echo "[Warmup] VF3 ChatGPT all failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./src/vf3 "${FILES[0]}" "${FILES[1]}"; then
            echo "[Warmup] VF3 Gemini all failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
        done
      else
        if ! warmup_only "VF3 baseline all" ./baselines/vf3lib/bin/vf3 -u -r 0 "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "VF3 ChatGPT all" ./src/chatvf3 "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "VF3 Gemini all" ./src/vf3 "${FILES[0]}" "${FILES[1]}"; then
          EXIT_CODE=1
        fi
      fi
    else
      progress_setup_tick
    fi
    PROGRESS_SETUP_DONE="$PROGRESS_SETUP_TOTAL"
    progress_update_check_run "in_progress" || true

    # Phase 2: measured iterations (web UI resets the bar and fills again here)
    PROGRESS_STAGE="tests"
    PROGRESS_PHASE=""
    PROGRESS_DONE_TICKS=0
    progress_update_check_run "in_progress" || true
    WARMUP=0

    progress_set_phase "VF3 baseline"
    vf3_success=0
    vf3_fail=0
    vf3_chatgpt_match=0
    vf3_chatgpt_total=0
    vf3_chatgpt_mismatch=0
    vf3_gemini_match=0
    vf3_gemini_total=0
    vf3_gemini_mismatch=0

    base_first_times=()
    base_first_rsses=()
    base_all_times=()
    base_all_rsses=()
    chat_first_times=()
    chat_first_rsses=()
    chat_all_times=()
    chat_all_rsses=()
    gem_first_times=()
    gem_first_rsses=()
    gem_all_times=()
    gem_all_rsses=()
    out=""
    dur=""
    rss=""

    for ((i=1; i<=ITERATIONS; i++)); do
      if [ "$INPUT_MODE" = "generate" ]; then
        if ! generate_graphs_for_run "vf3_iter" "$i"; then
          EXIT_CODE=1
          break
        fi
      fi

      baseline_ok=0
      progress_set_phase "VF3 baseline"
      max_attempts=1
      if [ "$INPUT_MODE" = "generate" ]; then
        max_attempts=3
      fi
      attempt=1
      while [ "$attempt" -le "$max_attempts" ]; do
        if [ "$attempt" -gt 1 ]; then
          if ! generate_graphs_for_run "vf3_iter_retry" "${i}_retry${attempt}"; then
            echo "[VF3 baseline] graph regeneration failed (retry)." >> outputs/result.txt
            break
          fi
        fi
        vf3_err_tmp=""
        if run_capture_rss_tmp out dur rss vf3_err_tmp ./baselines/vf3lib/bin/vf3 -u -r 0 "${FILES[0]}" "${FILES[1]}"; then
          baseline_ok=1
          if [ -n "${vf3_err_tmp:-}" ] && [ -f "$vf3_err_tmp" ]; then
            rm -f "$vf3_err_tmp"
          fi
          break
        fi
        if [ "$attempt" -eq 1 ] && [ "$max_attempts" -gt 1 ]; then
          echo "[VF3 baseline] run failed; regenerating graph and retrying." >> outputs/result.txt
        elif [ "$attempt" -lt "$max_attempts" ]; then
          echo "[VF3 baseline] run failed (retry); regenerating graph and retrying." >> outputs/result.txt
        else
          echo "[VF3 baseline] run failed (retry)." >> outputs/result.txt
        fi
        if [ -n "${vf3_err_tmp:-}" ] && [ -s "$vf3_err_tmp" ]; then
          if [ "$attempt" -gt 1 ]; then
            echo "[VF3 baseline] stderr (retry $attempt):" >> outputs/result.txt
          else
            echo "[VF3 baseline] stderr:" >> outputs/result.txt
          fi
          head -n 5 "$vf3_err_tmp" >> outputs/result.txt
        fi
        if [ -n "${vf3_err_tmp:-}" ] && [ -f "$vf3_err_tmp" ]; then
          rm -f "$vf3_err_tmp"
        fi
        attempt=$((attempt + 1))
      done
      if [ "$baseline_ok" -ne 1 ]; then
        EXIT_CODE=1
      fi
      if [ "$baseline_ok" -eq 1 ]; then
        read baseline_count base_first_ms base_all_ms <<< "$(extract_solution_times_ms "$out")"
        if [ -z "${baseline_count:-}" ] || [ -z "${base_first_ms:-}" ] || [ -z "${base_all_ms:-}" ]; then
          echo "[VF3 baseline] could not parse solution timings." >> outputs/result.txt
          baseline_ok=0
          EXIT_CODE=1
        else
          base_first_times+=("$base_first_ms")
          base_all_times+=("$base_all_ms")
          base_first_rsses+=("$rss")
          base_all_rsses+=("$rss")
          progress_tick
        fi
      fi

      if [ "$baseline_ok" -ne 1 ]; then
        vf3_fail=$((vf3_fail + 1))
        continue
      fi

      vf3_success=$((vf3_success + 1))

      progress_set_phase "VF3 ChatGPT"
      vf3_chatgpt_total=$((vf3_chatgpt_total + 1))
      chat_ok=1
      chat_count=""
      if ! run_capture_rss out dur rss ./src/chatvf3 "${FILES[0]}" "${FILES[1]}"; then
        EXIT_CODE=1
        echo "[VF3 ChatGPT] all-solutions run failed." >> outputs/result.txt
        chat_ok=0
      else
        read chat_count chat_first_ms chat_all_ms <<< "$(extract_solution_times_ms "$out")"
        if [ -z "${chat_count:-}" ] || [ -z "${chat_first_ms:-}" ] || [ -z "${chat_all_ms:-}" ]; then
          EXIT_CODE=1
          echo "[VF3 ChatGPT] could not parse solution timings." >> outputs/result.txt
          chat_ok=0
        else
          chat_first_times+=("$chat_first_ms")
          chat_all_times+=("$chat_all_ms")
          chat_first_rsses+=("$rss")
          chat_all_rsses+=("$rss")
          progress_tick
        fi
      fi
      if [ "$chat_ok" -eq 1 ] && [ -n "${chat_count:-}" ] && [ "$chat_count" = "$baseline_count" ]; then
        vf3_chatgpt_match=$((vf3_chatgpt_match + 1))
      else
        vf3_chatgpt_mismatch=$((vf3_chatgpt_mismatch + 1))
      fi

      progress_set_phase "VF3 Gemini"
      vf3_gemini_total=$((vf3_gemini_total + 1))
      gem_ok=1
      gem_count=""
      if ! run_capture_rss out dur rss ./src/vf3 "${FILES[0]}" "${FILES[1]}"; then
        EXIT_CODE=1
        echo "[VF3 Gemini] all-solutions run failed." >> outputs/result.txt
        gem_ok=0
      else
        read gem_count gem_first_ms gem_all_ms <<< "$(extract_solution_times_ms "$out")"
        if [ -z "${gem_count:-}" ] || [ -z "${gem_first_ms:-}" ] || [ -z "${gem_all_ms:-}" ]; then
          EXIT_CODE=1
          echo "[VF3 Gemini] could not parse solution timings." >> outputs/result.txt
          gem_ok=0
        else
          gem_first_times+=("$gem_first_ms")
          gem_all_times+=("$gem_all_ms")
          gem_first_rsses+=("$rss")
          gem_all_rsses+=("$rss")
          progress_tick
        fi
      fi
      if [ "$gem_ok" -eq 1 ] && [ -n "${gem_count:-}" ] && [ "$gem_count" = "$baseline_count" ]; then
        vf3_gemini_match=$((vf3_gemini_match + 1))
      else
        vf3_gemini_mismatch=$((vf3_gemini_mismatch + 1))
      fi
    done

    vf3_base_first_ms_runs="${base_first_times[*]}"
    vf3_base_first_rss_runs="${base_first_rsses[*]}"
    vf3_base_all_ms_runs="${base_all_times[*]}"
    vf3_base_all_rss_runs="${base_all_rsses[*]}"
    chatvf3_first_ms_runs="${chat_first_times[*]}"
    chatvf3_first_rss_runs="${chat_first_rsses[*]}"
    chatvf3_all_ms_runs="${chat_all_times[*]}"
    chatvf3_all_rss_runs="${chat_all_rsses[*]}"
    vf3_first_ms_runs="${gem_first_times[*]}"
    vf3_first_rss_runs="${gem_first_rsses[*]}"
    vf3_all_ms_runs="${gem_all_times[*]}"
    vf3_all_rss_runs="${gem_all_rsses[*]}"

    if [ -n "${vf3_base_first_ms_runs:-}" ]; then
      read vf3_base_first_ms_median vf3_base_first_ms_mean vf3_base_first_ms_stdev vf3_base_first_ms_min vf3_base_first_ms_max vf3_base_first_ms_n <<< "$(calc_stats_ms $vf3_base_first_ms_runs)"
      vf3_base_first_ms="$vf3_base_first_ms_median"
    fi
    if [ -n "${vf3_base_all_ms_runs:-}" ]; then
      read vf3_base_all_ms_median vf3_base_all_ms_mean vf3_base_all_ms_stdev vf3_base_all_ms_min vf3_base_all_ms_max vf3_base_all_ms_n <<< "$(calc_stats_ms $vf3_base_all_ms_runs)"
      vf3_base_all_ms="$vf3_base_all_ms_median"
    fi
    if [ -n "${vf3_base_first_rss_runs:-}" ]; then
      read vf3_base_first_rss_median vf3_base_first_rss_mean vf3_base_first_rss_stdev vf3_base_first_rss_min vf3_base_first_rss_max vf3_base_first_rss_n <<< "$(calc_stats_kb $vf3_base_first_rss_runs)"
      vf3_base_first_rss_kb="$vf3_base_first_rss_median"
    fi
    if [ -n "${vf3_base_all_rss_runs:-}" ]; then
      read vf3_base_all_rss_median vf3_base_all_rss_mean vf3_base_all_rss_stdev vf3_base_all_rss_min vf3_base_all_rss_max vf3_base_all_rss_n <<< "$(calc_stats_kb $vf3_base_all_rss_runs)"
      vf3_base_all_rss_kb="$vf3_base_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ] && [ "$ITERATIONS" -ge 1 ]; then
      vf3_failure_suffix=""
      if [ "${vf3_fail:-0}" -gt 0 ]; then
        vf3_failure_suffix=", ${vf3_fail} failed"
      fi
      {
        echo "[VF3 baseline]"
        echo "${vf3_success} iterations ran successfully${vf3_failure_suffix}"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${vf3_base_first_ms_median:-}" ] && [ -n "${vf3_base_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$vf3_base_first_ms_median" "$vf3_base_first_ms_mean" "$vf3_base_first_ms_stdev" "$vf3_base_first_ms_min" "$vf3_base_first_ms_max" \
            "$vf3_base_all_ms_median" "$vf3_base_all_ms_mean" "$vf3_base_all_ms_stdev" "$vf3_base_all_ms_min" "$vf3_base_all_ms_max"
        fi
        if [ -n "${vf3_base_first_rss_median:-}" ] && [ -n "${vf3_base_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$vf3_base_first_rss_median" "$vf3_base_first_rss_mean" "$vf3_base_first_rss_stdev" "$vf3_base_first_rss_min" "$vf3_base_first_rss_max" \
            "$vf3_base_all_rss_median" "$vf3_base_all_rss_mean" "$vf3_base_all_rss_stdev" "$vf3_base_all_rss_min" "$vf3_base_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${chatvf3_first_ms_runs:-}" ]; then
      read chatvf3_first_ms_median chatvf3_first_ms_mean chatvf3_first_ms_stdev chatvf3_first_ms_min chatvf3_first_ms_max chatvf3_first_ms_n <<< "$(calc_stats_ms $chatvf3_first_ms_runs)"
      chatvf3_first_ms="$chatvf3_first_ms_median"
    fi
    if [ -n "${chatvf3_all_ms_runs:-}" ]; then
      read chatvf3_all_ms_median chatvf3_all_ms_mean chatvf3_all_ms_stdev chatvf3_all_ms_min chatvf3_all_ms_max chatvf3_all_ms_n <<< "$(calc_stats_ms $chatvf3_all_ms_runs)"
      chatvf3_all_ms="$chatvf3_all_ms_median"
    fi
    if [ -n "${chatvf3_first_rss_runs:-}" ]; then
      read chatvf3_first_rss_median chatvf3_first_rss_mean chatvf3_first_rss_stdev chatvf3_first_rss_min chatvf3_first_rss_max chatvf3_first_rss_n <<< "$(calc_stats_kb $chatvf3_first_rss_runs)"
      chatvf3_first_rss_kb="$chatvf3_first_rss_median"
    fi
    if [ -n "${chatvf3_all_rss_runs:-}" ]; then
      read chatvf3_all_rss_median chatvf3_all_rss_mean chatvf3_all_rss_stdev chatvf3_all_rss_min chatvf3_all_rss_max chatvf3_all_rss_n <<< "$(calc_stats_kb $chatvf3_all_rss_runs)"
      chatvf3_all_rss_kb="$chatvf3_all_rss_median"
    fi
    if [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[VF3 ChatGPT]"
        echo "Matches: ${vf3_chatgpt_match}/${vf3_chatgpt_total} (mismatches: ${vf3_chatgpt_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${chatvf3_first_ms_median:-}" ] && [ -n "${chatvf3_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$chatvf3_first_ms_median" "$chatvf3_first_ms_mean" "$chatvf3_first_ms_stdev" "$chatvf3_first_ms_min" "$chatvf3_first_ms_max" \
            "$chatvf3_all_ms_median" "$chatvf3_all_ms_mean" "$chatvf3_all_ms_stdev" "$chatvf3_all_ms_min" "$chatvf3_all_ms_max"
        fi
        if [ -n "${chatvf3_first_rss_median:-}" ] && [ -n "${chatvf3_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$chatvf3_first_rss_median" "$chatvf3_first_rss_mean" "$chatvf3_first_rss_stdev" "$chatvf3_first_rss_min" "$chatvf3_first_rss_max" \
            "$chatvf3_all_rss_median" "$chatvf3_all_rss_mean" "$chatvf3_all_rss_stdev" "$chatvf3_all_rss_min" "$chatvf3_all_rss_max"
        fi
        if [ -n "${vf3_base_first_ms_mean:-}" ] && [ -n "${chatvf3_first_ms_mean:-}" ]; then
          t_test_line "runtime ms first baseline vs ChatGPT" \
            "$vf3_base_first_ms_mean" "$vf3_base_first_ms_stdev" "$vf3_base_first_ms_n" \
            "$chatvf3_first_ms_mean" "$chatvf3_first_ms_stdev" "$chatvf3_first_ms_n"
        fi
        if [ -n "${vf3_base_all_ms_mean:-}" ] && [ -n "${chatvf3_all_ms_mean:-}" ]; then
          t_test_line "runtime ms all baseline vs ChatGPT" \
            "$vf3_base_all_ms_mean" "$vf3_base_all_ms_stdev" "$vf3_base_all_ms_n" \
            "$chatvf3_all_ms_mean" "$chatvf3_all_ms_stdev" "$chatvf3_all_ms_n"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${vf3_first_ms_runs:-}" ]; then
      read vf3_first_ms_median vf3_first_ms_mean vf3_first_ms_stdev vf3_first_ms_min vf3_first_ms_max vf3_first_ms_n <<< "$(calc_stats_ms $vf3_first_ms_runs)"
      vf3_first_ms="$vf3_first_ms_median"
    fi
    if [ -n "${vf3_all_ms_runs:-}" ]; then
      read vf3_all_ms_median vf3_all_ms_mean vf3_all_ms_stdev vf3_all_ms_min vf3_all_ms_max vf3_all_ms_n <<< "$(calc_stats_ms $vf3_all_ms_runs)"
      vf3_all_ms="$vf3_all_ms_median"
    fi
    if [ -n "${vf3_first_rss_runs:-}" ]; then
      read vf3_first_rss_median vf3_first_rss_mean vf3_first_rss_stdev vf3_first_rss_min vf3_first_rss_max vf3_first_rss_n <<< "$(calc_stats_kb $vf3_first_rss_runs)"
      vf3_first_rss_kb="$vf3_first_rss_median"
    fi
    if [ -n "${vf3_all_rss_runs:-}" ]; then
      read vf3_all_rss_median vf3_all_rss_mean vf3_all_rss_stdev vf3_all_rss_min vf3_all_rss_max vf3_all_rss_n <<< "$(calc_stats_kb $vf3_all_rss_runs)"
      vf3_all_rss_kb="$vf3_all_rss_median"
    fi
    if [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[VF3 Gemini]"
        echo "Matches: ${vf3_gemini_match}/${vf3_gemini_total} (mismatches: ${vf3_gemini_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${vf3_first_ms_median:-}" ] && [ -n "${vf3_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$vf3_first_ms_median" "$vf3_first_ms_mean" "$vf3_first_ms_stdev" "$vf3_first_ms_min" "$vf3_first_ms_max" \
            "$vf3_all_ms_median" "$vf3_all_ms_mean" "$vf3_all_ms_stdev" "$vf3_all_ms_min" "$vf3_all_ms_max"
        fi
        if [ -n "${vf3_first_rss_median:-}" ] && [ -n "${vf3_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$vf3_first_rss_median" "$vf3_first_rss_mean" "$vf3_first_rss_stdev" "$vf3_first_rss_min" "$vf3_first_rss_max" \
            "$vf3_all_rss_median" "$vf3_all_rss_mean" "$vf3_all_rss_stdev" "$vf3_all_rss_min" "$vf3_all_rss_max"
        fi
        if [ -n "${vf3_base_first_ms_mean:-}" ] && [ -n "${vf3_first_ms_mean:-}" ]; then
          t_test_line "runtime ms first baseline vs Gemini" \
            "$vf3_base_first_ms_mean" "$vf3_base_first_ms_stdev" "$vf3_base_first_ms_n" \
            "$vf3_first_ms_mean" "$vf3_first_ms_stdev" "$vf3_first_ms_n"
        fi
        if [ -n "${vf3_base_all_ms_mean:-}" ] && [ -n "${vf3_all_ms_mean:-}" ]; then
          t_test_line "runtime ms all baseline vs Gemini" \
            "$vf3_base_all_ms_mean" "$vf3_base_all_ms_stdev" "$vf3_base_all_ms_n" \
            "$vf3_all_ms_mean" "$vf3_all_ms_stdev" "$vf3_all_ms_n"
        fi
        echo
      } >> outputs/result.txt
    fi
    if [ -n "${vf3_base_all_ms_runs:-}" ] || [ -n "${vf3_all_ms_runs:-}" ] || [ -n "${chatvf3_all_ms_runs:-}" ]; then
      SOLVER_TIME_MS_TOTAL="$(sum_ms_runs $vf3_base_all_ms_runs $vf3_all_ms_runs $chatvf3_all_ms_runs)"
    fi
    ;;
  subgraph)
    vf3_base_first_out=""
    vf3_base_first_ms_runs=""
    vf3_base_first_rss_runs=""
    vf3_base_all_out=""
    vf3_base_all_ms_runs=""
    vf3_base_all_rss_runs=""

    vf3_first_out=""
    vf3_first_ms_runs=""
    vf3_first_rss_runs=""
    vf3_all_out=""
    vf3_all_ms_runs=""
    vf3_all_rss_runs=""

    chatvf3_first_out=""
    chatvf3_first_ms_runs=""
    chatvf3_first_rss_runs=""
    chatvf3_all_out=""
    chatvf3_all_ms_runs=""
    chatvf3_all_rss_runs=""

    glasgow_first_out=""
    glasgow_first_ms_runs=""
    glasgow_first_rss_runs=""
    glasgow_all_out=""
    glasgow_all_ms_runs=""
    glasgow_all_rss_runs=""

    glasgow_gemini_first_out=""
    glasgow_gemini_first_ms_runs=""
    glasgow_gemini_first_rss_runs=""
    glasgow_gemini_all_out=""
    glasgow_gemini_all_ms_runs=""
    glasgow_gemini_all_rss_runs=""

    glasgow_chatgpt_first_out=""
    glasgow_chatgpt_first_ms_runs=""
    glasgow_chatgpt_first_rss_runs=""
    glasgow_chatgpt_all_out=""
    glasgow_chatgpt_all_ms_runs=""
    glasgow_chatgpt_all_rss_runs=""

    # Phase 1: setup + warmup (web UI fills the progress bar once here)
    PROGRESS_STAGE="setup"
    progress_set_phase "Setting up Testing Environment"
    if [ "${WARMUP_REQUESTED:-0}" -gt 0 ]; then
      if [ "$INPUT_MODE" = "generate" ]; then
        out=""
        dur=""
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          if ! generate_graphs_for_run "subgraph_warmup" "w${i}"; then
            EXIT_CODE=1
            break
          fi
          vf_pattern="${SUBGRAPH_VF_FILES[0]}"
          vf_target="${SUBGRAPH_VF_FILES[1]}"
          lad_pattern="${SUBGRAPH_LAD_FILES[0]}"
          lad_target="${SUBGRAPH_LAD_FILES[1]}"
          if ! run_capture out dur ./baselines/vf3lib/bin/vf3 -u -r 0 "$vf_pattern" "$vf_target"; then
            echo "[Warmup] Subgraph VF3 baseline failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./src/chatvf3 "$vf_pattern" "$vf_target"; then
            echo "[Warmup] Subgraph VF3 ChatGPT failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./src/vf3 "$vf_pattern" "$vf_target"; then
            echo "[Warmup] Subgraph VF3 Gemini failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --format vertexlabelledlad "$lad_pattern" "$lad_target"; then
            echo "[Warmup] Subgraph Glasgow baseline first failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --count-solutions --format vertexlabelledlad "$lad_pattern" "$lad_target"; then
            echo "[Warmup] Subgraph Glasgow baseline all failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          if ! run_capture out dur ./src/glasgow_chatgpt "$lad_pattern" "$lad_target"; then
            echo "[Warmup] Subgraph Glasgow ChatGPT failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          progress_setup_tick
          if ! run_capture out dur ./src/glasgow_gemini "$lad_pattern" "$lad_target"; then
            echo "[Warmup] Subgraph Glasgow Gemini failed." >> outputs/result.txt
            EXIT_CODE=1
            break
          fi
          progress_setup_tick
          progress_setup_tick
        done
      else
        vf_pattern="${SUBGRAPH_VF_FILES[0]}"
        vf_target="${SUBGRAPH_VF_FILES[1]}"
        lad_pattern="${SUBGRAPH_LAD_FILES[0]}"
        lad_target="${SUBGRAPH_LAD_FILES[1]}"
        if ! warmup_only "Subgraph VF3 baseline" ./baselines/vf3lib/bin/vf3 -u -r 0 "$vf_pattern" "$vf_target"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Subgraph VF3 ChatGPT" ./src/chatvf3 "$vf_pattern" "$vf_target"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Subgraph VF3 Gemini" ./src/vf3 "$vf_pattern" "$vf_target"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Subgraph Glasgow baseline first" ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --format vertexlabelledlad "$lad_pattern" "$lad_target"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Subgraph Glasgow baseline all" ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --count-solutions --format vertexlabelledlad "$lad_pattern" "$lad_target"; then
          EXIT_CODE=1
        fi
        if ! warmup_only "Subgraph Glasgow ChatGPT" ./src/glasgow_chatgpt "$lad_pattern" "$lad_target"; then
          EXIT_CODE=1
        fi
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          progress_setup_tick
        done
        if ! warmup_only "Subgraph Glasgow Gemini" ./src/glasgow_gemini "$lad_pattern" "$lad_target"; then
          EXIT_CODE=1
        fi
        for ((i=1; i<=WARMUP_REQUESTED; i++)); do
          progress_setup_tick
        done
      fi
    else
      progress_setup_tick
    fi
    PROGRESS_SETUP_DONE="$PROGRESS_SETUP_TOTAL"
    progress_update_check_run "in_progress" || true

    # Phase 2: measured iterations (web UI resets the bar and fills again here)
    PROGRESS_STAGE="tests"
    PROGRESS_PHASE=""
    PROGRESS_DONE_TICKS=0
    progress_update_check_run "in_progress" || true
    WARMUP=0

    vf3_success=0
    vf3_fail=0
    vf3_chatgpt_match=0
    vf3_chatgpt_total=0
    vf3_chatgpt_mismatch=0
    vf3_gemini_match=0
    vf3_gemini_total=0
    vf3_gemini_mismatch=0

    glasgow_success=0
    glasgow_fail=0
    glasgow_chatgpt_match=0
    glasgow_chatgpt_total=0
    glasgow_chatgpt_mismatch=0
    glasgow_gemini_match=0
    glasgow_gemini_total=0
    glasgow_gemini_mismatch=0
    glasgow_baseline_match=0
    glasgow_baseline_total=0
    glasgow_baseline_mismatch=0

    base_first_times=()
    base_first_rsses=()
    base_all_times=()
    base_all_rsses=()
    chat_first_times=()
    chat_first_rsses=()
    chat_all_times=()
    chat_all_rsses=()
    gem_first_times=()
    gem_first_rsses=()
    gem_all_times=()
    gem_all_rsses=()

    g_first_times=()
    g_first_rsses=()
    g_all_times=()
    g_all_rsses=()
    g_chat_first_times=()
    g_chat_first_rsses=()
    g_chat_all_times=()
    g_chat_all_rsses=()
    g_gem_first_times=()
    g_gem_first_rsses=()
    g_gem_all_times=()
    g_gem_all_rsses=()

    out=""
    dur=""
    rss=""

    for ((i=1; i<=ITERATIONS; i++)); do
      if [ "$INPUT_MODE" = "generate" ]; then
        if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ]; then
          if ! generate_graphs_for_run "subgraph_iter" "$i"; then
            EXIT_CODE=1
            break
          fi
        fi
      fi
      if [ "${SUBGRAPH_PHASE:-}" = "glasgow" ]; then
        lad_pattern="$(python -c "import sys; from pathlib import Path; iter_idx=sys.argv[1]; path=Path('outputs/subgraph_lad_files.csv'); lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []; matches=[p for p in ([s.strip() for s in line.split(',')] for line in lines) if len(p)>=3 and p[0]==str(iter_idx)]; print(matches[0][1] if matches else '')" "$i" 2>/dev/null)"
        lad_target="$(python -c "import sys; from pathlib import Path; iter_idx=sys.argv[1]; path=Path('outputs/subgraph_lad_files.csv'); lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []; matches=[p for p in ([s.strip() for s in line.split(',')] for line in lines) if len(p)>=3 and p[0]==str(iter_idx)]; print(matches[0][2] if matches else '')" "$i" 2>/dev/null)"
      else
        vf_pattern="${SUBGRAPH_VF_FILES[0]}"
        vf_target="${SUBGRAPH_VF_FILES[1]}"
        lad_pattern="${SUBGRAPH_LAD_FILES[0]}"
        lad_target="${SUBGRAPH_LAD_FILES[1]}"
        if [ -n "${lad_pattern:-}" ] && [ -n "${lad_target:-}" ]; then
          echo "${i},${lad_pattern},${lad_target}" >> outputs/subgraph_lad_files.csv
        fi
      fi

      if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ]; then
        baseline_ok=1
        progress_set_phase "Subgraph VF3 baseline"
        if ! run_capture_rss out dur rss ./baselines/vf3lib/bin/vf3 -u -r 0 "$vf_pattern" "$vf_target"; then
        EXIT_CODE=1
        echo "[Subgraph VF3 baseline] run failed." >> outputs/result.txt
        baseline_ok=0
        else
          read baseline_count base_first_ms base_all_ms <<< "$(extract_solution_times_ms "$out")"
          if [ -z "${baseline_count:-}" ] || [ -z "${base_first_ms:-}" ] || [ -z "${base_all_ms:-}" ]; then
            echo "[Subgraph VF3 baseline] could not parse solution timings." >> outputs/result.txt
            baseline_ok=0
            EXIT_CODE=1
          else
            base_first_times+=("$base_first_ms")
            base_all_times+=("$base_all_ms")
            base_first_rsses+=("$rss")
            base_all_rsses+=("$rss")
            progress_tick
          fi
        fi

        if [ "$baseline_ok" -ne 1 ]; then
          vf3_fail=$((vf3_fail + 1))
          continue
        fi

        vf3_success=$((vf3_success + 1))
        echo "${i},${baseline_count}" >> outputs/subgraph_baseline_counts.csv

        progress_set_phase "Subgraph VF3 ChatGPT"
        vf3_chatgpt_total=$((vf3_chatgpt_total + 1))
        chat_ok=1
        chat_count=""
        if ! run_capture_rss out dur rss ./src/chatvf3 "$vf_pattern" "$vf_target"; then
          EXIT_CODE=1
          echo "[Subgraph VF3 ChatGPT] all-solutions run failed." >> outputs/result.txt
          chat_ok=0
        else
          read chat_count chat_first_ms chat_all_ms <<< "$(extract_solution_times_ms "$out")"
          if [ -z "${chat_count:-}" ] || [ -z "${chat_first_ms:-}" ] || [ -z "${chat_all_ms:-}" ]; then
            EXIT_CODE=1
            echo "[Subgraph VF3 ChatGPT] could not parse solution timings." >> outputs/result.txt
            chat_ok=0
          else
            chat_first_times+=("$chat_first_ms")
            chat_all_times+=("$chat_all_ms")
            chat_first_rsses+=("$rss")
            chat_all_rsses+=("$rss")
            progress_tick
          fi
        fi
        if [ "$chat_ok" -eq 1 ] && [ -n "${chat_count:-}" ] && [ "$chat_count" = "$baseline_count" ]; then
          vf3_chatgpt_match=$((vf3_chatgpt_match + 1))
        else
          vf3_chatgpt_mismatch=$((vf3_chatgpt_mismatch + 1))
        fi

        progress_set_phase "Subgraph VF3 Gemini"
        vf3_gemini_total=$((vf3_gemini_total + 1))
        gem_ok=1
        gem_count=""
        if ! run_capture_rss out dur rss ./src/vf3 "$vf_pattern" "$vf_target"; then
          EXIT_CODE=1
          echo "[Subgraph VF3 Gemini] all-solutions run failed." >> outputs/result.txt
          gem_ok=0
        else
          read gem_count gem_first_ms gem_all_ms <<< "$(extract_solution_times_ms "$out")"
          if [ -z "${gem_count:-}" ] || [ -z "${gem_first_ms:-}" ] || [ -z "${gem_all_ms:-}" ]; then
            EXIT_CODE=1
            echo "[Subgraph VF3 Gemini] could not parse solution timings." >> outputs/result.txt
            gem_ok=0
          else
            gem_first_times+=("$gem_first_ms")
            gem_all_times+=("$gem_all_ms")
            gem_first_rsses+=("$rss")
            gem_all_rsses+=("$rss")
            progress_tick
          fi
        fi
        if [ "$gem_ok" -eq 1 ] && [ -n "${gem_count:-}" ] && [ "$gem_count" = "$baseline_count" ]; then
          vf3_gemini_match=$((vf3_gemini_match + 1))
        else
          vf3_gemini_mismatch=$((vf3_gemini_mismatch + 1))
        fi

        if [ "${SUBGRAPH_PHASE:-}" = "vf3" ]; then
          continue
        fi
      fi
      progress_set_phase "Subgraph Glasgow baseline"
      glasgow_baseline_total=$((glasgow_baseline_total + 1))
      glasgow_ok=1
      if [ -z "${baseline_count:-}" ]; then
        baseline_count="$(python -c "import sys; from pathlib import Path; iter_idx=sys.argv[1]; path=Path('outputs/subgraph_baseline_counts.csv'); lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []; matches=[p for p in ([s.strip() for s in line.split(',')] for line in lines) if len(p)>=2 and p[0]==str(iter_idx)]; print(matches[0][1] if matches else '')" "$i" 2>/dev/null)"
      fi
      if ! run_capture_rss out dur rss ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --format vertexlabelledlad "$lad_pattern" "$lad_target"; then
        EXIT_CODE=1
        echo "[Subgraph Glasgow] first-solution run failed." >> outputs/result.txt
        glasgow_ok=0
      else
        g_first_times+=("$dur")
        g_first_rsses+=("$rss")
        progress_tick
      fi
      if [ "$glasgow_ok" -eq 1 ]; then
        if ! run_capture_rss out dur rss ./baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver --induced --count-solutions --format vertexlabelledlad "$lad_pattern" "$lad_target"; then
          EXIT_CODE=1
          echo "[Subgraph Glasgow] all-solutions run failed." >> outputs/result.txt
          glasgow_ok=0
        else
          g_all_times+=("$dur")
          g_all_rsses+=("$rss")
          progress_tick
          glasgow_count="$(extract_solution_count "$out")"
          if [ -z "${glasgow_count:-}" ]; then
            echo "[Subgraph Glasgow] could not parse solution count." >> outputs/result.txt
            glasgow_ok=0
            EXIT_CODE=1
          fi
        fi
      fi
      if [ "$glasgow_ok" -eq 1 ]; then
        glasgow_success=$((glasgow_success + 1))
          if [ -n "${glasgow_count:-}" ] && [ "$glasgow_count" = "$baseline_count" ]; then
            glasgow_baseline_match=$((glasgow_baseline_match + 1))
          else
            glasgow_baseline_mismatch=$((glasgow_baseline_mismatch + 1))
          fi
      else
        glasgow_fail=$((glasgow_fail + 1))
      fi

      progress_set_phase "Subgraph Glasgow ChatGPT"
      glasgow_chatgpt_total=$((glasgow_chatgpt_total + 1))
      chat_ok=1
      chat_count=""
      if ! run_capture_rss out dur rss ./src/glasgow_chatgpt "$lad_pattern" "$lad_target"; then
        EXIT_CODE=1
        echo "[Subgraph Glasgow ChatGPT] run failed." >> outputs/result.txt
        chat_ok=0
      else
        g_chat_first_times+=("$dur")
        g_chat_all_times+=("$dur")
        g_chat_first_rsses+=("$rss")
        g_chat_all_rsses+=("$rss")
        progress_tick
        progress_tick
        parsed="$(extract_count_time_ms <<< "$out")"
        if [ -n "${parsed:-}" ]; then
          read chat_count _ _ <<< "$parsed"
        else
          chat_count="0"
          echo "[Subgraph Glasgow ChatGPT] could not parse solution count/time; defaulting to 0." >> outputs/result.txt
        fi
      fi
      if [ "$chat_ok" -eq 1 ] && [ -n "${chat_count:-}" ] && [ "$chat_count" = "$baseline_count" ]; then
        glasgow_chatgpt_match=$((glasgow_chatgpt_match + 1))
      else
        glasgow_chatgpt_mismatch=$((glasgow_chatgpt_mismatch + 1))
      fi

      progress_set_phase "Subgraph Glasgow Gemini"
      glasgow_gemini_total=$((glasgow_gemini_total + 1))
      gem_ok=1
      gem_count=""
      if ! run_capture_rss out dur rss ./src/glasgow_gemini "$lad_pattern" "$lad_target"; then
        EXIT_CODE=1
        echo "[Subgraph Glasgow Gemini] run failed." >> outputs/result.txt
        gem_ok=0
      else
        g_gem_first_times+=("$dur")
        g_gem_all_times+=("$dur")
        g_gem_first_rsses+=("$rss")
        g_gem_all_rsses+=("$rss")
        progress_tick
        progress_tick
        parsed="$(extract_count_time_ms <<< "$out")"
        if [ -n "${parsed:-}" ]; then
          read gem_count _ _ <<< "$parsed"
        else
          gem_count="0"
          echo "[Subgraph Glasgow Gemini] could not parse solution count/time; defaulting to 0." >> outputs/result.txt
        fi
      fi
      if [ "$gem_ok" -eq 1 ] && [ -n "${gem_count:-}" ] && [ "$gem_count" = "$baseline_count" ]; then
        glasgow_gemini_match=$((glasgow_gemini_match + 1))
      else
        glasgow_gemini_mismatch=$((glasgow_gemini_mismatch + 1))
      fi
    done

    vf3_base_first_ms_runs="${base_first_times[*]}"
    vf3_base_first_rss_runs="${base_first_rsses[*]}"
    vf3_base_all_ms_runs="${base_all_times[*]}"
    vf3_base_all_rss_runs="${base_all_rsses[*]}"
    chatvf3_first_ms_runs="${chat_first_times[*]}"
    chatvf3_first_rss_runs="${chat_first_rsses[*]}"
    chatvf3_all_ms_runs="${chat_all_times[*]}"
    chatvf3_all_rss_runs="${chat_all_rsses[*]}"
    vf3_first_ms_runs="${gem_first_times[*]}"
    vf3_first_rss_runs="${gem_first_rsses[*]}"
    vf3_all_ms_runs="${gem_all_times[*]}"
    vf3_all_rss_runs="${gem_all_rsses[*]}"

    glasgow_first_ms_runs="${g_first_times[*]}"
    glasgow_first_rss_runs="${g_first_rsses[*]}"
    glasgow_all_ms_runs="${g_all_times[*]}"
    glasgow_all_rss_runs="${g_all_rsses[*]}"
    glasgow_chatgpt_first_ms_runs="${g_chat_first_times[*]}"
    glasgow_chatgpt_first_rss_runs="${g_chat_first_rsses[*]}"
    glasgow_chatgpt_all_ms_runs="${g_chat_all_times[*]}"
    glasgow_chatgpt_all_rss_runs="${g_chat_all_rsses[*]}"
    glasgow_gemini_first_ms_runs="${g_gem_first_times[*]}"
    glasgow_gemini_first_rss_runs="${g_gem_first_rsses[*]}"
    glasgow_gemini_all_ms_runs="${g_gem_all_times[*]}"
    glasgow_gemini_all_rss_runs="${g_gem_all_rsses[*]}"

    if [ -n "${vf3_base_first_ms_runs:-}" ]; then
      read vf3_base_first_ms_median vf3_base_first_ms_mean vf3_base_first_ms_stdev vf3_base_first_ms_min vf3_base_first_ms_max vf3_base_first_ms_n <<< "$(calc_stats_ms $vf3_base_first_ms_runs)"
      vf3_base_first_ms="$vf3_base_first_ms_median"
    fi
    if [ -n "${vf3_base_all_ms_runs:-}" ]; then
      read vf3_base_all_ms_median vf3_base_all_ms_mean vf3_base_all_ms_stdev vf3_base_all_ms_min vf3_base_all_ms_max vf3_base_all_ms_n <<< "$(calc_stats_ms $vf3_base_all_ms_runs)"
      vf3_base_all_ms="$vf3_base_all_ms_median"
    fi
    if [ -n "${vf3_base_first_rss_runs:-}" ]; then
      read vf3_base_first_rss_median vf3_base_first_rss_mean vf3_base_first_rss_stdev vf3_base_first_rss_min vf3_base_first_rss_max vf3_base_first_rss_n <<< "$(calc_stats_kb $vf3_base_first_rss_runs)"
      vf3_base_first_rss_kb="$vf3_base_first_rss_median"
    fi
    if [ -n "${vf3_base_all_rss_runs:-}" ]; then
      read vf3_base_all_rss_median vf3_base_all_rss_mean vf3_base_all_rss_stdev vf3_base_all_rss_min vf3_base_all_rss_max vf3_base_all_rss_n <<< "$(calc_stats_kb $vf3_base_all_rss_runs)"
      vf3_base_all_rss_kb="$vf3_base_all_rss_median"
    fi

    if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ] && [ "$ITERATIONS" -ge 1 ]; then
      vf3_failure_suffix=""
      if [ "${vf3_fail:-0}" -gt 0 ]; then
        vf3_failure_suffix=", ${vf3_fail} failed"
      fi
      {
        echo "[Subgraph VF3 baseline]"
        echo "${vf3_success} iterations ran successfully${vf3_failure_suffix}"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${vf3_base_first_ms_median:-}" ] && [ -n "${vf3_base_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$vf3_base_first_ms_median" "$vf3_base_first_ms_mean" "$vf3_base_first_ms_stdev" "$vf3_base_first_ms_min" "$vf3_base_first_ms_max" \
            "$vf3_base_all_ms_median" "$vf3_base_all_ms_mean" "$vf3_base_all_ms_stdev" "$vf3_base_all_ms_min" "$vf3_base_all_ms_max"
        fi
        if [ -n "${vf3_base_first_rss_median:-}" ] && [ -n "${vf3_base_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$vf3_base_first_rss_median" "$vf3_base_first_rss_mean" "$vf3_base_first_rss_stdev" "$vf3_base_first_rss_min" "$vf3_base_first_rss_max" \
            "$vf3_base_all_rss_median" "$vf3_base_all_rss_mean" "$vf3_base_all_rss_stdev" "$vf3_base_all_rss_min" "$vf3_base_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${chatvf3_first_ms_runs:-}" ]; then
      read chatvf3_first_ms_median chatvf3_first_ms_mean chatvf3_first_ms_stdev chatvf3_first_ms_min chatvf3_first_ms_max chatvf3_first_ms_n <<< "$(calc_stats_ms $chatvf3_first_ms_runs)"
      chatvf3_first_ms="$chatvf3_first_ms_median"
    fi
    if [ -n "${chatvf3_all_ms_runs:-}" ]; then
      read chatvf3_all_ms_median chatvf3_all_ms_mean chatvf3_all_ms_stdev chatvf3_all_ms_min chatvf3_all_ms_max chatvf3_all_ms_n <<< "$(calc_stats_ms $chatvf3_all_ms_runs)"
      chatvf3_all_ms="$chatvf3_all_ms_median"
    fi
    if [ -n "${chatvf3_first_rss_runs:-}" ]; then
      read chatvf3_first_rss_median chatvf3_first_rss_mean chatvf3_first_rss_stdev chatvf3_first_rss_min chatvf3_first_rss_max chatvf3_first_rss_n <<< "$(calc_stats_kb $chatvf3_first_rss_runs)"
      chatvf3_first_rss_kb="$chatvf3_first_rss_median"
    fi
    if [ -n "${chatvf3_all_rss_runs:-}" ]; then
      read chatvf3_all_rss_median chatvf3_all_rss_mean chatvf3_all_rss_stdev chatvf3_all_rss_min chatvf3_all_rss_max chatvf3_all_rss_n <<< "$(calc_stats_kb $chatvf3_all_rss_runs)"
      chatvf3_all_rss_kb="$chatvf3_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ] && [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[Subgraph VF3 ChatGPT]"
        echo "Matches: ${vf3_chatgpt_match}/${vf3_chatgpt_total} (mismatches: ${vf3_chatgpt_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${chatvf3_first_ms_median:-}" ] && [ -n "${chatvf3_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$chatvf3_first_ms_median" "$chatvf3_first_ms_mean" "$chatvf3_first_ms_stdev" "$chatvf3_first_ms_min" "$chatvf3_first_ms_max" \
            "$chatvf3_all_ms_median" "$chatvf3_all_ms_mean" "$chatvf3_all_ms_stdev" "$chatvf3_all_ms_min" "$chatvf3_all_ms_max"
        fi
        if [ -n "${chatvf3_first_rss_median:-}" ] && [ -n "${chatvf3_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$chatvf3_first_rss_median" "$chatvf3_first_rss_mean" "$chatvf3_first_rss_stdev" "$chatvf3_first_rss_min" "$chatvf3_first_rss_max" \
            "$chatvf3_all_rss_median" "$chatvf3_all_rss_mean" "$chatvf3_all_rss_stdev" "$chatvf3_all_rss_min" "$chatvf3_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${vf3_first_ms_runs:-}" ]; then
      read vf3_first_ms_median vf3_first_ms_mean vf3_first_ms_stdev vf3_first_ms_min vf3_first_ms_max vf3_first_ms_n <<< "$(calc_stats_ms $vf3_first_ms_runs)"
      vf3_first_ms="$vf3_first_ms_median"
    fi
    if [ -n "${vf3_all_ms_runs:-}" ]; then
      read vf3_all_ms_median vf3_all_ms_mean vf3_all_ms_stdev vf3_all_ms_min vf3_all_ms_max vf3_all_ms_n <<< "$(calc_stats_ms $vf3_all_ms_runs)"
      vf3_all_ms="$vf3_all_ms_median"
    fi
    if [ -n "${vf3_first_rss_runs:-}" ]; then
      read vf3_first_rss_median vf3_first_rss_mean vf3_first_rss_stdev vf3_first_rss_min vf3_first_rss_max vf3_first_rss_n <<< "$(calc_stats_kb $vf3_first_rss_runs)"
      vf3_first_rss_kb="$vf3_first_rss_median"
    fi
    if [ -n "${vf3_all_rss_runs:-}" ]; then
      read vf3_all_rss_median vf3_all_rss_mean vf3_all_rss_stdev vf3_all_rss_min vf3_all_rss_max vf3_all_rss_n <<< "$(calc_stats_kb $vf3_all_rss_runs)"
      vf3_all_rss_kb="$vf3_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "glasgow" ] && [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[Subgraph VF3 Gemini]"
        echo "Matches: ${vf3_gemini_match}/${vf3_gemini_total} (mismatches: ${vf3_gemini_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${vf3_first_ms_median:-}" ] && [ -n "${vf3_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$vf3_first_ms_median" "$vf3_first_ms_mean" "$vf3_first_ms_stdev" "$vf3_first_ms_min" "$vf3_first_ms_max" \
            "$vf3_all_ms_median" "$vf3_all_ms_mean" "$vf3_all_ms_stdev" "$vf3_all_ms_min" "$vf3_all_ms_max"
        fi
        if [ -n "${vf3_first_rss_median:-}" ] && [ -n "${vf3_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$vf3_first_rss_median" "$vf3_first_rss_mean" "$vf3_first_rss_stdev" "$vf3_first_rss_min" "$vf3_first_rss_max" \
            "$vf3_all_rss_median" "$vf3_all_rss_mean" "$vf3_all_rss_stdev" "$vf3_all_rss_min" "$vf3_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${glasgow_first_ms_runs:-}" ]; then
      read glasgow_first_ms_median glasgow_first_ms_mean glasgow_first_ms_stdev glasgow_first_ms_min glasgow_first_ms_max glasgow_first_ms_n <<< "$(calc_stats_ms $glasgow_first_ms_runs)"
      glasgow_first_ms="$glasgow_first_ms_median"
    fi
    if [ -n "${glasgow_all_ms_runs:-}" ]; then
      read glasgow_all_ms_median glasgow_all_ms_mean glasgow_all_ms_stdev glasgow_all_ms_min glasgow_all_ms_max glasgow_all_ms_n <<< "$(calc_stats_ms $glasgow_all_ms_runs)"
      glasgow_all_ms="$glasgow_all_ms_median"
    fi
    if [ -n "${glasgow_first_rss_runs:-}" ]; then
      read glasgow_first_rss_median glasgow_first_rss_mean glasgow_first_rss_stdev glasgow_first_rss_min glasgow_first_rss_max glasgow_first_rss_n <<< "$(calc_stats_kb $glasgow_first_rss_runs)"
      glasgow_first_rss_kb="$glasgow_first_rss_median"
    fi
    if [ -n "${glasgow_all_rss_runs:-}" ]; then
      read glasgow_all_rss_median glasgow_all_rss_mean glasgow_all_rss_stdev glasgow_all_rss_min glasgow_all_rss_max glasgow_all_rss_n <<< "$(calc_stats_kb $glasgow_all_rss_runs)"
      glasgow_all_rss_kb="$glasgow_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "vf3" ] && [ "$ITERATIONS" -ge 1 ]; then
      glasgow_failure_suffix=""
      if [ "${glasgow_fail:-0}" -gt 0 ]; then
        glasgow_failure_suffix=", ${glasgow_fail} failed"
      fi
      {
        echo "[Subgraph Glasgow baseline]"
        echo "${glasgow_success} iterations ran successfully${glasgow_failure_suffix}"
        echo "Matches: ${glasgow_baseline_match}/${glasgow_baseline_total} (mismatches: ${glasgow_baseline_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${glasgow_first_ms_median:-}" ] && [ -n "${glasgow_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$glasgow_first_ms_median" "$glasgow_first_ms_mean" "$glasgow_first_ms_stdev" "$glasgow_first_ms_min" "$glasgow_first_ms_max" \
            "$glasgow_all_ms_median" "$glasgow_all_ms_mean" "$glasgow_all_ms_stdev" "$glasgow_all_ms_min" "$glasgow_all_ms_max"
        fi
        if [ -n "${glasgow_first_rss_median:-}" ] && [ -n "${glasgow_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$glasgow_first_rss_median" "$glasgow_first_rss_mean" "$glasgow_first_rss_stdev" "$glasgow_first_rss_min" "$glasgow_first_rss_max" \
            "$glasgow_all_rss_median" "$glasgow_all_rss_mean" "$glasgow_all_rss_stdev" "$glasgow_all_rss_min" "$glasgow_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${glasgow_chatgpt_first_ms_runs:-}" ]; then
      read glasgow_chatgpt_first_ms_median glasgow_chatgpt_first_ms_mean glasgow_chatgpt_first_ms_stdev glasgow_chatgpt_first_ms_min glasgow_chatgpt_first_ms_max glasgow_chatgpt_first_ms_n <<< "$(calc_stats_ms $glasgow_chatgpt_first_ms_runs)"
      glasgow_chatgpt_first_ms="$glasgow_chatgpt_first_ms_median"
    fi
    if [ -n "${glasgow_chatgpt_all_ms_runs:-}" ]; then
      read glasgow_chatgpt_all_ms_median glasgow_chatgpt_all_ms_mean glasgow_chatgpt_all_ms_stdev glasgow_chatgpt_all_ms_min glasgow_chatgpt_all_ms_max glasgow_chatgpt_all_ms_n <<< "$(calc_stats_ms $glasgow_chatgpt_all_ms_runs)"
      glasgow_chatgpt_all_ms="$glasgow_chatgpt_all_ms_median"
    fi
    if [ -n "${glasgow_chatgpt_first_rss_runs:-}" ]; then
      read glasgow_chatgpt_first_rss_median glasgow_chatgpt_first_rss_mean glasgow_chatgpt_first_rss_stdev glasgow_chatgpt_first_rss_min glasgow_chatgpt_first_rss_max glasgow_chatgpt_first_rss_n <<< "$(calc_stats_kb $glasgow_chatgpt_first_rss_runs)"
      glasgow_chatgpt_first_rss_kb="$glasgow_chatgpt_first_rss_median"
    fi
    if [ -n "${glasgow_chatgpt_all_rss_runs:-}" ]; then
      read glasgow_chatgpt_all_rss_median glasgow_chatgpt_all_rss_mean glasgow_chatgpt_all_rss_stdev glasgow_chatgpt_all_rss_min glasgow_chatgpt_all_rss_max glasgow_chatgpt_all_rss_n <<< "$(calc_stats_kb $glasgow_chatgpt_all_rss_runs)"
      glasgow_chatgpt_all_rss_kb="$glasgow_chatgpt_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "vf3" ] && [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[Subgraph Glasgow ChatGPT]"
        echo "Matches: ${glasgow_chatgpt_match}/${glasgow_chatgpt_total} (mismatches: ${glasgow_chatgpt_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${glasgow_chatgpt_first_ms_median:-}" ] && [ -n "${glasgow_chatgpt_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$glasgow_chatgpt_first_ms_median" "$glasgow_chatgpt_first_ms_mean" "$glasgow_chatgpt_first_ms_stdev" "$glasgow_chatgpt_first_ms_min" "$glasgow_chatgpt_first_ms_max" \
            "$glasgow_chatgpt_all_ms_median" "$glasgow_chatgpt_all_ms_mean" "$glasgow_chatgpt_all_ms_stdev" "$glasgow_chatgpt_all_ms_min" "$glasgow_chatgpt_all_ms_max"
        fi
        if [ -n "${glasgow_chatgpt_first_rss_median:-}" ] && [ -n "${glasgow_chatgpt_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$glasgow_chatgpt_first_rss_median" "$glasgow_chatgpt_first_rss_mean" "$glasgow_chatgpt_first_rss_stdev" "$glasgow_chatgpt_first_rss_min" "$glasgow_chatgpt_first_rss_max" \
            "$glasgow_chatgpt_all_rss_median" "$glasgow_chatgpt_all_rss_mean" "$glasgow_chatgpt_all_rss_stdev" "$glasgow_chatgpt_all_rss_min" "$glasgow_chatgpt_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${glasgow_gemini_first_ms_runs:-}" ]; then
      read glasgow_gemini_first_ms_median glasgow_gemini_first_ms_mean glasgow_gemini_first_ms_stdev glasgow_gemini_first_ms_min glasgow_gemini_first_ms_max glasgow_gemini_first_ms_n <<< "$(calc_stats_ms $glasgow_gemini_first_ms_runs)"
      glasgow_gemini_first_ms="$glasgow_gemini_first_ms_median"
    fi
    if [ -n "${glasgow_gemini_all_ms_runs:-}" ]; then
      read glasgow_gemini_all_ms_median glasgow_gemini_all_ms_mean glasgow_gemini_all_ms_stdev glasgow_gemini_all_ms_min glasgow_gemini_all_ms_max glasgow_gemini_all_ms_n <<< "$(calc_stats_ms $glasgow_gemini_all_ms_runs)"
      glasgow_gemini_all_ms="$glasgow_gemini_all_ms_median"
    fi
    if [ -n "${glasgow_gemini_first_rss_runs:-}" ]; then
      read glasgow_gemini_first_rss_median glasgow_gemini_first_rss_mean glasgow_gemini_first_rss_stdev glasgow_gemini_first_rss_min glasgow_gemini_first_rss_max glasgow_gemini_first_rss_n <<< "$(calc_stats_kb $glasgow_gemini_first_rss_runs)"
      glasgow_gemini_first_rss_kb="$glasgow_gemini_first_rss_median"
    fi
    if [ -n "${glasgow_gemini_all_rss_runs:-}" ]; then
      read glasgow_gemini_all_rss_median glasgow_gemini_all_rss_mean glasgow_gemini_all_rss_stdev glasgow_gemini_all_rss_min glasgow_gemini_all_rss_max glasgow_gemini_all_rss_n <<< "$(calc_stats_kb $glasgow_gemini_all_rss_runs)"
      glasgow_gemini_all_rss_kb="$glasgow_gemini_all_rss_median"
    fi
    if [ "${SUBGRAPH_PHASE:-}" != "vf3" ] && [ "$ITERATIONS" -ge 1 ]; then
      {
        echo "[Subgraph Glasgow Gemini]"
        echo "Matches: ${glasgow_gemini_match}/${glasgow_gemini_total} (mismatches: ${glasgow_gemini_mismatch})"
        echo "Warmup: $WARMUP_REQUESTED"
        echo "Iterations: $ITERATIONS"
        if [ -n "${glasgow_gemini_first_ms_median:-}" ] && [ -n "${glasgow_gemini_all_ms_median:-}" ]; then
          print_stats_ms_first_all "Runtime (ms): " \
            "$glasgow_gemini_first_ms_median" "$glasgow_gemini_first_ms_mean" "$glasgow_gemini_first_ms_stdev" "$glasgow_gemini_first_ms_min" "$glasgow_gemini_first_ms_max" \
            "$glasgow_gemini_all_ms_median" "$glasgow_gemini_all_ms_mean" "$glasgow_gemini_all_ms_stdev" "$glasgow_gemini_all_ms_min" "$glasgow_gemini_all_ms_max"
        fi
        if [ -n "${glasgow_gemini_first_rss_median:-}" ] && [ -n "${glasgow_gemini_all_rss_median:-}" ]; then
          print_stats_kb_first_all "Max RSS (kB): " \
            "$glasgow_gemini_first_rss_median" "$glasgow_gemini_first_rss_mean" "$glasgow_gemini_first_rss_stdev" "$glasgow_gemini_first_rss_min" "$glasgow_gemini_first_rss_max" \
            "$glasgow_gemini_all_rss_median" "$glasgow_gemini_all_rss_mean" "$glasgow_gemini_all_rss_stdev" "$glasgow_gemini_all_rss_min" "$glasgow_gemini_all_rss_max"
        fi
        echo
      } >> outputs/result.txt
    fi

    if [ -n "${vf3_base_all_ms_runs:-}" ] || [ -n "${vf3_all_ms_runs:-}" ] || [ -n "${chatvf3_all_ms_runs:-}" ] || [ -n "${glasgow_first_ms_runs:-}" ] || [ -n "${glasgow_all_ms_runs:-}" ] || [ -n "${glasgow_gemini_all_ms_runs:-}" ] || [ -n "${glasgow_chatgpt_all_ms_runs:-}" ]; then
      SOLVER_TIME_MS_TOTAL="$(sum_ms_runs $vf3_base_all_ms_runs $vf3_all_ms_runs $chatvf3_all_ms_runs $glasgow_first_ms_runs $glasgow_all_ms_runs $glasgow_gemini_all_ms_runs $glasgow_chatgpt_all_ms_runs)"
    fi
    ;;
  *)
    echo "Unknown algorithm: $ALGORITHM" >> outputs/result.txt
    EXIT_CODE=1
    ;;
esac

VISUALIZATION_FILE="outputs/visualization.json"
rm -f "$VISUALIZATION_FILE"
if [ "$INPUT_MODE" = "generate" ] && [ -n "${SEED_USED:-}" ] && [ "${SUBGRAPH_PHASE:-}" != "glasgow" ]; then
  if [ -z "${VIS_SEED:-}" ]; then
    VIS_SEED="$SEED_USED"
  fi
  export VIS_SEED
  export ALGORITHM
  export GENERATOR_N
  export GENERATOR_K
  export GENERATOR_DENSITY
  export ITERATIONS
  python - <<'PY'
import csv
import heapq
import json
import os
import re
import subprocess
from pathlib import Path

algo = os.environ.get("ALGORITHM", "")
iterations_raw = os.environ.get("ITERATIONS", "1")
out_path = Path("outputs/visualization.json")
out_dir = Path("outputs/visualization")
out_dir.mkdir(parents=True, exist_ok=True)

if algo not in {"dijkstra", "glasgow", "vf3", "subgraph"}:
    raise SystemExit(0)

try:
    iterations = int(iterations_raw)
except (TypeError, ValueError):
    iterations = 1
if iterations < 1:
    iterations = 1

def load_metadata(iter_idx: int):
    if algo == "dijkstra":
        for candidate in (
            Path(f"outputs/generated/dijkstra/dijkstra_baseline/iter_{iter_idx}/metadata.json"),
            Path(f"outputs/generated/dijkstra/dijkstra_iter/iter_{iter_idx}/metadata.json"),
            Path(f"outputs/generated/dijkstra/dijkstra_llm/iter_{iter_idx}/metadata.json"),
        ):
            if candidate.exists():
                return candidate
        return None
    if algo == "glasgow":
        base = Path(f"outputs/generated/glasgow/glasgow_iter/iter_{iter_idx}/metadata.json")
        if base.exists():
            return base
        return None
    if algo == "vf3":
        base = Path(f"outputs/generated/vf3/vf3_iter/iter_{iter_idx}/metadata.json")
        if base.exists():
            return base
        retry_dir = Path("outputs/generated/vf3/vf3_iter_retry")
        if retry_dir.exists():
            candidates = sorted(retry_dir.glob(f"iter_{iter_idx}_retry*/metadata.json"))
            if candidates:
                return candidates[-1]
        return None
    if algo == "subgraph":
        base = Path(f"outputs/generated/subgraph/subgraph_iter/iter_{iter_idx}/metadata.json")
        if base.exists():
            return base
        return None
    return None

def parse_lad(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        first = fh.readline()
        if not first:
            return []
        n = int(first.strip())
        adj = [set() for _ in range(n)]
        for i in range(n):
            line = fh.readline()
            if not line:
                break
            parts = line.strip().split()
            if not parts:
                continue
            nums = [int(x) for x in parts]
            if len(nums) >= 2 and nums[1] == len(nums) - 2:
                d = nums[1]
                start = 2
            else:
                d = nums[0]
                start = 1
            for v in nums[start:start + d]:
                try:
                    j = int(v)
                except ValueError:
                    continue
                if 0 <= j < n and j != i:
                    adj[i].add(j)
    for i in range(len(adj)):
        for j in list(adj[i]):
            adj[j].add(i)
    return adj

def parse_vf(path: Path):
    def next_int_line(handle):
        while True:
            line = handle.readline()
            if not line:
                return None
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            nums = [int(x) for x in re.findall(r"-?\d+", line)]
            if nums:
                return nums

    with path.open("r", encoding="utf-8") as fh:
        header = next_int_line(fh)
        if not header:
            return []
        n = int(header[0])
        for _ in range(n):
            if next_int_line(fh) is None:
                break
        adj = [set() for _ in range(n)]
        for i in range(n):
            count_line = next_int_line(fh)
            if not count_line:
                break
            m = int(count_line[0])
            for _ in range(m):
                edge_nums = next_int_line(fh)
                if not edge_nums:
                    break
                if len(edge_nums) >= 2:
                    a, b = edge_nums[0], edge_nums[1]
                    if a == i and 0 <= b < n:
                        j = b
                    elif b == i and 0 <= a < n:
                        j = a
                    else:
                        j = a if 0 <= a < n else (b if 0 <= b < n else None)
                else:
                    j = edge_nums[0] if 0 <= edge_nums[0] < n else None
                if j is None or j == i:
                    continue
                adj[i].add(j)
    for i in range(len(adj)):
        for j in list(adj[i]):
            adj[j].add(i)
    return adj

def parse_dijkstra(path: Path):
    edges = []
    nodes = set()
    start_label = None
    target_label = None
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            first = row[0].strip() if row else ""
            if not first:
                continue
            if first.startswith("#"):
                meta = first[1:]
                m_start = re.search(r"\bstart\s*=\s*([^\s,]+)", meta, re.IGNORECASE)
                m_target = re.search(r"\b(?:target|end)\s*=\s*([^\s,]+)", meta, re.IGNORECASE)
                if m_start:
                    start_label = m_start.group(1).strip()
                if m_target:
                    target_label = m_target.group(1).strip()
                continue
            if first.lower() in {"source", "src", "from"}:
                continue
            if len(row) < 2:
                continue
            src = row[0].strip()
            tgt = row[1].strip()
            if not src or not tgt:
                continue
            weight = 1.0
            if len(row) >= 3 and str(row[2]).strip():
                try:
                    weight = float(str(row[2]).strip())
                except ValueError:
                    weight = 1.0
            nodes.add(src)
            nodes.add(tgt)
            edges.append((src, tgt, weight))

    node_list = sorted(nodes)
    node_index = {name: idx for idx, name in enumerate(node_list)}
    undirected_adj = [set() for _ in range(len(node_list))]
    directed_adj = [[] for _ in range(len(node_list))]

    for src, tgt, weight in edges:
        i = node_index.get(src)
        j = node_index.get(tgt)
        if i is None or j is None or i == j:
            continue
        undirected_adj[i].add(j)
        undirected_adj[j].add(i)
        directed_adj[i].append((j, weight))

    start_idx = node_index.get(start_label) if start_label else None
    target_idx = node_index.get(target_label) if target_label else None
    path_nodes = []
    path_distance = None

    if (
        start_idx is not None
        and target_idx is not None
        and 0 <= start_idx < len(node_list)
        and 0 <= target_idx < len(node_list)
    ):
        dist = [float("inf")] * len(node_list)
        parent = [-1] * len(node_list)
        dist[start_idx] = 0.0
        pq = [(0.0, start_idx)]
        while pq:
            d, u = heapq.heappop(pq)
            if d != dist[u]:
                continue
            if u == target_idx:
                break
            for v, w in directed_adj[u]:
                nd = d + w
                if nd < dist[v]:
                    dist[v] = nd
                    parent[v] = u
                    heapq.heappush(pq, (nd, v))
        if dist[target_idx] != float("inf"):
            path_distance = dist[target_idx]
            cur = target_idx
            while cur != -1:
                path_nodes.append(cur)
                if cur == start_idx:
                    break
                cur = parent[cur]
            if not path_nodes or path_nodes[-1] != start_idx:
                path_nodes = []
                path_distance = None
            else:
                path_nodes.reverse()

    return {
        "adj": undirected_adj,
        "node_list": node_list,
        "start_label": start_label,
        "target_label": target_label,
        "start_idx": start_idx,
        "target_idx": target_idx,
        "path_nodes": path_nodes,
        "path_distance": path_distance,
    }

def edge_key(a, b):
    return (a, b) if a <= b else (b, a)

def build_visualization(pattern_path, target_path, pattern_nodes, iteration_index, seed_value):
    if algo == "dijkstra":
        parsed = parse_dijkstra(target_path)
        adj_target = parsed.get("adj") or []
        node_labels = parsed.get("node_list") or []
        start_idx = parsed.get("start_idx")
        target_idx = parsed.get("target_idx")
        path_nodes = parsed.get("path_nodes") or []
        path_distance = parsed.get("path_distance")

        target_edges = set()
        for i, nbrs in enumerate(adj_target):
            for j in nbrs:
                if i == j:
                    continue
                target_edges.add(edge_key(i, j))

        max_nodes = 4000
        max_edges = 4000
        truncated = False
        total_nodes = len(adj_target)
        total_edges = len(target_edges)

        allowed_nodes = set(range(min(total_nodes, max_nodes)))
        if total_nodes > max_nodes:
            truncated = True

        edges_sorted = sorted(target_edges)
        filtered_edges = [e for e in edges_sorted if e[0] in allowed_nodes and e[1] in allowed_nodes]
        if len(filtered_edges) > max_edges:
            filtered_edges = filtered_edges[:max_edges]
            truncated = True
        filtered_edge_set = set(filtered_edges)

        nodes = []
        for i in range(min(total_nodes, max_nodes)):
            label = node_labels[i] if i < len(node_labels) else str(i)
            nodes.append({"data": {"id": str(i), "label": str(label)}})

        edges = []
        for a, b in filtered_edges:
            edges.append({"data": {"id": f"{a}-{b}", "source": str(a), "target": str(b)}})

        highlight_nodes = []
        if start_idx is not None:
            highlight_nodes.append(start_idx)
        if target_idx is not None and target_idx != start_idx:
            highlight_nodes.append(target_idx)
        if path_nodes:
            for node in path_nodes:
                if node not in highlight_nodes:
                    highlight_nodes.append(node)

        highlight_edge_ids = []
        for a, b in zip(path_nodes, path_nodes[1:]):
            ek = edge_key(a, b)
            if ek in filtered_edge_set:
                highlight_edge_ids.append(f"{ek[0]}-{ek[1]}")

        payload = {
            "algorithm": algo,
            "seed": seed_value,
            "iteration": iteration_index,
            "node_count": total_nodes,
            "edge_count": total_edges,
            "nodes": nodes,
            "edges": edges,
            "highlight_nodes": [str(n) for n in highlight_nodes if n in allowed_nodes],
            "highlight_edges": highlight_edge_ids,
            "pattern_node_count": 0,
            "pattern_nodes": [],
            "pattern_edges": [],
            "solutions": [],
            "no_solutions": len(path_nodes) == 0,
            "truncated": truncated,
        }
        if parsed.get("start_label"):
            payload["start_label"] = parsed.get("start_label")
        if parsed.get("target_label"):
            payload["target_label"] = parsed.get("target_label")
        if path_nodes:
            payload["shortest_path"] = [
                node_labels[i] if 0 <= i < len(node_labels) else str(i)
                for i in path_nodes
            ]
        if path_distance is not None:
            payload["shortest_path_distance"] = path_distance
        return payload

    adj_pattern = parse_lad(pattern_path) if algo == "glasgow" else parse_vf(pattern_path)
    adj_target = parse_lad(target_path) if algo == "glasgow" else parse_vf(target_path)

    target_edges = set()
    for i, nbrs in enumerate(adj_target):
        for j in nbrs:
            if i == j:
                continue
            target_edges.add(edge_key(i, j))

    pattern_edges = set()
    for i, nbrs in enumerate(adj_pattern):
        for j in nbrs:
            if i == j:
                continue
            pattern_edges.add(edge_key(i, j))

    mapping = {}
    solutions = []
    solution_limit = 1000
    solver_stdout = ""
    solver_stderr = ""
    solver_cmd = []
    solution_lines = 0

    if algo == "glasgow":
        solver = Path("baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver")
        if solver.exists():
            solver_cmd = [
                str(solver),
                "--induced",
                "--format",
                "lad",
                "--print-all-solutions",
                "--solution-limit",
                str(solution_limit),
                str(pattern_path),
                str(target_path),
            ]
            out = subprocess.run(solver_cmd, capture_output=True, text=True)
            if out.returncode == 0:
                solver_stdout = out.stdout or ""
                solver_stderr = out.stderr or ""
                for line in out.stdout.splitlines():
                    if "mapping =" not in line:
                        continue
                    pairs = re.findall(r"\(\s*(\d+)\s*->\s*(\d+)\s*\)", line)
                    if not pairs:
                        continue
                    solution_lines += 1
                    mapping = {int(p): int(t) for p, t in pairs}
                    if mapping and len(solutions) < solution_limit:
                        solutions.append(mapping)
    elif algo in {"vf3", "subgraph"}:
        solver = Path("baselines/vf3lib/bin/vf3")
        if solver.exists():
            solver_cmd = [str(solver), "-u", "-s", "-r", "0", str(pattern_path), str(target_path)]
            out = subprocess.run(solver_cmd, capture_output=True, text=True)
            if out.returncode == 0:
                solver_stdout = out.stdout or ""
                solver_stderr = out.stderr or ""
                text_out = "\n".join(part for part in [solver_stdout, solver_stderr] if part)
                lines = [line.strip() for line in text_out.splitlines() if line.strip()]
                for line in lines:
                    if "," in line and ":" in line:
                        pairs = re.findall(r"(\d+)\s*,\s*(\d+)\s*:", line)
                        if not pairs:
                            continue
                        solution_lines += 1
                        mapping = {int(p): int(t) for p, t in pairs}
                        if mapping and len(solutions) < solution_limit:
                            solutions.append(mapping)
                if not solutions:
                    pairs = re.findall(r"\(\s*(\d+)\s*->\s*(\d+)\s*\)", text_out)
                    if not pairs:
                        pairs = re.findall(r"(\d+)\s*->\s*(\d+)", text_out)
                    if pairs:
                        mapping = {int(p): int(t) for p, t in pairs}
                        if mapping:
                            solutions.append(mapping)

    if not solutions and pattern_nodes:
        mapping = {i: node for i, node in enumerate(pattern_nodes)}
        solutions.append(mapping)
    elif solutions:
        mapping = solutions[0]

    pattern_edge_list = sorted(pattern_edges)

    def mapping_to_solution(mapping_dict):
        if not mapping_dict:
            return None
        pattern_n = len(adj_pattern)
        mapping_list = [None] * pattern_n
        for p, t in mapping_dict.items():
            if 0 <= p < pattern_n:
                mapping_list[p] = t
        highlight_nodes = [t for t in mapping_list if t is not None]
        highlight_edges = []
        for a, b in pattern_edges:
            ta = mapping_dict.get(a)
            tb = mapping_dict.get(b)
            if ta is None or tb is None:
                continue
            ek = edge_key(ta, tb)
            if ek in target_edges:
                highlight_edges.append(ek)
        return {
            "mapping": mapping_list,
            "highlight_nodes": highlight_nodes,
            "highlight_edges": highlight_edges,
        }

    max_nodes = 4000
    max_edges = 4000
    truncated = False

    total_nodes = len(adj_target)
    total_edges = len(target_edges)

    allowed_nodes = set(range(min(total_nodes, max_nodes)))
    if total_nodes > max_nodes:
        truncated = True

    edges_sorted = sorted(target_edges)
    filtered_edges = [e for e in edges_sorted if e[0] in allowed_nodes and e[1] in allowed_nodes]
    if len(filtered_edges) > max_edges:
        filtered_edges = filtered_edges[:max_edges]
        truncated = True

    filtered_edge_set = set(filtered_edges)

    nodes = []
    for i in range(min(total_nodes, max_nodes)):
        nodes.append({"data": {"id": str(i), "label": str(i)}})

    edges = []
    for a, b in filtered_edges:
        eid = f"{a}-{b}"
        edges.append({"data": {"id": eid, "source": str(a), "target": str(b)}})

    solutions_payload = []
    seen_mappings = set()
    for mapping_dict in solutions:
        solution = mapping_to_solution(mapping_dict)
        if not solution:
            continue
        mapping_key = tuple(solution["mapping"])
        if mapping_key in seen_mappings:
            continue
        seen_mappings.add(mapping_key)
        solution["highlight_nodes"] = [n for n in solution["highlight_nodes"] if n in allowed_nodes]
        solution_edges = [e for e in solution["highlight_edges"] if e in filtered_edge_set]
        solution["highlight_edges"] = [f"{a}-{b}" for (a, b) in solution_edges]
        solutions_payload.append(solution)
        if len(solutions_payload) >= solution_limit:
            break
    if solutions_payload:
        highlight_nodes = solutions_payload[0]["highlight_nodes"]
        highlight_edge_ids = solutions_payload[0]["highlight_edges"]
        mapping_list = solutions_payload[0]["mapping"]
    else:
        highlight_nodes = []
        highlight_edge_ids = []
        mapping_list = []

    payload = {
        "algorithm": algo,
        "seed": seed_value,
        "iteration": iteration_index,
        "node_count": total_nodes,
        "edge_count": total_edges,
        "nodes": nodes,
        "edges": edges,
        "highlight_nodes": [str(n) for n in highlight_nodes],
        "highlight_edges": highlight_edge_ids,
        "pattern_node_count": len(adj_pattern),
        "pattern_nodes": mapping_list,
        "pattern_edges": [[int(a), int(b)] for (a, b) in pattern_edge_list],
        "solutions": solutions_payload,
        "no_solutions": len(solutions_payload) == 0,
        "truncated": truncated,
    }
    if solver_cmd:
        payload["solver_cmd"] = solver_cmd
        payload["solver_solution_lines"] = solution_lines
        if solver_stdout:
            payload["solver_stdout"] = solver_stdout[:5000]
            if len(solver_stdout) > 5000:
                payload["solver_stdout_truncated"] = True
        if solver_stderr:
            payload["solver_stderr"] = solver_stderr[:5000]
            if len(solver_stderr) > 5000:
                payload["solver_stderr_truncated"] = True
    return payload

vis_iterations = []
for i in range(1, iterations + 1):
    meta_path = load_metadata(i)
    if not meta_path:
        continue
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    files = [Path(p) for p in meta.get("files", []) if p]
    if not files:
        continue
    if algo == "subgraph":
        vf_files = [p for p in files if p.suffix.lower() == ".vf"]
        if vf_files:
            pattern_path = next((p for p in vf_files if "pattern" in p.name), vf_files[0])
            target_path = next((p for p in vf_files if "target" in p.name), vf_files[-1])
        else:
            pattern_path = next((p for p in files if "pattern" in p.name), files[0])
            target_path = next((p for p in files if "target" in p.name), files[-1])
    else:
        pattern_path = next((p for p in files if "pattern" in p.name), files[0])
        target_path = next((p for p in files if "target" in p.name), files[-1])
    if not pattern_path.exists() or not target_path.exists():
        continue
    pattern_nodes = None
    candidate = meta.get("pattern_nodes")
    if isinstance(candidate, list) and all(isinstance(x, int) for x in candidate):
        pattern_nodes = candidate
    seed_value = meta.get("seed")
    try:
        vis_payload = build_visualization(pattern_path, target_path, pattern_nodes, i, seed_value)
    except Exception:
        continue
    if vis_payload:
        vis_iterations.append(vis_payload)

if not vis_iterations:
    out_path.write_text(
        json.dumps(
            {
                "algorithm": algo,
                "visualization_error": "No visualization iterations available",
                "visualization_iterations": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

payload = dict(vis_iterations[0])
payload["visualization_iterations"] = vis_iterations
out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
  if [ ! -s "$VISUALIZATION_FILE" ]; then
    echo "[Visualization] visualization.json was not generated." >> outputs/result.txt
  fi
fi

finish_run
echo "EXIT_CODE=$EXIT_CODE" >> "$GITHUB_OUTPUT"
echo "REQUEST_ID=${REQUEST_ID}" >> "$GITHUB_OUTPUT"
echo "ITERATIONS=${ITERATIONS}" >> "$GITHUB_OUTPUT"
echo "WARMUP=${WARMUP_REQUESTED}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_BASELINE_MS=${dijkstra_baseline_ms:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_LLM_MS=${dijkstra_llm_ms:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_GEMINI_MS=${dijkstra_gemini_ms:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_BASELINE_MS_STDEV=${dijkstra_baseline_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_LLM_MS_STDEV=${dijkstra_llm_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_GEMINI_MS_STDEV=${dijkstra_gemini_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_BASELINE_RSS_KB=${dijkstra_baseline_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_LLM_RSS_KB=${dijkstra_llm_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_GEMINI_RSS_KB=${dijkstra_gemini_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_BASELINE_RSS_KB_STDEV=${dijkstra_baseline_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_LLM_RSS_KB_STDEV=${dijkstra_llm_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_GEMINI_RSS_KB_STDEV=${dijkstra_gemini_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_CHATGPT_MATCH=${dijkstra_match:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_CHATGPT_TOTAL=${dijkstra_total:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_CHATGPT_MISMATCH=${dijkstra_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_MATCH=${dijkstra_match:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_TOTAL=${dijkstra_total:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_MISMATCH=${dijkstra_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_GEMINI_MATCH=${dijkstra_gemini_match:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_GEMINI_TOTAL=${dijkstra_gemini_total:-}" >> "$GITHUB_OUTPUT"
echo "DIJKSTRA_GEMINI_MISMATCH=${dijkstra_gemini_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_FIRST_MS=${glasgow_first_ms:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_ALL_MS=${glasgow_all_ms:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_FIRST_MS_STDEV=${glasgow_first_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_ALL_MS_STDEV=${glasgow_all_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_FIRST_RSS_KB=${glasgow_first_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_ALL_RSS_KB=${glasgow_all_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_FIRST_RSS_KB_STDEV=${glasgow_first_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_ALL_RSS_KB_STDEV=${glasgow_all_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_FIRST_MS=${glasgow_gemini_first_ms:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_ALL_MS=${glasgow_gemini_all_ms:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_FIRST_MS_STDEV=${glasgow_gemini_first_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_ALL_MS_STDEV=${glasgow_gemini_all_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_FIRST_RSS_KB=${glasgow_gemini_first_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_ALL_RSS_KB=${glasgow_gemini_all_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_FIRST_RSS_KB_STDEV=${glasgow_gemini_first_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_ALL_RSS_KB_STDEV=${glasgow_gemini_all_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_FIRST_MS=${glasgow_chatgpt_first_ms:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_ALL_MS=${glasgow_chatgpt_all_ms:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_FIRST_MS_STDEV=${glasgow_chatgpt_first_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_ALL_MS_STDEV=${glasgow_chatgpt_all_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_FIRST_RSS_KB=${glasgow_chatgpt_first_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_ALL_RSS_KB=${glasgow_chatgpt_all_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_FIRST_RSS_KB_STDEV=${glasgow_chatgpt_first_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_ALL_RSS_KB_STDEV=${glasgow_chatgpt_all_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_BASELINE_SUCCESS=${glasgow_success:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_BASELINE_FAILED=${glasgow_fail:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_BASELINE_MATCH=${glasgow_baseline_match:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_BASELINE_TOTAL=${glasgow_baseline_total:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_BASELINE_MISMATCH=${glasgow_baseline_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_MATCH=${glasgow_chatgpt_match:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_TOTAL=${glasgow_chatgpt_total:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_CHATGPT_MISMATCH=${glasgow_chatgpt_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_MATCH=${glasgow_gemini_match:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_TOTAL=${glasgow_gemini_total:-}" >> "$GITHUB_OUTPUT"
echo "GLASGOW_GEMINI_MISMATCH=${glasgow_gemini_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_FIRST_MS=${vf3_base_first_ms:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_ALL_MS=${vf3_base_all_ms:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_FIRST_MS_STDEV=${vf3_base_first_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_ALL_MS_STDEV=${vf3_base_all_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_FIRST_RSS_KB=${vf3_base_first_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_ALL_RSS_KB=${vf3_base_all_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_FIRST_RSS_KB_STDEV=${vf3_base_first_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASE_ALL_RSS_KB_STDEV=${vf3_base_all_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_FIRST_MS=${vf3_first_ms:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_ALL_MS=${vf3_all_ms:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_FIRST_MS_STDEV=${vf3_first_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_ALL_MS_STDEV=${vf3_all_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_FIRST_RSS_KB=${vf3_first_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_ALL_RSS_KB=${vf3_all_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_FIRST_RSS_KB_STDEV=${vf3_first_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_ALL_RSS_KB_STDEV=${vf3_all_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_FIRST_MS=${chatvf3_first_ms:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_ALL_MS=${chatvf3_all_ms:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_FIRST_MS_STDEV=${chatvf3_first_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_ALL_MS_STDEV=${chatvf3_all_ms_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_FIRST_RSS_KB=${chatvf3_first_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_ALL_RSS_KB=${chatvf3_all_rss_kb:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_FIRST_RSS_KB_STDEV=${chatvf3_first_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_ALL_RSS_KB_STDEV=${chatvf3_all_rss_stdev:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASELINE_SUCCESS=${vf3_success:-}" >> "$GITHUB_OUTPUT"
echo "VF3_BASELINE_FAILED=${vf3_fail:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_MATCH=${vf3_chatgpt_match:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_TOTAL=${vf3_chatgpt_total:-}" >> "$GITHUB_OUTPUT"
echo "VF3_CHATGPT_MISMATCH=${vf3_chatgpt_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_MATCH=${vf3_gemini_match:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_TOTAL=${vf3_gemini_total:-}" >> "$GITHUB_OUTPUT"
echo "VF3_GEMINI_MISMATCH=${vf3_gemini_mismatch:-}" >> "$GITHUB_OUTPUT"
echo "SUBGRAPH_PHASE=${SUBGRAPH_PHASE:-}" >> "$GITHUB_OUTPUT"
echo "SEED_USED=${SEED_USED:-}" >> "$GITHUB_OUTPUT"
# Always exit 0 so later steps run and results are committed
exit 0
