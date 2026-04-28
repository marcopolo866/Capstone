package edu.uidaho.capstone.androidrunner.data;

import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.SolverVariant;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class SolverCatalog {
    private SolverCatalog() {
    }

    public static List<SolverVariant> all() {
        List<SolverVariant> rows = new ArrayList<>();
        rows.add(new SolverVariant("dijkstra_baseline", "Dijkstra Baseline", "shortest_path", "dijkstra", "baseline"));
        rows.add(new SolverVariant("sp_via_baseline", "With Intermediate Baseline", "shortest_path", "sp_via", "baseline"));
        rows.add(new SolverVariant("vf3_baseline", "VF3 Baseline", "subgraph", "vf3", "baseline"));
        rows.add(new SolverVariant("glasgow_baseline", "Glasgow Baseline", "subgraph", "glasgow", "baseline"));

        rows.add(new SolverVariant("dijkstra_chatgpt", "Dijkstra ChatGPT", "shortest_path", "dijkstra", "variant"));
        rows.add(new SolverVariant("dijkstra_claude", "Dijkstra Claude", "shortest_path", "dijkstra", "variant"));
        rows.add(new SolverVariant("dijkstra_gemini", "Dijkstra Gemini", "shortest_path", "dijkstra", "variant"));
        rows.add(new SolverVariant("sp_via_chatgpt", "With Intermediate ChatGPT", "shortest_path", "sp_via", "variant"));
        rows.add(new SolverVariant("sp_via_claude", "With Intermediate Claude", "shortest_path", "sp_via", "variant"));
        rows.add(new SolverVariant("sp_via_gemini", "With Intermediate Gemini", "shortest_path", "sp_via", "variant"));

        rows.add(new SolverVariant("vf3_chatgpt_control", "VF3 ChatGPT Control", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_chatgpt_dense", "VF3 ChatGPT Dense", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_chatgpt_sparse", "VF3 ChatGPT Sparse", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_claude_control", "VF3 Claude Control", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_claude_dense", "VF3 Claude Dense", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_claude_sparse", "VF3 Claude Sparse", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_gemini_control", "VF3 Gemini Control", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_gemini_dense", "VF3 Gemini Dense", "subgraph", "vf3", "variant"));
        rows.add(new SolverVariant("vf3_gemini_sparse", "VF3 Gemini Sparse", "subgraph", "vf3", "variant"));

        rows.add(new SolverVariant("glasgow_chatgpt_control", "Glasgow ChatGPT Control", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_chatgpt_dense", "Glasgow ChatGPT Dense", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_chatgpt_sparse", "Glasgow ChatGPT Sparse", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_claude_control", "Glasgow Claude Control", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_claude_dense", "Glasgow Claude Dense", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_claude_sparse", "Glasgow Claude Sparse", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_gemini_control", "Glasgow Gemini Control", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_gemini_dense", "Glasgow Gemini Dense", "subgraph", "glasgow", "variant"));
        rows.add(new SolverVariant("glasgow_gemini_sparse", "Glasgow Gemini Sparse", "subgraph", "glasgow", "variant"));
        return Collections.unmodifiableList(rows);
    }
}
