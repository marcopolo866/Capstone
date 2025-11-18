import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter import font as tkfont
import csv
import random
import math
import os
import re
import threading
import queue
import time
from collections import defaultdict

############################################################
# Graph data model
############################################################
class GraphModel:
    def __init__(self, directed=False, weighted=True):
        self.directed = directed
        self.weighted = weighted
        self.nodes = {}            # label -> (x, y)
        self.edges = []            # list of {'id', 'u', 'v', 'w'}
        self._edge_id_seq = 0
        self._edge_lookup = {}
        self._edge_keys = set()

    def clear(self):
        self.nodes.clear()
        self.edges.clear()
        self._edge_id_seq = 0
        self._edge_lookup.clear()
        self._edge_keys.clear()

    def add_node(self, label, x, y):
        self.nodes[label] = (x, y)

    def remove_node(self, label):
        if label in self.nodes:
            self.nodes.pop(label)
            # remove incident edges
            self.edges = [e for e in self.edges if e['u'] != label and e['v'] != label]
            self._edge_lookup = {e['id']: e for e in self.edges}
            self._edge_keys = {self._edge_key(e['u'], e['v']) for e in self.edges}

    def add_edge(self, u, v, w=1):
        if u not in self.nodes or v not in self.nodes:
            return None
        if not self.weighted:
            w = None
        edge_key = self._edge_key(u, v)
        if edge_key in self._edge_keys:
            return None
        edge = {'id': self._edge_id_seq, 'u': u, 'v': v, 'w': w}
        self._edge_id_seq += 1
        self.edges.append(edge)
        self._edge_lookup[edge['id']] = edge
        self._edge_keys.add(edge_key)
        # if undirected, store just one copy in edges
        return edge

    def remove_edge(self, edge_id):
        edge = self._edge_lookup.pop(edge_id, None)
        if not edge:
            return
        self.edges = [e for e in self.edges if e['id'] != edge_id]
        self._edge_keys.discard(self._edge_key(edge['u'], edge['v']))

    def labels(self):
        return list(self.nodes.keys())

    def get_edge(self, edge_id):
        return self._edge_lookup.get(edge_id)

    def _edge_key(self, u, v):
        if u == v:
            return (u,)
        return tuple(sorted((u, v)))

    def to_csv(self, filepath, header_style='long', start_label=None, target_label=None, include_weight=True):
        """
        header_style: 'long' -> source,target,weight ; 'short' -> src,dst,w
        include_weight: if False, omit weight column entirely
        Optionally includes a first-line comment: "# start=... target=..."
        """
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            if start_label or target_label:
                parts = []
                if start_label:
                    parts.append(f"start={start_label}")
                if target_label:
                    parts.append(f"target={target_label}")
                f.write(f"# {' '.join(parts)}\n")
            writer = csv.writer(f)
            writer.writerow(['source', 'target', 'weight'])
            for edge in self.edges:
                weight = edge['w'] if (self.weighted and include_weight and edge['w'] is not None) else 1
                writer.writerow([edge['u'], edge['v'], weight])


class GenerationAborted(Exception):
    """Raised when a user aborts an in-progress generation."""
    pass

############################################################
# GUI application
############################################################
class GraphBuilderApp(tk.Tk):
    NODE_RADIUS = 10
    WEIGHT_LABEL_RENDER_LIMIT = 50_000
    ARROW_RENDER_LIMIT = 150_000

    def __init__(self):
        super().__init__()
        self.title("Graph Test Data Builder")
        self.geometry("1200x800")

        # Model
        self.graph = GraphModel(directed=False, weighted=True)
        self.label_prefix = tk.StringVar(value="")
        self.next_index = tk.IntVar(value=1)

        # UI State
        self.add_nodes_mode = tk.BooleanVar(value=False)
        self.selected_nodes = []  # ordered labels
        self.selected_edges = []  # ordered edge ids
        self.node_items = {}      # label -> (oval_id, text_id or None)
        self.item_to_label = {}   # canvas item id -> label
        self.edge_items = {}      # edge id -> {'line': id, 'weight': id or None}
        self.item_to_edge = {}    # canvas item id -> edge id
        self.connect_button = None
        self._generate_option_widgets = {'ring': [], 'grid': []}
        self._disabled_label_color = "#94a3b8"
        self._is_redrawing = False
        self.node_tooltip = None
        self.tooltip_title_label = None
        self.tooltip_text = None
        self.tooltip_sort_var = tk.StringVar(value='label')
        self.tooltip_sort_var.trace_add('write', self._on_tooltip_sort_change)
        self.edit_weight_button = None
        self.tooltip_data = None
        self.tooltip_node = None
        self.tooltip_has_weights = False
        self.tooltip_hide_job = None
        self.tooltip_hide_delay_ms = 500
        self.tooltip_font = tkfont.Font(family="Segoe UI", size=10)
        self.tooltip_sort_font = tkfont.Font(family="Segoe UI", size=9)
        self.tooltip_sort_font_bold = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.tooltip_instruction_label = None
        self.tooltip_sort_label_label = None
        self.tooltip_sort_label_weight = None
        self.mass_nodes_progress_var = tk.StringVar(value="")
        self.mass_edges_progress_var = tk.StringVar(value="")
        self.mass_nodes_progress_label = None
        self.mass_nodes_progress_bar = None
        self.mass_edges_progress_label = None
        self.mass_edges_progress_bar = None
        self._mass_generation_active = False
        self._mass_progress_queue = None
        self._mass_worker_thread = None
        self._mass_job_config = None
        self._generation_in_progress = False
        self._generation_abort_event = None

        # View state
        self.zoom_level = 1.0
        self.view_x = 0.0
        self.view_y = 0.0
        self.min_zoom = 0.02
        self.max_zoom = 4.0
        self.zoom_offset_x = 0.0
        self.zoom_offset_y = 0.0

        # Build UI
        self._build_layout()
        self._bind_canvas_events()

    ############################################################
    # Layout
    ############################################################
    def _build_layout(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        container = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        container.grid(row=0, column=0, sticky="nsew")

        # Left: Canvas with scrollbars
        left = ttk.Frame(container)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(left, bg="#0f172a", scrollregion=(0, 0, 4000, 3000), highlightthickness=0)
        hbar = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        # Right: Controls
        right = ttk.Notebook(container)

        # --- Manual tab ---
        manual = ttk.Frame(right)
        ttk.Label(manual, text="Canvas actions:").grid(row=0, column=0, sticky="w", pady=(8,2))
        ttk.Checkbutton(
            manual,
            text="Add Nodes",
            variable=self.add_nodes_mode,
            command=self._on_add_nodes_toggle
        ).grid(row=1, column=0, sticky="w")
        self.connect_button = ttk.Button(manual, text="Connect selected", command=self.connect_selected_nodes)
        self.connect_button.grid(row=1, column=1, sticky="w", padx=(12, 0))
        self.connect_button.state(['disabled'])
        ttk.Button(manual, text="Delete selection", command=self.delete_selected_items).grid(row=1, column=2, sticky="w", padx=(12, 0))
        ttk.Button(manual, text="Clear selection", command=self.clear_selection_button).grid(row=1, column=3, sticky="w", padx=(12, 0))
        self.edit_weight_button = ttk.Button(manual, text="Edit edge weight", command=self.edit_selected_edge_weight)
        self.edit_weight_button.grid(row=1, column=4, sticky="w", padx=(12, 0))

        ttk.Separator(manual).grid(row=2, column=0, columnspan=6, sticky="ew", pady=8)

        ttk.Label(manual, text="Label prefix").grid(row=3, column=0, sticky="w")
        ttk.Entry(manual, textvariable=self.label_prefix, width=8).grid(row=3, column=1, sticky="w")
        ttk.Label(manual, text="Start index").grid(row=3, column=2, sticky="w")
        ttk.Spinbox(manual, from_=0, to=10_000_000, textvariable=self.next_index, width=8).grid(row=3, column=3, sticky="w")

        # Directed / weighted toggles
        self.directed_var = tk.BooleanVar(value=False)
        self.weighted_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(manual, text="Directed graph", variable=self.directed_var, command=self._on_toggle_directed).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8,0))
        ttk.Checkbutton(manual, text="Weighted edges", variable=self.weighted_var, command=self._on_toggle_weighted).grid(row=4, column=2, columnspan=2, sticky="w", pady=(8,0))

        # Layout helpers
        ttk.Separator(manual).grid(row=5, column=0, columnspan=6, sticky="ew", pady=8)
        ttk.Label(manual, text="Quick layout:").grid(row=6, column=0, sticky="w")
        ttk.Button(manual, text="Circle", command=self.layout_circle).grid(row=6, column=1, sticky="w")
        ttk.Button(manual, text="Grid", command=self.layout_grid).grid(row=6, column=2, sticky="w")
        ttk.Button(manual, text="Random", command=self.layout_random).grid(row=6, column=3, sticky="w")

        # Clear
        ttk.Separator(manual).grid(row=7, column=0, columnspan=6, sticky="ew", pady=8)
        ttk.Button(manual, text="Clear graph", command=self.clear_graph).grid(row=8, column=0, sticky="w")

        # Status
        self.status_var = tk.StringVar(value="Ready")
        ttk.Separator(manual).grid(row=9, column=0, columnspan=6, sticky="ew", pady=8)
        ttk.Label(manual, textvariable=self.status_var, foreground="#334155").grid(row=10, column=0, columnspan=6, sticky="w")
        manual_help_text = (
            "Manual tab tips:\n"
            "- Click nodes to select up to two at a time; hold Ctrl to pick more nodes or even edges for bulk deletes.\n"
            "- Use Connect selected to add an edge between the two most recently selected nodes (prompts for a weight when enabled).\n"
            "- Delete selection removes highlighted nodes/edges; Clear selection simply deselects everything, while Clear graph wipes all data and resets the start index.\n"
            "- Toggle Add Nodes to drop new vertices wherever you click. Drag with the middle/right mouse button to pan and use the mouse wheel to zoom."
        )
        ttk.Label(manual, text=manual_help_text, wraplength=360, justify="left", foreground="#475569").grid(
            row=11, column=0, columnspan=6, sticky="nw", pady=(8, 0)
        )

        # --- Generate tab ---
        gen = ttk.Frame(right)
        for col in range(4):
            gen.columnconfigure(col, weight=1)
        self.gen_nodes_var = tk.IntVar(value=20)
        self.gen_type_var = tk.StringVar(value="random")  # random | grid | ring | path | star
        self.gnp_p_var = tk.DoubleVar(value=0.5)
        self.k_neighbors_var = tk.IntVar(value=4)
        self.grid_rows_var = tk.IntVar(value=20)
        self.grid_cols_var = tk.IntVar(value=25)
        self.weight_min_var = tk.IntVar(value=1)
        self.weight_max_var = tk.IntVar(value=10)
        self.render_edges_var = tk.BooleanVar(value=True)
        self.mass_export_format_var = tk.StringVar(value=".csv")
        self.gen_type_var.trace_add('write', self._on_gen_type_change)
        self.estimated_edges_var = tk.StringVar(value="Estimated edges: ~0")
        for var in (self.gen_nodes_var, self.gnp_p_var, self.k_neighbors_var,
                    self.grid_rows_var, self.grid_cols_var):
            var.trace_add('write', self._on_generate_param_change)

        r = 0
        ttk.Label(gen, text="Graph type:").grid(row=r, column=0, sticky="w", pady=(8,2))
        ttk.Combobox(gen, textvariable=self.gen_type_var, values=["random", "grid", "ring", "path", "star"], width=10, state="readonly").grid(row=r, column=1, sticky="w")
        r += 1

        ttk.Label(gen, text="# nodes (N):").grid(row=r, column=0, sticky="w")
        ttk.Spinbox(gen, from_=1, to=1_000_000, textvariable=self.gen_nodes_var, width=10).grid(row=r, column=1, sticky="w")
        r += 1

        # gnp options
        ttk.Label(gen, text="p (for G(n,p)):").grid(row=r, column=0, sticky="w")
        ttk.Entry(gen, textvariable=self.gnp_p_var, width=10).grid(row=r, column=1, sticky="w")
        ttk.Label(gen, text="Higher p creates more random edges between nodes, lower p creates less connections.\n[0 < p ≤ 1]", wraplength=260, foreground="#475569").grid(row=r, column=2, columnspan=2, sticky="w")
        r += 1

        # ring options
        ring_header = ttk.Label(gen, text="Ring", font=("Segoe UI", 10, "bold"))
        ring_header.grid(row=r, column=0, columnspan=2, sticky="w", pady=(8,2))
        self._register_generate_widget('ring', ring_header, kind='label')
        r += 1

        # ring/path/star options
        ring_label = ttk.Label(gen, text="k neighbors (ring):")
        ring_label.grid(row=r, column=0, sticky="w")
        ring_spin = ttk.Spinbox(gen, from_=1, to=1000, textvariable=self.k_neighbors_var, width=10)
        ring_spin.grid(row=r, column=1, sticky="w")
        self._register_generate_widget('ring', ring_label, kind='label')
        self._register_generate_widget('ring', ring_spin, kind='input')
        r += 1

        # grid options
        grid_header = ttk.Label(gen, text="Grid", font=("Segoe UI", 10, "bold"))
        grid_header.grid(row=r, column=0, columnspan=2, sticky="w", pady=(8,2))
        self._register_generate_widget('grid', grid_header, kind='label')
        r += 1

        grid_rows_label = ttk.Label(gen, text="Grid rows:")
        grid_rows_label.grid(row=r, column=0, sticky="w")
        grid_rows_spin = ttk.Spinbox(gen, from_=1, to=2000, textvariable=self.grid_rows_var, width=10)
        grid_rows_spin.grid(row=r, column=1, sticky="w")
        self._register_generate_widget('grid', grid_rows_label, kind='label')
        self._register_generate_widget('grid', grid_rows_spin, kind='input')
        r += 1

        grid_cols_label = ttk.Label(gen, text="Grid cols:")
        grid_cols_label.grid(row=r, column=0, sticky="w")
        grid_cols_spin = ttk.Spinbox(gen, from_=1, to=2000, textvariable=self.grid_cols_var, width=10)
        grid_cols_spin.grid(row=r, column=1, sticky="w")
        self._register_generate_widget('grid', grid_cols_label, kind='label')
        self._register_generate_widget('grid', grid_cols_spin, kind='input')
        r += 1

        # weights
        ttk.Separator(gen).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        r += 1
        ttk.Label(gen, text="Weight min:").grid(row=r, column=0, sticky="w")
        ttk.Spinbox(gen, from_=-10_000, to=10_000, textvariable=self.weight_min_var, width=10).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(gen, text="Weight max:").grid(row=r, column=0, sticky="w")
        ttk.Spinbox(gen, from_=-10_000, to=10_000, textvariable=self.weight_max_var, width=10).grid(row=r, column=1, sticky="w")
        r += 1

        ttk.Checkbutton(gen, text="Render edges", variable=self.render_edges_var, command=self._on_render_edges_toggle).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8,0))
        ttk.Label(gen, text="Rendering more than 100,000 edges not recommended.", foreground="#b45309", wraplength=200, justify="left").grid(row=r, column=2, columnspan=2, sticky="w")
        r += 1
        ttk.Label(gen, textvariable=self.estimated_edges_var, foreground="#475569").grid(row=r, column=0, columnspan=4, sticky="w")
        r += 1

        self.generate_button = ttk.Button(gen, text="Generate", command=self.generate_graph)
        self.generate_button.grid(row=r, column=0, sticky="w", pady=(8,0))
        r += 1

        self.mass_generate_button = ttk.Button(gen, text="Mass Generate and Export", command=self.mass_generate_and_export)
        self.mass_generate_button.grid(row=r, column=0, sticky="w", pady=(4,0))
        ttk.Combobox(
            gen,
            textvariable=self.mass_export_format_var,
            values=[".csv", ".lad", ".grf"],
            state="readonly",
            width=6
        ).grid(row=r, column=1, sticky="w", padx=(8, 0), pady=(4,0))
        ttk.Label(
            gen,
            text="For 10k+ nodes. Skips rendering and writes straight to disk.",
            wraplength=220,
            foreground="#b45309"
        ).grid(row=r, column=2, columnspan=2, sticky="w", pady=(4,0), padx=(12,0))
        r += 1

        self.abort_generation_button = ttk.Button(gen, text="Abort Generation", command=self.abort_generation)
        self.abort_generation_button.grid(row=r, column=0, sticky="w", pady=(2,0))
        r += 1

        self.mass_timer_var = tk.StringVar(value="")
        self.mass_timer_label = ttk.Label(
            gen,
            textvariable=self.mass_timer_var,
            foreground="#0f172a",
            justify="left",
            anchor="w",
        )
        self.mass_timer_label.grid(row=r, column=0, columnspan=4, sticky="w", pady=(8, 0))
        r += 1
        self.mass_nodes_progress_label = ttk.Label(
            gen,
            textvariable=self.mass_nodes_progress_var,
            foreground="#0369a1",
            justify="left",
            anchor="w",
            wraplength=800,
        )
        self.mass_nodes_progress_label.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(4,0))
        r += 1
        self.mass_nodes_progress_bar = ttk.Progressbar(gen, orient="horizontal", mode="determinate")
        self.mass_nodes_progress_bar.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(2, 4))
        r += 1

        self.mass_edges_progress_label = ttk.Label(
            gen,
            textvariable=self.mass_edges_progress_var,
            foreground="#0369a1",
            justify="left",
            anchor="w",
            wraplength=800,
        )
        self.mass_edges_progress_label.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(4,0))
        r += 1
        self.mass_edges_progress_bar = ttk.Progressbar(gen, orient="horizontal", mode="determinate")
        self.mass_edges_progress_bar.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(2, 8))
        r += 1
        self._hide_mass_progress()
        generate_help_text = (
            "Generate tab tips:\n"
            "- Choose a graph type; N sets the size except for Grid, which uses the rows/cols fields.\n"
            "- Use p or k neighbors (Ring) to control density.\n"
            "- Weight min/max define the random range if graph is weighted.\n"
            "- Disable Render edges for very dense graphs to keep the program responsive. (Edges will still export in CSV)\n"
            "- Generated graphs guarantee every node is part of one graph."
        )
        ttk.Label(gen, text=generate_help_text, wraplength=320, justify="left", foreground="#475569").grid(
            row=r, column=0, columnspan=3, sticky="nw", pady=(8, 0)
        )

        # --- Export tab ---
        export = ttk.Frame(right)
        export.columnconfigure(0, weight=1)
        self.header_style_var = tk.StringVar(value='long')
        self.include_weight_var = tk.BooleanVar(value=True)
        self.start_label_var = tk.StringVar(value='')
        self.target_label_var = tk.StringVar(value='')

        d_frame = ttk.LabelFrame(export, text="Dijkstra (.csv)")
        d_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        d_frame.columnconfigure(1, weight=1)
        rr = 0
        ttk.Label(d_frame, text="Header example:").grid(row=rr, column=0, sticky="w", pady=(2,2))
        ttk.Label(d_frame, text='start = X, target = Y\nsource,target,weight', justify="left", foreground="#475569").grid(row=rr, column=1, columnspan=2, sticky="w")
        rr += 1
        ttk.Label(d_frame, text="(Optional) start label:").grid(row=rr, column=0, sticky="w")
        ttk.Entry(d_frame, textvariable=self.start_label_var, width=12).grid(row=rr, column=1, sticky="w")
        rr += 1
        ttk.Label(d_frame, text="(Optional) target label:").grid(row=rr, column=0, sticky="w")
        ttk.Entry(d_frame, textvariable=self.target_label_var, width=12).grid(row=rr, column=1, sticky="w")
        rr += 1
        ttk.Button(d_frame, text="Export CSV", command=self.export_csv).grid(row=rr, column=0, sticky="w", pady=(6,0))

        glasgow_frame = ttk.LabelFrame(export, text="Glasgow (.lad)")
        glasgow_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(4,4))
        ttk.Label(glasgow_frame, text="Exports to the LAD adjacency format used by the Glasgow Subgraph Solver. Nodes are reindexed from 0..N-1.", wraplength=360, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Button(glasgow_frame, text="Export LAD", command=self.export_glasgow).grid(row=1, column=0, sticky="w", pady=(6,0))

        vf3_frame = ttk.LabelFrame(export, text="VF3 (.grf)")
        vf3_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(4,8))
        ttk.Label(vf3_frame, text="Creates a .grf file compatible with VF3/VF2 matchers (node labels default to 1).", wraplength=360, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Button(vf3_frame, text="Export GRF", command=self.export_vf3).grid(row=1, column=0, sticky="w", pady=(6,0))

        # --- Import tab ---
        import_tab = ttk.Frame(right)
        import_tab.columnconfigure(0, weight=1)
        self.import_status_csv = tk.StringVar(value="Select a CSV containing (source, target) or (source,target,weight)")
        self.import_status_lad = tk.StringVar(value="Select a .lad file.")
        self.import_status_grf = tk.StringVar(value="Select a .grf file.")
        self.import_status_var = self.import_status_csv

        csv_frame = ttk.LabelFrame(import_tab, text="Dijkstra (.csv)")
        csv_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8,4))
        ttk.Label(csv_frame, textvariable=self.import_status_csv, wraplength=360, justify="left", foreground="#475569").grid(row=0, column=0, sticky="w")
        ttk.Button(csv_frame, text="Import CSV...", command=self.import_csv).grid(row=1, column=0, sticky="w", pady=(8,0))

        lad_frame = ttk.LabelFrame(import_tab, text="Glasgow (.lad)")
        lad_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(4,4))
        ttk.Label(lad_frame, textvariable=self.import_status_lad, wraplength=360, justify="left", foreground="#475569").grid(row=0, column=0, sticky="w")
        ttk.Button(lad_frame, text="Import LAD...", command=self.import_glasgow).grid(row=1, column=0, sticky="w", pady=(8,0))

        grf_frame = ttk.LabelFrame(import_tab, text="VF3 (.grf)")
        grf_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(4,8))
        ttk.Label(grf_frame, textvariable=self.import_status_grf, wraplength=360, justify="left", foreground="#475569").grid(row=0, column=0, sticky="w")
        ttk.Button(grf_frame, text="Import GRF...", command=self.import_vf3).grid(row=1, column=0, sticky="w", pady=(8,0))

        # Add panes
        container.add(left, weight=3)
        container.add(right, weight=1)

        right.add(manual, text="Manual")
        right.add(gen, text="Generate")
        right.add(export, text="Export")
        right.add(import_tab, text="Import")
        self._update_action_states()
        self._update_generate_option_states()
        self._update_estimated_edges()
        self._update_generation_controls()

    def _bind_canvas_events(self):
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<ButtonPress-2>", self.on_middle_press)
        self.canvas.bind("<B2-Motion>", self.on_middle_drag)
        self.canvas.bind("<ButtonPress-3>", self.on_middle_press)
        self.canvas.bind("<B3-Motion>", self.on_middle_drag)
        self.canvas.bind("<Button-2>", self.on_canvas_right_click)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel_zoom)
        self.canvas.bind("<Button-4>", self.on_mousewheel_zoom)
        self.canvas.bind("<Button-5>", self.on_mousewheel_zoom)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Leave>", lambda e: self._request_tooltip_hide(force=True))

    def _register_generate_widget(self, group, widget, kind='input'):
        if group not in self._generate_option_widgets:
            self._generate_option_widgets[group] = []
        info = {'widget': widget, 'kind': kind}
        if kind == 'label':
            normal_fg = widget.cget('foreground')
            if not normal_fg:
                normal_fg = "#0f172a"
            info['normal_fg'] = normal_fg
        self._generate_option_widgets[group].append(info)

    def _on_gen_type_change(self, *args):
        self._update_generate_option_states()
        self._update_estimated_edges()

    def _on_generate_param_change(self, *args):
        self._update_estimated_edges()

    def _set_option_widget_state(self, widget_info, enabled):
        widget = widget_info['widget']
        kind = widget_info.get('kind', 'input')
        if kind == 'label':
            normal_fg = widget_info.get('normal_fg', "#0f172a")
            widget.configure(foreground=normal_fg if enabled else self._disabled_label_color)
        else:
            try:
                if enabled:
                    widget.state(['!disabled'])
                else:
                    widget.state(['disabled'])
            except tk.TclError:
                widget.configure(state='normal' if enabled else 'disabled')

    def _update_generate_option_states(self):
        if not hasattr(self, 'gen_type_var'):
            return
        current = self.gen_type_var.get()
        for group, widgets in self._generate_option_widgets.items():
            enabled = (current == group)
            for info in widgets:
                self._set_option_widget_state(info, enabled)

    def _update_estimated_edges(self):
        if not hasattr(self, 'estimated_edges_var'):
            return
        try:
            N = int(float(self.gen_nodes_var.get()))
            p = float(self.gnp_p_var.get())
            k = int(float(self.k_neighbors_var.get()))
            rows = int(float(self.grid_rows_var.get()))
            cols = int(float(self.grid_cols_var.get()))
        except (tk.TclError, ValueError):
            self.estimated_edges_var.set("Estimated edges: ~?")
            return
        gtype = getattr(self, 'gen_type_var', None)
        directed = getattr(self, 'directed_var', None)
        if gtype is None or directed is None:
            return
        estimated = self._compute_estimated_edges(
            N,
            gtype.get(),
            directed.get(),
            p,
            k,
            rows,
            cols
        )
        self.estimated_edges_var.set(f"Estimated edges: ~{estimated:,}")

    def _compute_estimated_edges(self, N, gtype, directed, p, k, rows, cols):
        try:
            N = max(0, int(N))
        except (TypeError, ValueError):
            N = 0
        try:
            rows = max(1, int(rows))
        except (TypeError, ValueError):
            rows = 1
        try:
            cols = max(1, int(cols))
        except (TypeError, ValueError):
            cols = 1
        try:
            k = max(0, int(k))
        except (TypeError, ValueError):
            k = 0
        try:
            p = float(p)
        except (TypeError, ValueError):
            p = 0.0
        p = max(0.0, min(1.0, p))
        estimated_edges = 0
        if gtype == 'random':
            estimated_edges = N * max(0, N - 1) * p
            if not directed:
                estimated_edges /= 2
        elif gtype == 'grid':
            estimated_edges = rows * max(0, cols - 1) + cols * max(0, rows - 1)
        elif gtype == 'ring':
            estimated_edges = N * k
            if not directed:
                estimated_edges /= 2
        elif gtype == 'path':
            estimated_edges = max(0, N - 1)
        elif gtype == 'star':
            estimated_edges = max(0, N - 1)
        return max(0, int(round(estimated_edges)))

    ############################################################
    # Tooltip helpers
    ############################################################
    def _show_node_tooltip(self, label, screen_x, screen_y):
        content = self._build_node_tooltip_content(label)
        if not content:
            self._hide_node_tooltip()
            return
        self._cancel_tooltip_hide()
        same_node = self.tooltip_node == label if self.tooltip_node else False
        tooltip_visible = self.node_tooltip and self.node_tooltip.winfo_exists() and self.node_tooltip.winfo_ismapped()
        self._ensure_tooltip_window()
        self.tooltip_data = content
        self.tooltip_has_weights = content['has_weights'] and self.graph.weighted
        if not self.tooltip_has_weights and self.tooltip_sort_var.get() == 'weight':
            self.tooltip_sort_var.set('label')
        self._update_tooltip_sort_display()
        self.tooltip_title_label.configure(text=content['title'])
        self.node_tooltip.deiconify()
        if not (same_node and tooltip_visible):
            x = int(screen_x + 12)
            y = int(screen_y + 12)
            self.node_tooltip.geometry(f"+{x}+{y}")
        self.tooltip_node = label
        self._render_tooltip_content()
        self._cancel_tooltip_hide()

    def _hide_node_tooltip(self):
        self._cancel_tooltip_hide()
        self.tooltip_node = None
        self.tooltip_data = None
        self.tooltip_has_weights = False
        if self.node_tooltip:
            self.node_tooltip.withdraw()

    def _request_tooltip_hide(self, force=False):
        if not self.tooltip_node:
            return
        if force and not self._pointer_over_tooltip():
            if self._pointer_far_from_canvas(margin=32):
                self._hide_node_tooltip()
                return
        if self._pointer_over_tooltip() or self._pointer_over_current_node():
            return
        self._cancel_tooltip_hide()
        self.tooltip_hide_job = self.after(self.tooltip_hide_delay_ms, self._hide_tooltip_if_inactive)

    def _cancel_tooltip_hide(self):
        if self.tooltip_hide_job:
            self.after_cancel(self.tooltip_hide_job)
            self.tooltip_hide_job = None

    def _hide_tooltip_if_inactive(self):
        self.tooltip_hide_job = None
        if self._pointer_over_tooltip() or self._pointer_over_current_node():
            return
        self._hide_node_tooltip()

    def _tooltip_visible(self):
        return bool(self.node_tooltip and self.node_tooltip.winfo_exists() and self.node_tooltip.winfo_ismapped())

    def _scroll_tooltip(self, event):
        if not self._tooltip_visible() or not self.tooltip_text:
            return False
        delta = getattr(event, 'delta', 0)
        steps = 0
        if delta != 0:
            steps = -1 if delta > 0 else 1
        else:
            num = getattr(event, 'num', None)
            if num == 4:
                steps = -1
            elif num == 5:
                steps = 1
        if steps == 0:
            return False
        self._cancel_tooltip_hide()
        self.tooltip_text.yview_scroll(steps, "units")
        return True

    def _on_tooltip_scroll(self, event):
        if self._scroll_tooltip(event):
            return "break"

    def _pointer_over_tooltip(self):
        if not self._tooltip_visible():
            return False
        try:
            px = self.winfo_pointerx()
            py = self.winfo_pointery()
            return self.node_tooltip.winfo_containing(px, py) is not None
        except tk.TclError:
            return False

    def _pointer_over_current_node(self):
        if not self.tooltip_node:
            return False
        cx, cy = self._pointer_canvas_coords()
        if cx is None:
            return False
        pad = GraphBuilderApp.NODE_RADIUS * max(1.0, self.zoom_level) + 24
        item = self._find_node_item_at(cx, cy, pad=pad)
        if not item:
            return False
        return self.item_to_label.get(item) == self.tooltip_node

    def _pointer_canvas_coords(self):
        try:
            px = self.winfo_pointerx() - self.canvas.winfo_rootx()
            py = self.winfo_pointery() - self.canvas.winfo_rooty()
        except tk.TclError:
            return None, None
        try:
            cx = self.canvas.canvasx(px)
            cy = self.canvas.canvasy(py)
            return cx, cy
        except tk.TclError:
            return None, None

    def _pointer_far_from_canvas(self, margin=24):
        try:
            px = self.winfo_pointerx()
            py = self.winfo_pointery()
            left = self.canvas.winfo_rootx()
            top = self.canvas.winfo_rooty()
            right = left + self.canvas.winfo_width()
            bottom = top + self.canvas.winfo_height()
        except tk.TclError:
            return True
        return px < left - margin or px > right + margin or py < top - margin or py > bottom + margin

    def _ensure_tooltip_window(self):
        if self.node_tooltip is not None:
            return
        tooltip = tk.Toplevel(self)
        tooltip.withdraw()
        tooltip.overrideredirect(True)
        try:
            tooltip.attributes("-topmost", True)
        except tk.TclError:
            pass
        container = ttk.Frame(tooltip, padding=8)
        container.pack(fill='both', expand=True)
        title = ttk.Label(container, text="", font=("Segoe UI", 10, "bold"))
        title.grid(row=0, column=0, columnspan=2, sticky="w")
        instruction = ttk.Label(
            container,
            text="Right-click any node to toggle sorting.",
            foreground="#475569",
            wraplength=220,
            justify="left"
        )
        instruction.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 4))
        sort_frame = ttk.Frame(container)
        sort_frame.grid(row=2, column=0, sticky="w")
        ttk.Label(sort_frame, text="Sort by:", foreground="#334155").grid(row=0, column=0, sticky="w", padx=(0, 8))
        label_option = tk.Label(sort_frame, text="Label", font=self.tooltip_sort_font, cursor="hand2", foreground="#0f172a")
        label_option.grid(row=0, column=1, sticky="w")
        label_option.bind("<Button-1>", lambda e: self.tooltip_sort_var.set('label'))
        weight_option = tk.Label(sort_frame, text="Weight", font=self.tooltip_sort_font, cursor="hand2", foreground="#475569")
        weight_option.grid(row=0, column=2, sticky="w", padx=(12, 0))
        weight_option.bind("<Button-1>", lambda e: self.tooltip_sort_var.set('weight'))
        text_widget = tk.Text(container, width=20, height=14, wrap='none', state='disabled',
                              background="#f8fafc", foreground="#0f172a", relief='flat',
                              font=self.tooltip_font)
        scroll = ttk.Scrollbar(container, orient='vertical', command=text_widget.yview)
        text_widget.configure(yscrollcommand=scroll.set)
        text_widget.grid(row=3, column=0, sticky="nsew")
        scroll.grid(row=3, column=1, sticky="ns")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)
        tooltip.bind("<Enter>", lambda e: self._cancel_tooltip_hide())
        tooltip.bind("<Leave>", lambda e: self._request_tooltip_hide())
        tooltip.bind("<MouseWheel>", self._on_tooltip_scroll)
        tooltip.bind("<Button-4>", self._on_tooltip_scroll)
        tooltip.bind("<Button-5>", self._on_tooltip_scroll)
        tooltip.bind("<Button-2>", self._on_tooltip_right_click)
        tooltip.bind("<Button-3>", self._on_tooltip_right_click)
        text_widget.bind("<Button-2>", self._on_tooltip_right_click)
        text_widget.bind("<Button-3>", self._on_tooltip_right_click)
        self.node_tooltip = tooltip
        self.tooltip_title_label = title
        self.tooltip_text = text_widget
        self.tooltip_instruction_label = instruction
        self.tooltip_sort_label_label = label_option
        self.tooltip_sort_label_weight = weight_option
        self._update_tooltip_sort_display()

    def _render_tooltip_content(self, *_):
        if not (self.tooltip_text and self.tooltip_data and self.node_tooltip and self.node_tooltip.winfo_exists()):
            return
        sections = []
        sort_mode = self.tooltip_sort_var.get()
        for section in self.tooltip_data['sections']:
            edges = list(section['edges'])
            if sort_mode == 'weight' and self.tooltip_has_weights:
                edges.sort(key=lambda e: (self._weight_sort_value(e['weight']), self._natural_key(e['neighbor'])))
            else:
                edges.sort(key=lambda e: self._natural_key(e['neighbor']))
            sections.append((section['title'], edges))
        lines = [self.tooltip_data['title']]
        connection_lines = []
        for title, edges in sections:
            lines.append(title)
            if not edges:
                lines.append("  (none)")
                continue
            for edge in edges:
                desc = f"{edge['prefix']} {edge['neighbor']}"
                if edge['weight'] is not None and self.graph.weighted:
                    desc += f" (w={edge['weight']})"
                formatted = f"  {desc}"
                lines.append(formatted)
                connection_lines.append(formatted.strip())
        if self.tooltip_has_weights:
            lines.append("")
            lines.append("Right-click anywhere in this tooltip to toggle between label and weight sorting.")
        text = "\n".join(lines)
        self.tooltip_text.configure(state='normal')
        self.tooltip_text.delete("1.0", "end")
        self.tooltip_text.insert("end", text)
        self.tooltip_text.configure(state='disabled')
        self._resize_tooltip_width(lines, connection_lines)

    def _on_tooltip_sort_change(self, *_):
        self._update_tooltip_sort_display()
        self._render_tooltip_content()

    def _toggle_tooltip_sort(self):
        if not self.tooltip_has_weights:
            self.tooltip_sort_var.set('label')
            return
        current = self.tooltip_sort_var.get()
        next_mode = 'weight' if current == 'label' else 'label'
        self.tooltip_sort_var.set(next_mode)

    def _update_tooltip_sort_display(self):
        if not (self.tooltip_sort_label_label and self.tooltip_sort_label_weight):
            return
        has_weights = self.tooltip_has_weights and self.graph.weighted
        sort_mode = self.tooltip_sort_var.get()
        label_font = self.tooltip_sort_font_bold if sort_mode == 'label' else self.tooltip_sort_font
        self.tooltip_sort_label_label.configure(
            font=label_font,
            foreground="#0f172a" if sort_mode == 'label' else "#475569"
        )
        if has_weights:
            weight_font = self.tooltip_sort_font_bold if sort_mode == 'weight' else self.tooltip_sort_font
            weight_color = "#0f172a" if sort_mode == 'weight' else "#475569"
            self.tooltip_sort_label_weight.configure(font=weight_font, foreground=weight_color)
        else:
            self.tooltip_sort_label_weight.configure(
                font=self.tooltip_sort_font,
                foreground="#94a3b8",
                text="Weight (n/a)"
            )
            if sort_mode == 'weight':
                self.tooltip_sort_var.set('label')
                return
        if has_weights:
            self.tooltip_sort_label_weight.configure(text="Weight")

    def _on_tooltip_right_click(self, event):
        self._cancel_tooltip_hide()
        self._toggle_tooltip_sort()
        return "break"

    def _resize_tooltip_width(self, all_lines, connection_lines):
        if not (self.tooltip_text and self.tooltip_font):
            return
        sort_labels = ["Sort by:", "Label", "Weight"]
        candidates = (connection_lines or all_lines) + sort_labels
        max_pixels = 0
        for line in candidates:
            try:
                width_px = self.tooltip_font.measure(line.rstrip() or " ")
            except tk.TclError:
                width_px = 0
            if width_px > max_pixels:
                max_pixels = width_px
        char_px = self.tooltip_font.measure("0") or 7
        target_width_chars = max(12, int((max_pixels / char_px) + 3))
        self.tooltip_text.configure(width=target_width_chars)

    def _weight_sort_value(self, weight):
        if weight is None:
            return float('inf')
        try:
            return float(weight)
        except (TypeError, ValueError):
            return float('inf')

    def _natural_key(self, value):
        parts = re.split(r'(\d+)', value)
        key = []
        for part in parts:
            if part.isdigit():
                key.append(int(part))
            else:
                key.append(part)
        return tuple(key)

    def _build_node_tooltip_content(self, label):
        if label not in self.graph.nodes:
            return None
        content = {'title': f"Node: {label}", 'sections': [], 'has_weights': False}
        weighted = self.graph.weighted
        if self.graph.directed:
            outgoing = []
            incoming = []
            for edge in self.graph.edges:
                w = edge.get('w')
                if weighted and w is not None:
                    content['has_weights'] = True
                if edge['u'] == label:
                    outgoing.append({'neighbor': edge['v'], 'weight': w, 'prefix': '->'})
                if edge['v'] == label:
                    incoming.append({'neighbor': edge['u'], 'weight': w, 'prefix': '<-'})
            content['sections'].append({'title': "Outgoing:", 'edges': outgoing})
            content['sections'].append({'title': "Incoming:", 'edges': incoming})
        else:
            neighbors = []
            for edge in self.graph.edges:
                w = edge.get('w')
                if weighted and w is not None:
                    content['has_weights'] = True
                if edge['u'] == label:
                    neighbors.append({'neighbor': edge['v'], 'weight': w, 'prefix': '--'})
                elif edge['v'] == label:
                    neighbors.append({'neighbor': edge['u'], 'weight': w, 'prefix': '--'})
            content['sections'].append({'title': "Connections:", 'edges': neighbors})
        return content

    def _build_adjacency_sets(self, model=None):
        graph = model or self.graph
        labels = sorted(graph.labels(), key=self._natural_key)
        index_map = {label: idx for idx, label in enumerate(labels)}
        adjacency = [set() for _ in labels]
        for edge in graph.edges:
            u = edge['u']
            v = edge['v']
            if u not in index_map or v not in index_map:
                continue
            adjacency[index_map[u]].add(index_map[v])
            if not graph.directed:
                adjacency[index_map[v]].add(index_map[u])
        return labels, index_map, adjacency

    def _set_import_status(self, var, message):
        if var is not None:
            var.set(message)

    def _show_mass_progress(self, total_nodes, total_edges):
        if not self.mass_nodes_progress_label or not self.mass_nodes_progress_bar:
            return
        total = max(1, int(total_nodes))
        edges_total = max(1, int(total_edges))
        self.mass_nodes_progress_bar.configure(maximum=total, value=0)
        self.mass_edges_progress_bar.configure(maximum=edges_total, value=0)
        self.mass_nodes_progress_var.set(f"Nodes written: 0 / {total:,} | Initializing...")
        self.mass_edges_progress_var.set(f"Edges written: 0 / {edges_total:,} | Pending...")
        self.mass_timer_start = time.time()
        self._update_generation_timer(force=True)
        self.mass_nodes_progress_label.grid()
        self.mass_nodes_progress_bar.grid()
        self.mass_edges_progress_label.grid()
        self.mass_edges_progress_bar.grid()
        self.mass_timer_label.grid()
        self.update_idletasks()

    def _update_mass_progress(self, stage, done, total):
        if not self.mass_nodes_progress_label or not self.mass_nodes_progress_bar:
            return
        total = max(1, int(total))
        done = max(0, min(int(done), total))
        if stage == "edges":
            self.mass_edges_progress_bar.configure(maximum=total, value=done)
            suffix = " | Building edges..."
            self.mass_edges_progress_var.set(f"Edges written: {done:,} / {total:,}{suffix}")
        else:
            self.mass_nodes_progress_bar.configure(maximum=total, value=done)
            suffix = " | Generating nodes..."
            self.mass_nodes_progress_var.set(f"Nodes written: {done:,} / {total:,}{suffix}")
        self._update_generation_timer()
        self.update_idletasks()

    def _hide_mass_progress(self):
        if self.mass_nodes_progress_label:
            self.mass_nodes_progress_label.grid_remove()
        if self.mass_nodes_progress_bar:
            self.mass_nodes_progress_bar.grid_remove()
        if self.mass_edges_progress_label:
            self.mass_edges_progress_label.grid_remove()
        if self.mass_edges_progress_bar:
            self.mass_edges_progress_bar.grid_remove()
        if getattr(self, 'mass_timer_label', None):
            self.mass_timer_label.grid_remove()
        self.mass_nodes_progress_var.set("")
        self.mass_edges_progress_var.set("")
        self.mass_timer_var.set("")
        if getattr(self, '_mass_timer_job', None):
            self.after_cancel(self._mass_timer_job)
            self._mass_timer_job = None
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def _update_generation_timer(self, force=False):
        if not getattr(self, 'mass_timer_label', None):
            return
        if not getattr(self, 'mass_timer_start', None):
            return
        elapsed = time.time() - self.mass_timer_start if self.mass_timer_start else 0
        minutes = int(elapsed) // 60
        seconds = int(elapsed) % 60
        self.mass_timer_var.set(f"Elapsed: {minutes:02d}m {seconds:02d}s")
        if force:
            self.update_idletasks()
        self._mass_timer_job = self.after(1000, self._update_generation_timer)

    def _update_generation_controls(self):
        if getattr(self, 'abort_generation_button', None):
            if self._generation_in_progress or self._mass_generation_active:
                self.abort_generation_button.state(['!disabled'])
            else:
                self.abort_generation_button.state(['disabled'])
        if getattr(self, 'generate_button', None):
            if self._generation_in_progress or self._mass_generation_active:
                self.generate_button.state(['disabled'])
            else:
                self.generate_button.state(['!disabled'])
        if getattr(self, 'mass_generate_button', None):
            if self._mass_generation_active or self._generation_in_progress:
                self.mass_generate_button.state(['disabled'])
            else:
                self.mass_generate_button.state(['!disabled'])

    def abort_generation(self):
        aborted = False
        if self._generation_in_progress and self._generation_abort_event and not self._generation_abort_event.is_set():
            self._generation_abort_event.set()
            aborted = True
        if self._mass_generation_active and self._mass_job_config:
            evt = self._mass_job_config.get('abort_event')
            if evt and not evt.is_set():
                evt.set()
                aborted = True
        if aborted:
            self.status("Abort requested. Finishing current step...")
        else:
            self.status("No generation in progress to abort.")
        self._update_generation_controls()

    def _start_mass_export_job(self, job):
        if self._mass_generation_active:
            messagebox.showwarning("Mass export", "Another mass generation is already running.")
            return False
        self._mass_generation_active = True
        self._mass_job_config = job
        self._mass_progress_queue = queue.Queue()
        abort_event = threading.Event()
        job['abort_event'] = abort_event
        self._update_generation_controls()

        def progress_update(stage, done, total):
            if not self._mass_generation_active or not self._mass_progress_queue:
                return
            self._mass_progress_queue.put(('progress', stage, done, total))

        def worker():
            try:
                model, next_index_value = self._generate_model_data(
                    job['N'],
                    job['gtype'],
                    job['directed'],
                    job['weighted'],
                    job['wmin'],
                    job['wmax'],
                    job['p'],
                    job['k'],
                    job['rows'],
                    job['cols'],
                    job['prefix'],
                    job['start_index'],
                    progress_callback=progress_update,
                    estimated_edges=job['edge_estimate'],
                    abort_event=abort_event,
                )
                if abort_event.is_set():
                    raise GenerationAborted("Aborted before export.")
                job['exporter'](model, job['path'])
                if abort_event.is_set():
                    raise GenerationAborted("Aborted during export.")
                self._mass_progress_queue.put(('done', next_index_value))
            except GenerationAborted as exc:
                self._mass_progress_queue.put(('aborted', str(exc)))
            except Exception as exc:
                self._mass_progress_queue.put(('error', str(exc)))

        self._mass_worker_thread = threading.Thread(target=worker, daemon=True)
        self._mass_worker_thread.start()
        self._poll_mass_progress()
        return True

    def _poll_mass_progress(self):
        if not self._mass_generation_active or not self._mass_progress_queue:
            return
        try:
            while True:
                msg = self._mass_progress_queue.get_nowait()
                if not msg:
                    continue
                kind = msg[0]
                if kind == 'progress':
                    _, stage, done, total = msg
                    self._update_mass_progress(stage, done, total)
                elif kind == 'done':
                    _, next_index_value = msg
                    self._complete_mass_export(success=True, next_index=next_index_value)
                    return
                elif kind == 'error':
                    _, error_message = msg
                    self._complete_mass_export(success=False, error=error_message)
                    return
                elif kind == 'aborted':
                    _, reason = msg
                    self._complete_mass_export(success=False, error=reason, aborted=True)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll_mass_progress)

    def _complete_mass_export(self, success, next_index=None, error=None, aborted=False):
        job = self._mass_job_config
        self._mass_generation_active = False
        self._mass_worker_thread = None
        self._mass_job_config = None
        self._mass_progress_queue = None
        self._hide_mass_progress()
        self._update_generation_controls()
        if not job:
            return
        path = job.get('path', '')
        if success:
            if next_index is not None:
                self.next_index.set(next_index)
            messagebox.showinfo("Mass export complete", f"Graph written to:\n{path}")
            self.status(f"Mass export complete: {path}")
        elif aborted:
            messagebox.showinfo("Mass export", "Generation aborted.")
            self.status("Mass export aborted.")
        else:
            messagebox.showerror("Mass export failed", f"Operation aborted:\n{error}")
            self.status("Mass export failed.")

    def status(self, message):
        """Update the Manual tab status label (fallback to console if unavailable)."""
        text = str(message) if message is not None else ""
        if hasattr(self, "status_var") and self.status_var is not None:
            self.status_var.set(text)
        else:
            print(f"STATUS: {text}")

    def _autofill_start_target_defaults(self):
        labels = sorted(self.graph.labels(), key=self._natural_key)
        if not labels:
            return
        current_start = self.start_label_var.get().strip()
        current_target = self.target_label_var.get().strip()
        if not current_start:
            self.start_label_var.set(labels[0])
        if not current_target:
            self.target_label_var.set(labels[-1])

    def _load_imported_graph(self, node_labels, edges, weighted, directed, start_label='', target_label=''):
        labels = sorted(set(node_labels), key=self._natural_key)
        if not labels:
            raise ValueError("Import failed: no nodes detected.")
        self.clear_graph()
        self.directed_var.set(directed)
        self.weighted_var.set(weighted)
        self.graph.directed = directed
        self.graph.weighted = weighted

        x_min, x_max = 100, 3800
        y_min, y_max = 100, 2800
        rng = random.Random()
        for label in labels:
            x = rng.uniform(x_min, x_max)
            y = rng.uniform(y_min, y_max)
            self.graph.add_node(label, x, y)

        skipped = 0
        for (u, v, w) in edges:
            if u not in self.graph.nodes or v not in self.graph.nodes:
                continue
            weight_val = w if (weighted and w is not None) else 1
            added = self.graph.add_edge(u, v, weight_val)
            if not added:
                skipped += 1

        if start_label:
            self.start_label_var.set(start_label)
        else:
            self.start_label_var.set('')
        if target_label:
            self.target_label_var.set(target_label)
        else:
            self.target_label_var.set('')
        self.next_index.set(len(self.graph.nodes) + 1)

        self.redraw_all(draw_edges=self.render_edges_var.get(), preserve_view=False)
        self._fit_view_to_contents()
        self._autofill_start_target_defaults()
        return skipped

    def _parse_metadata_line(self, line):
        metadata = {}
        for token in line.strip().split():
            if '=' in token:
                key, value = token.split('=', 1)
                metadata[key.strip().lower()] = value.strip()
        return metadata

    def _find_header_index(self, header, names):
        for idx, name in enumerate(header):
            if name in names:
                return idx
        return None
    ############################################################
    # Canvas interactions
    ############################################################
    def on_middle_press(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def on_middle_drag(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._remember_view_state()

    def on_canvas_click(self, event):
        # translate to canvas coords
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        ctrl_down = self._ctrl_held(event)

        if self.add_nodes_mode.get():
            # Create with next label
            label = f"{self.label_prefix.get()}{self.next_index.get()}"
            self.next_index.set(self.next_index.get() + 1)
            world_x, world_y = self._canvas_to_world(cx, cy)
            self.graph.add_node(label, world_x, world_y)
            self._draw_node(label)
            self._autofill_start_target_defaults()
            self.status(f"Added node {label}")
            return

        item = self._find_node_item_at(cx, cy)
        if item is not None:
            label = self.item_to_label.get(item)
            if label:
                self._toggle_node_selection(label, ctrl_down)
            return

        edge_item = self._find_edge_item_at(cx, cy)
        if edge_item is not None:
            edge_id = self.item_to_edge.get(edge_item)
            if edge_id is not None:
                self._toggle_edge_selection(edge_id, ctrl_down)
            self._request_tooltip_hide()
            return

        self._request_tooltip_hide()
        if not ctrl_down:
            self._clear_selection()

    def on_canvas_right_click(self, event):
        label = self._label_at_canvas_point(event)
        if not label:
            return
        self._toggle_tooltip_sort()
        self._show_node_tooltip(label, event.x_root, event.y_root)
        self._cancel_tooltip_hide()
        return "break"

    def _label_at_canvas_point(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        item = self._find_node_item_at(cx, cy)
        if item is None:
            return None
        return self.item_to_label.get(item)

    def on_canvas_motion(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        item = self._find_node_item_at(cx, cy)
        if item is not None:
            label = self.item_to_label.get(item)
            if label:
                self._show_node_tooltip(label, event.x_root, event.y_root)
                self._cancel_tooltip_hide()
                return
        self._hide_node_tooltip()

    def _find_node_item_at(self, x, y, pad=1):
        # Return topmost node oval or text at (x,y)
        pad = max(1, int(pad))
        items = self.canvas.find_overlapping(x-pad, y-pad, x+pad, y+pad)
        for it in reversed(items):
            if it in self.item_to_label:
                return it
        return None

    def _find_edge_item_at(self, x, y):
        items = self.canvas.find_overlapping(x-3, y-3, x+3, y+3)
        for it in reversed(items):
            if it in self.item_to_edge:
                return it
        return None

    def _ctrl_held(self, event):
        state = getattr(event, 'state', 0)
        return bool(state & 0x0004 or state & 0x0008 or state & 0x000C)

    def _toggle_node_selection(self, label, ctrl_down):
        if label in self.selected_nodes:
            self._unhighlight_node(label)
            self.selected_nodes.remove(label)
            self._update_selection_status()
            return
        if not ctrl_down:
            while len(self.selected_nodes) >= 2:
                oldest = self.selected_nodes.pop(0)
                self._unhighlight_node(oldest)
        self.selected_nodes.append(label)
        self._highlight_node(label)
        self._update_selection_status()

    def _toggle_edge_selection(self, edge_id, ctrl_down):
        if edge_id in self.selected_edges:
            self.selected_edges.remove(edge_id)
            self._unhighlight_edge(edge_id)
            self._update_selection_status()
            return
        if not ctrl_down and self.selected_edges:
            while self.selected_edges:
                oldest = self.selected_edges.pop(0)
                self._unhighlight_edge(oldest)
        self.selected_edges.append(edge_id)
        self._highlight_edge(edge_id)
        self._update_selection_status()

    def _update_selection_status(self):
        parts = []
        if self.selected_nodes:
            parts.append(f"Nodes: {', '.join(self.selected_nodes[-5:])}" if len(self.selected_nodes) > 5 else f"Nodes: {', '.join(self.selected_nodes)}")
        if self.selected_edges:
            edge_labels = []
            for edge_id in self.selected_edges[-5:]:
                edge = self.graph.get_edge(edge_id)
                if edge:
                    edge_labels.append(f"{edge['u']}->{edge['v']}")
            if edge_labels:
                parts.append(f"Edges: {', '.join(edge_labels)}")
        if parts:
            self.status(" | ".join(parts))
        else:
            self.status("Ready")
        self._refresh_selection_visuals()
        self._update_action_states()

    def _refresh_selection_visuals(self):
        selected_node_set = set(self.selected_nodes)
        for label, (oval, _) in self.node_items.items():
            fill = "#fde68a" if label in selected_node_set else "#e2e8f0"
            self.canvas.itemconfig(oval, fill=fill)
        selected_edge_set = set(self.selected_edges)
        for edge_id in list(self.edge_items.keys()):
            if edge_id in selected_edge_set:
                self._highlight_edge(edge_id)
            else:
                self._unhighlight_edge(edge_id)

    def _update_action_states(self):
        if self.connect_button:
            if len(self.selected_nodes) == 2:
                self.connect_button.state(['!disabled'])
            else:
                self.connect_button.state(['disabled'])
        if self.edit_weight_button:
            if self.graph.weighted and self.selected_edges and not self.selected_nodes:
                self.edit_weight_button.state(['!disabled'])
            else:
                self.edit_weight_button.state(['disabled'])

    ############################################################
    # View controls and helpers
    ############################################################
    def on_mousewheel_zoom(self, event):
        if self._tooltip_visible():
            if self._scroll_tooltip(event):
                return "break"
        if not self.canvas.find_all():
            return
        delta = getattr(event, 'delta', 0)
        direction = 0
        if delta != 0:
            direction = 1 if delta > 0 else -1
        else:
            num = getattr(event, 'num', None)
            if num in (4, 5):
                direction = 1 if num == 4 else -1
        if direction == 0:
            return
        factor = 1.1 if direction > 0 else 0.9
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self._set_zoom(self.zoom_level * factor, anchor=(cx, cy))
        return "break"

    def _set_zoom(self, target_zoom, anchor=None, update_view_state=True):
        target_zoom = max(self.min_zoom, min(self.max_zoom, target_zoom))
        if abs(target_zoom - self.zoom_level) < 1e-4:
            return
        if anchor is None:
            self.canvas.update_idletasks()
            anchor = (
                self.canvas.canvasx(self.canvas.winfo_width() / 2),
                self.canvas.canvasy(self.canvas.winfo_height() / 2),
            )
        factor = target_zoom / self.zoom_level
        has_content = bool(self.canvas.find_all())
        if has_content:
            self.canvas.scale('all', anchor[0], anchor[1], factor, factor)
        self.zoom_level = target_zoom
        self.zoom_offset_x = factor * self.zoom_offset_x + (1 - factor) * anchor[0]
        self.zoom_offset_y = factor * self.zoom_offset_y + (1 - factor) * anchor[1]
        self._update_scrollregion()
        if update_view_state:
            self._remember_view_state()
            self._restore_view_state()

    def _update_scrollregion(self):
        bbox = self.canvas.bbox('all')
        if bbox:
            pad = 60
            self.canvas.configure(scrollregion=(bbox[0]-pad, bbox[1]-pad, bbox[2]+pad, bbox[3]+pad))
        else:
            self.canvas.configure(scrollregion=(0, 0, 4000, 3000))

    def _remember_view_state(self):
        try:
            self.view_x = self.canvas.xview()[0]
            self.view_y = self.canvas.yview()[0]
        except tk.TclError:
            self.view_x = 0.0
            self.view_y = 0.0

    def _restore_view_state(self):
        try:
            self.canvas.xview_moveto(min(max(self.view_x, 0.0), 1.0))
            self.canvas.yview_moveto(min(max(self.view_y, 0.0), 1.0))
        except tk.TclError:
            pass

    def _center_on_point(self, x, y):
        bbox = self.canvas.bbox('all')
        if not bbox:
            return
        self.canvas.update_idletasks()
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 0 or height <= 0:
            return
        x1, y1, x2, y2 = bbox
        scroll_w = x2 - x1
        scroll_h = y2 - y1
        if scroll_w <= 0 or scroll_h <= 0:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
            self._remember_view_state()
            return
        left = x - width / 2
        top = y - height / 2
        fx = (left - x1) / scroll_w
        fy = (top - y1) / scroll_h
        self.canvas.xview_moveto(min(max(fx, 0.0), 1.0))
        self.canvas.yview_moveto(min(max(fy, 0.0), 1.0))
        self._remember_view_state()

    def _fit_view_to_contents(self):
        bbox = self.canvas.bbox('all')
        if not bbox:
            return
        self.canvas.update_idletasks()
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 0 or height <= 0:
            return
        pad = 80
        content_w = max(1, (bbox[2] - bbox[0]) + pad)
        content_h = max(1, (bbox[3] - bbox[1]) + pad)
        scale_x = width / content_w
        scale_y = height / content_h
        target_zoom = max(self.min_zoom, min(self.max_zoom, min(scale_x, scale_y)))
        center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        self.zoom_level = 1.0
        self.zoom_offset_x = 0.0
        self.zoom_offset_y = 0.0
        self.view_x = 0.0
        self.view_y = 0.0
        self._set_zoom(target_zoom, anchor=center, update_view_state=False)
        self._update_scrollregion()
        bbox = self.canvas.bbox('all')
        if bbox:
            self._center_on_point((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)

    def _reset_viewport(self):
        self.zoom_level = 1.0
        self.zoom_offset_x = 0.0
        self.zoom_offset_y = 0.0
        self.view_x = 0.0
        self.view_y = 0.0
        try:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        except tk.TclError:
            pass
        self.canvas.configure(scrollregion=(0, 0, 4000, 3000))
        self._remember_view_state()

    def _apply_transform_to_canvas(self):
        if not self.canvas.find_all():
            return
        needs_scale = abs(self.zoom_level - 1.0) > 1e-4
        needs_move = abs(self.zoom_offset_x) > 1e-4 or abs(self.zoom_offset_y) > 1e-4
        if not needs_scale and not needs_move:
            return
        if needs_scale:
            self.canvas.scale('all', 0, 0, self.zoom_level, self.zoom_level)
        if needs_move:
            self.canvas.move('all', self.zoom_offset_x, self.zoom_offset_y)

    def _apply_transform_to_items(self, items):
        if not items:
            return
        needs_scale = abs(self.zoom_level - 1.0) > 1e-4
        needs_move = abs(self.zoom_offset_x) > 1e-4 or abs(self.zoom_offset_y) > 1e-4
        if not needs_scale and not needs_move:
            return
        for item in items:
            if not item:
                continue
            if needs_scale:
                self.canvas.scale(item, 0, 0, self.zoom_level, self.zoom_level)
            if needs_move:
                self.canvas.move(item, self.zoom_offset_x, self.zoom_offset_y)

    def _canvas_to_world(self, x, y):
        if abs(self.zoom_level) < 1e-6:
            return x, y
        wx = (x - self.zoom_offset_x) / self.zoom_level
        wy = (y - self.zoom_offset_y) / self.zoom_level
        return wx, wy

    ############################################################
    # Drawing
    ############################################################
    def _draw_node(self, label):
        x, y = self.graph.nodes[label]
        r = GraphBuilderApp.NODE_RADIUS
        oval = self.canvas.create_oval(
            x - r,
            y - r,
            x + r,
            y + r,
            fill="#e2e8f0",
            outline="#334155",
            tags=('node',),
        )
        text = None
        self.node_items[label] = (oval, text)
        self.item_to_label[oval] = label
        if text:
            self.item_to_label[text] = label
        if not self._is_redrawing:
            self._apply_transform_to_items((oval,))
            self._update_scrollregion()

    def _draw_edge(self, edge, draw_arrows=True, draw_weight_label=True):
        if not edge:
            return
        u, v = edge['u'], edge['v']
        w = edge.get('w', 1)
        edge_id = edge['id']
        x1, y1 = self.graph.nodes[u]
        x2, y2 = self.graph.nodes[v]
        # draw line; optional arrowheads/weights are decided by caller
        kwargs = {"fill": "#64748b"}
        if draw_arrows:
            kwargs.update({"arrow": tk.LAST, "arrowshape": (10, 12, 4)})
        line = self.canvas.create_line(x1, y1, x2, y2, tags=('edge',), **kwargs)
        self.canvas.tag_lower(line)
        self.item_to_edge[line] = edge_id
        created_items = [line]
        weight_text = None
        if draw_weight_label:
            # label midpoint
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            weight_value = w if w is not None else 1
            try:
                display = str(int(weight_value)) if float(weight_value).is_integer() else str(weight_value)
            except Exception:
                display = str(weight_value)
            weight_text = self.canvas.create_text(mx, my, text=display,
                                                  font=("Segoe UI", 8), fill="#94a3b8", tags=('edge',))
            created_items.append(weight_text)
            self.item_to_edge[weight_text] = edge_id
        self.edge_items[edge_id] = {'line': line, 'weight': weight_text}
        if not self._is_redrawing:
            self._apply_transform_to_items(created_items)
            self._update_scrollregion()
        if edge_id in self.selected_edges:
            self._highlight_edge(edge_id)

    def _edge_render_flags(self, total_edges=None):
        """
        Decide whether arrowheads and weight labels should be rendered based
        on the current graph size to keep the Canvas responsive.
        """
        if total_edges is None:
            total_edges = len(self.graph.edges)
        draw_arrows = self.directed_var.get() and total_edges <= GraphBuilderApp.ARROW_RENDER_LIMIT
        draw_weights = self.weighted_var.get() and total_edges <= GraphBuilderApp.WEIGHT_LABEL_RENDER_LIMIT
        return draw_arrows, draw_weights

    def redraw_all(self, draw_edges=True, preserve_view=True):
        self._is_redrawing = True
        total_edges = len(self.graph.edges)
        draw_arrows, draw_weight_labels = self._edge_render_flags(total_edges)
        try:
            self.canvas.delete('all')
            self.node_items = {}
            self.item_to_label = {}
            self.edge_items = {}
            self.item_to_edge = {}
            # draw edges first (optional)
            if draw_edges:
                for edge in self.graph.edges:
                    self._draw_edge(
                        edge,
                        draw_arrows=draw_arrows,
                        draw_weight_label=draw_weight_labels,
                    )
            # draw nodes
            for label in self.graph.labels():
                self._draw_node(label)
        finally:
            self._is_redrawing = False
        if preserve_view:
            self._apply_transform_to_canvas()
            self._update_scrollregion()
            self._restore_view_state()
        else:
            self._update_scrollregion()
            self._remember_view_state()
        self._reapply_selection_highlights()

    def _highlight_node(self, label):
        it = self.node_items.get(label)
        if not it: return
        oval, text = it
        self.canvas.itemconfig(oval, fill="#fde68a")

    def _unhighlight_node(self, label):
        it = self.node_items.get(label)
        if not it: return
        oval, text = it
        self.canvas.itemconfig(oval, fill="#e2e8f0")

    def _highlight_edge(self, edge_id):
        info = self.edge_items.get(edge_id)
        if not info:
            return
        line_id = info.get('line')
        weight_id = info.get('weight')
        if line_id:
            self.canvas.itemconfig(line_id, fill="#f97316", width=2)
        if weight_id:
            self.canvas.itemconfig(weight_id, fill="#fb923c")

    def _unhighlight_edge(self, edge_id):
        info = self.edge_items.get(edge_id)
        if not info:
            return
        line_id = info.get('line')
        weight_id = info.get('weight')
        if line_id:
            self.canvas.itemconfig(line_id, fill="#64748b", width=1)
        if weight_id:
            self.canvas.itemconfig(weight_id, fill="#94a3b8")

    def _reapply_selection_highlights(self):
        for label in self.selected_nodes:
            self._highlight_node(label)
        for edge_id in self.selected_edges:
            self._highlight_edge(edge_id)

    def _clear_selection(self):
        for lbl in list(self.selected_nodes):
            self._unhighlight_node(lbl)
        self.selected_nodes.clear()
        for edge_id in list(self.selected_edges):
            self._unhighlight_edge(edge_id)
        self.selected_edges.clear()
        self._update_selection_status()

    ############################################################
    # Manual actions
    ############################################################
    def _on_add_nodes_toggle(self):
        if self.add_nodes_mode.get():
            self.status("Add Nodes is ON. Click the canvas to drop new nodes.")
        else:
            self.status("Add Nodes is OFF. Click nodes or edges to select them.")

    def clear_selection_button(self):
        if not self.selected_nodes and not self.selected_edges:
            self.status("Selection is already empty.")
            return
        self._clear_selection()
        self.status("Selection cleared.")

    def _on_render_edges_toggle(self):
        self.redraw_all(draw_edges=self.render_edges_var.get(), preserve_view=True)

    def edit_selected_edge_weight(self):
        if not self.selected_edges or self.selected_nodes:
            return
        try:
            current_weight = None
            edge = self.graph.get_edge(self.selected_edges[-1])
            if edge:
                current_weight = edge.get('w')
        except Exception:
            current_weight = None
        initial = current_weight if isinstance(current_weight, (int, float)) else 1
        value = simpledialog.askfloat(
            "Edit weight",
            "Enter new edge weight:",
            initialvalue=initial,
            parent=self,
        )
        if value is None:
            self.status("Edge weight edit cancelled.")
            return
        if self.graph.weighted:
            for edge_id in self.selected_edges:
                edge = self.graph.get_edge(edge_id)
                if edge:
                    edge['w'] = value
        self.redraw_all(draw_edges=self.render_edges_var.get(), preserve_view=True)
        self.status(f"Updated {len(self.selected_edges)} edge(s) to weight {value}.")

    def connect_selected_nodes(self):
        if len(self.selected_nodes) < 2:
            self.status("Select two nodes first (Ctrl+click allows more).")
            return
        u, v = self.selected_nodes[-2], self.selected_nodes[-1]
        if u == v:
            self.status("Cannot connect a node to itself.")
            return
        weight = 1
        if self.weighted_var.get():
            try:
                value = simpledialog.askfloat(
                    "Edge weight",
                    "Enter weight:",
                    minvalue=-1e12,
                    maxvalue=1e12,
                    initialvalue=1.0,
                    parent=self
                )
                if value is None:
                    self.status("Edge creation cancelled.")
                    return
                weight = value
            except Exception:
                weight = 1
        edge = self.graph.add_edge(u, v, weight)
        if not edge:
            self.status("Edge already exists or nodes are missing.")
            return
        draw_arrows, draw_weight_labels = self._edge_render_flags()
        self._draw_edge(edge, draw_arrows=draw_arrows, draw_weight_label=draw_weight_labels)
        if self.selected_nodes:
            remaining = [lbl for lbl in self.selected_nodes if lbl not in (u, v)]
            self.selected_nodes = remaining
            self._unhighlight_node(u)
            self._unhighlight_node(v)
            self._update_selection_status()
        if self.weighted_var.get():
            try:
                display_weight = int(weight) if float(weight).is_integer() else weight
            except Exception:
                display_weight = weight
            weight_note = f"w={display_weight}"
        else:
            weight_note = "weightless"
        self.status(f"Added edge {u} -> {v} ({weight_note})")

    def delete_selected_items(self):
        nodes_to_remove = list(self.selected_nodes)
        edges_to_remove = list(self.selected_edges)
        if not nodes_to_remove and not edges_to_remove:
            self.status("No selection to delete.")
            return
        self._clear_selection()
        for label in nodes_to_remove:
            self.graph.remove_node(label)
        for edge_id in edges_to_remove:
            self.graph.remove_edge(edge_id)
        self.redraw_all(draw_edges=self.render_edges_var.get())
        self.status(f"Deleted {len(nodes_to_remove)} nodes and {len(edges_to_remove)} edges.")

    def delete_node(self, label):
        # remove from model
        self.graph.remove_node(label)
        if label in self.selected_nodes:
            self.selected_nodes.remove(label)
        # remove canvas items
        if label in self.node_items:
            for it in self.node_items[label]:
                if not it:
                    continue
                if it in self.item_to_label:
                    self.item_to_label.pop(it, None)
                self.canvas.delete(it)
            self.node_items.pop(label, None)
        # redraw everything to keep edges consistent
        self.redraw_all(draw_edges=self.render_edges_var.get())
        self._update_selection_status()
        self.status(f"Deleted node {label}")

    def clear_graph(self):
        self.graph.clear()
        self.node_items.clear()
        self.item_to_label.clear()
        self.edge_items.clear()
        self.item_to_edge.clear()
        self.canvas.delete('all')
        self.next_index.set(1)
        self.start_label_var.set('')
        self.target_label_var.set('')
        self._clear_selection()
        self._reset_viewport()
        self._hide_node_tooltip()
        self.status("Graph cleared")

    def _on_toggle_directed(self):
        self.graph.directed = self.directed_var.get()
        self.redraw_all(draw_edges=self.render_edges_var.get())
        self._update_estimated_edges()

    def _on_toggle_weighted(self):
        self.graph.weighted = self.weighted_var.get()
        self.redraw_all(draw_edges=self.render_edges_var.get())

    ############################################################
    # Layout helpers
    ############################################################
    def layout_circle(self):
        labels = self.graph.labels()
        n = len(labels)
        if n == 0: return
        cx, cy, R = 1000, 800, max(100, min(1200, 20*n))
        for i, lbl in enumerate(labels):
            ang = 2*math.pi * i / n
            x = cx + R * math.cos(ang)
            y = cy + R * math.sin(ang)
            self.graph.nodes[lbl] = (x, y)
        self.redraw_all(draw_edges=self.render_edges_var.get())

    def layout_grid(self):
        labels = self.graph.labels()
        n = len(labels)
        if n == 0: return
        cols = int(math.ceil(math.sqrt(n)))
        gap = 50
        startx, starty = 100, 100
        for idx, lbl in enumerate(labels):
            r = idx // cols
            c = idx % cols
            x = startx + c * gap
            y = starty + r * gap
            self.graph.nodes[lbl] = (x, y)
        self.redraw_all(draw_edges=self.render_edges_var.get())

    def layout_random(self):
        labels = self.graph.labels()
        if not labels: return
        random.seed(42)
        for lbl in labels:
            x = random.randint(100, 3800)
            y = random.randint(100, 2800)
            self.graph.nodes[lbl] = (x, y)
        self.redraw_all(draw_edges=self.render_edges_var.get())

    ############################################################
    # Generation
    ############################################################
    def _generate_model_data(
        self,
        N,
        gtype,
        directed,
        weighted,
        wmin,
        wmax,
        p,
        k,
        rows,
        cols,
        prefix,
        start_index,
        progress_callback=None,
        estimated_edges=None,
        abort_event=None,
    ):
        """Return a GraphModel populated per the requested parameters without touching the canvas."""
        total_nodes = rows * cols if gtype == 'grid' else N
        if total_nodes <= 0:
            raise ValueError("Node count must be positive.")

        model = GraphModel(directed=directed, weighted=weighted)
        labels = []
        next_index = start_index
        prefix = prefix or ""

        node_step = max(1, total_nodes // 200) if total_nodes > 0 else 1
        edge_goal = int(estimated_edges) if estimated_edges and estimated_edges > 0 else total_nodes
        edge_goal = max(1, edge_goal)
        edge_step = max(1, edge_goal // 200) if edge_goal > 0 else 1
        edge_progress = 0

        def check_abort():
            if abort_event and abort_event.is_set():
                raise GenerationAborted("Generation aborted by user.")

        def report(stage, done, total):
            if progress_callback:
                try:
                    progress_callback(stage, done, total)
                except Exception:
                    pass

        def maybe_report_nodes(count):
            check_abort()
            if total_nodes <= 0:
                return
            if count >= total_nodes or count % node_step == 0:
                report('nodes', count, total_nodes)

        def bump_edges(delta=1):
            check_abort()
            nonlocal edge_progress, edge_goal, edge_step
            if delta <= 0:
                return
            edge_progress += delta
            if edge_progress > edge_goal:
                edge_goal = edge_progress
                edge_step = max(1, edge_goal // 200)
            if edge_progress >= edge_goal or edge_progress % edge_step == 0:
                report('edges', edge_progress, edge_goal)

        for idx in range(total_nodes):
            check_abort()
            label = f"{prefix}{next_index}"
            next_index += 1
            labels.append(label)
            model.add_node(label, 0.0, 0.0)
            maybe_report_nodes(idx + 1)

        add_edge = model.add_edge
        rnd = random.random

        if gtype == 'random':
            edge_labels = labels[:]
            random.shuffle(edge_labels)
            self._generate_random_edges_fast(
                edge_labels,
                directed,
                weighted,
                wmin,
                wmax,
                p,
                add_edge,
                bump_edges,
                abort_event,
            )
        elif gtype == 'grid':
            for r in range(rows):
                check_abort()
                for c in range(cols):
                    check_abort()
                    idx = r * cols + c
                    if idx >= len(labels):
                        continue
                    if c + 1 < cols and idx + 1 < len(labels):
                        u, v = labels[idx], labels[idx + 1]
                        w = random.randint(wmin, wmax) if weighted else None
                        if add_edge(u, v, w if weighted else 1):
                            bump_edges()
                    if r + 1 < rows and idx + cols < len(labels):
                        u, v = labels[idx], labels[idx + cols]
                        w = random.randint(wmin, wmax) if weighted else None
                        if add_edge(u, v, w if weighted else 1):
                            bump_edges()
        elif gtype == 'ring':
            max_neighbors = max(0, k)
            for i in range(total_nodes):
                check_abort()
                for d in range(1, max_neighbors // 2 + 1):
                    check_abort()
                    j = (i + d) % total_nodes
                    u, v = labels[i], labels[j]
                    w = random.randint(wmin, wmax) if weighted else None
                    if directed:
                        if add_edge(u, v, w if weighted else 1):
                            bump_edges()
                        if add_edge(v, u, w if weighted else 1):
                            bump_edges()
                    else:
                        if u < v:
                            if add_edge(u, v, w if weighted else 1):
                                bump_edges()
                        else:
                            if add_edge(v, u, w if weighted else 1):
                                bump_edges()
        elif gtype == 'path':
            for i in range(total_nodes - 1):
                check_abort()
                u, v = labels[i], labels[i + 1]
                w = random.randint(wmin, wmax) if weighted else None
                if add_edge(u, v, w if weighted else 1):
                    bump_edges()
                if directed:
                    pass
        elif gtype == 'star':
            center = labels[0]
            for i in range(1, total_nodes):
                check_abort()
                u, v = center, labels[i]
                w = random.randint(wmin, wmax) if weighted else None
                if directed:
                    if add_edge(u, v, w if weighted else 1):
                        bump_edges()
                    if add_edge(v, u, w if weighted else 1):
                        bump_edges()
                else:
                    if add_edge(u, v, w if weighted else 1):
                        bump_edges()

        if progress_callback:
            report('nodes', total_nodes, total_nodes)

        self._ensure_generated_connectivity(
            labels,
            directed,
            weighted,
            wmin,
            wmax,
            graph=model,
            edge_hook=bump_edges if progress_callback else None,
            abort_event=abort_event,
        )

        if progress_callback:
            final_edges = max(edge_progress, len(model.edges))
            final_total = max(edge_goal, final_edges, 1)
            report('edges', final_edges, final_total)

        return model, next_index

    def _generate_random_edges_fast(self, labels, directed, weighted, wmin, wmax, p, add_edge, bump_edges, abort_event):
        n = len(labels)
        if n <= 1 or p <= 0.0:
            return
        # Clamp probabilities extremely close to 1.0 to avoid log(0)
        p = min(p, 1.0 - 1e-12)
        log_prob = math.log1p(-p)  # negative
        total_pairs = n * (n - 1) if directed else n * (n - 1) // 2
        idx = -1

        while True:
            if abort_event and abort_event.is_set():
                raise GenerationAborted("Generation aborted by user.")
            u = random.random()
            if u <= 0.0:
                continue
            skip = int(math.log(u) / log_prob)
            idx += skip + 1
            if idx >= total_pairs:
                break
            if directed:
                row = idx // (n - 1)
                col = idx % (n - 1)
                if col >= row:
                    col += 1
                i, j = row, col
            else:
                i, j = self._undirected_index_to_pair(idx, n)
            u_label = labels[i]
            v_label = labels[j]
            w = random.randint(wmin, wmax) if weighted else None
            if add_edge(u_label, v_label, w if weighted else 1):
                bump_edges()

    def _undirected_index_to_pair(self, idx, n):
        # Binary search to find row corresponding to idx
        lo, hi = 0, n - 1
        while lo < hi:
            mid = (lo + hi) // 2
            offset = mid * (2 * n - mid - 1) // 2
            if idx < offset:
                hi = mid
            else:
                lo = mid + 1
        i = max(0, lo - 1)
        offset = i * (2 * n - i - 1) // 2
        j = idx - offset + i + 1
        return i, j


    def generate_graph(self):
        if self._generation_in_progress:
            messagebox.showwarning("Generate", "Generation already in progress.")
            return
        if self._mass_generation_active:
            messagebox.showwarning("Generate", "Mass generation is currently running. Please wait or abort it first.")
            return
        N = int(self.gen_nodes_var.get())
        gtype = self.gen_type_var.get()
        directed = self.directed_var.get()
        weighted = self.weighted_var.get()
        wmin, wmax = int(self.weight_min_var.get()), int(self.weight_max_var.get())
        if wmin > wmax:
            wmin, wmax = wmax, wmin
        p = float(self.gnp_p_var.get())
        k = int(self.k_neighbors_var.get())
        rows = int(self.grid_rows_var.get())
        cols = int(self.grid_cols_var.get())

        # Confirm potentially heavy graphs
        estimated_edges = self._compute_estimated_edges(N, gtype, directed, p, k, rows, cols)
        if estimated_edges > 100_000:
            if not messagebox.askyesno("Large graph", f"This will create ~{estimated_edges:,} edges. Rendering may be slow; uncheck 'Render edges' if needed. Continue?"):
                return

        total_nodes = rows * cols if gtype == 'grid' else N
        edge_estimate = max(1, estimated_edges)
        self._show_mass_progress(total_nodes, edge_estimate)
        self.next_index.set(1)
        prefix = self.label_prefix.get()
        start_index = self.next_index.get()
        self._generation_in_progress = True
        self._generation_abort_event = threading.Event()
        self._update_generation_controls()
        self.status("Generating graph...")
        model = None
        next_index_value = None
        try:
            model, next_index_value = self._generate_model_data(
                N,
                gtype,
                directed,
                weighted,
                wmin,
                wmax,
                p,
                k,
                rows,
                cols,
                prefix,
                start_index,
                estimated_edges=estimated_edges,
                abort_event=self._generation_abort_event,
                progress_callback=lambda stage, done, total: self._update_mass_progress(stage, done, total),
            )
        except GenerationAborted:
            messagebox.showinfo("Generate", "Generation aborted.")
            self.status("Generation aborted.")
            return
        except Exception as exc:
            messagebox.showerror("Generate failed", f"Unable to create graph:\n{exc}")
            return
        finally:
            self._hide_mass_progress()
            self._generation_in_progress = False
            self._generation_abort_event = None
            self._update_generation_controls()

        self.clear_graph()
        self.graph = model
        self.next_index.set(next_index_value)

        # Layout for readability
        if gtype in ('ring', 'star'):
            self.layout_circle()
        elif gtype == 'grid':
            self._layout_grid_specific(rows, cols)
        else:
            self.layout_random()

        # Final redraw
        self.redraw_all(draw_edges=self.render_edges_var.get(), preserve_view=False)
        self._fit_view_to_contents()
        self._autofill_start_target_defaults()
        self.status(f"Generated {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges (directed={directed}, weighted={weighted}).")

    def mass_generate_and_export(self):
        try:
            N = int(self.gen_nodes_var.get())
            gtype = self.gen_type_var.get()
            directed = self.directed_var.get()
            weighted = self.weighted_var.get()
            wmin = int(self.weight_min_var.get())
            wmax = int(self.weight_max_var.get())
            if wmin > wmax:
                wmin, wmax = wmax, wmin
            p = float(self.gnp_p_var.get())
            k = int(self.k_neighbors_var.get())
            rows = int(self.grid_rows_var.get())
            cols = int(self.grid_cols_var.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Mass export", "Please ensure all generation fields contain valid numbers.")
            return

        format_choice = (self.mass_export_format_var.get() or ".csv").strip().lower()
        if not format_choice.startswith("."):
            format_choice = f".{format_choice}"
        fmt_map = {
            ".csv": {
                "ext": ".csv",
                "filetypes": [("CSV", "*.csv")],
                "exporter": self._export_model_to_csv,
                "title": "Save CSV",
            },
            ".lad": {
                "ext": ".lad",
                "filetypes": [("LAD", "*.lad"), ("Text", "*.txt"), ("All files", "*.*")],
                "exporter": self._export_model_to_lad,
                "title": "Save LAD",
            },
            ".grf": {
                "ext": ".grf",
                "filetypes": [("GRF", "*.grf"), ("Text", "*.txt"), ("All files", "*.*")],
                "exporter": self._export_model_to_grf,
                "title": "Save GRF",
            },
        }
        if format_choice not in fmt_map:
            messagebox.showerror("Mass export", f"Unsupported format: {format_choice}")
            return

        estimated_edges = self._compute_estimated_edges(N, gtype, directed, p, k, rows, cols)
        if estimated_edges > 1_000_000:
            proceed = messagebox.askyesno(
                "Large graph warning",
                f"This will synthesize approximately {estimated_edges:,} edges and may take a while.\nContinue?",
            )
            if not proceed:
                return

        total_nodes = rows * cols if gtype == 'grid' else N
        if total_nodes <= 0:
            messagebox.showerror("Mass export", "Node count must be positive.")
            return
        edge_estimate = int(estimated_edges) if estimated_edges and estimated_edges > 0 else total_nodes
        edge_estimate = max(1, edge_estimate)

        cfg = fmt_map[format_choice]
        path = filedialog.asksaveasfilename(
            defaultextension=cfg["ext"],
            filetypes=cfg["filetypes"],
            title="Mass Generate and Export",
        )
        if not path:
            return

        if self._mass_generation_active:
            messagebox.showwarning("Mass export", "Another mass generation is already running.")
            return
        if self._generation_in_progress:
            messagebox.showwarning("Mass export", "Manual generation is currently running. Please wait or abort it first.")
            return

        self.next_index.set(1)
        prefix = self.label_prefix.get()
        start_index = self.next_index.get()
        self.status("Mass generating graph...")
        self._show_mass_progress(total_nodes, edge_estimate)

        job = {
            'N': N,
            'gtype': gtype,
            'directed': directed,
            'weighted': weighted,
            'wmin': wmin,
            'wmax': wmax,
            'p': p,
            'k': k,
            'rows': rows,
            'cols': cols,
            'prefix': prefix,
            'start_index': start_index,
            'edge_estimate': edge_estimate,
            'path': path,
            'exporter': cfg["exporter"],
        }
        if not self._start_mass_export_job(job):
            self._hide_mass_progress()

    def _layout_grid_specific(self, rows, cols):
        labels = self.graph.labels()
        gap = 50
        startx, starty = 100, 100
        for idx, lbl in enumerate(labels):
            r = idx // cols
            c = idx % cols
            x = startx + c * gap
            y = starty + r * gap
            self.graph.nodes[lbl] = (x, y)

    def _ensure_generated_connectivity(self, labels, directed, weighted, wmin, wmax, graph=None, edge_hook=None, abort_event=None):
        if len(labels) <= 1:
            return
        graph = graph or self.graph

        parent = {lbl: lbl for lbl in labels}

        def check_abort():
            if abort_event and abort_event.is_set():
                raise GenerationAborted("Generation aborted by user.")

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            parent[rb] = ra

        for edge in graph.edges:
            check_abort()
            union(edge['u'], edge['v'])

        components = defaultdict(list)
        for lbl in labels:
            components[find(lbl)].append(lbl)

        if len(components) <= 1:
            return

        comp_lists = list(components.values())
        for i in range(1, len(comp_lists)):
            check_abort()
            u = comp_lists[i-1][0]
            v = comp_lists[i][0]
            weight = random.randint(wmin, wmax) if weighted else 1
            edge = graph.add_edge(u, v, weight if weighted else 1)
            if edge and edge_hook:
                edge_hook(1)
            if not edge:
                continue
            if directed:
                rev = graph.add_edge(v, u, weight if weighted else 1)
                if rev and edge_hook:
                    edge_hook(1)
            union(u, v)

    ############################################################
    # Export
    ############################################################
    def _export_model_to_csv(self, model, path):
        header_style = self.header_style_var.get()
        start_label = self.start_label_var.get().strip() or None
        target_label = self.target_label_var.get().strip() or None
        include_weight = self.include_weight_var.get()
        model.to_csv(
            path,
            header_style=header_style,
            start_label=start_label,
            target_label=target_label,
            include_weight=include_weight,
        )

    def _export_model_to_lad(self, model, path):
        labels, _, adjacency = self._build_adjacency_sets(model)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"{len(labels)}\n")
            for neighbors in adjacency:
                neighbor_list = sorted(neighbors)
                if neighbor_list:
                    f.write(f"{len(neighbor_list)} {' '.join(str(n) for n in neighbor_list)}\n")
                else:
                    f.write("0\n")

    def _export_model_to_grf(self, model, path):
        labels, _, adjacency = self._build_adjacency_sets(model)
        with open(path, 'w', encoding='utf-8') as f:
            f.write("# Number of nodes\n")
            f.write(f"{len(labels)}\n")
            for idx in range(len(labels)):
                f.write(f"{idx} 1\n")
            f.write("\n")
            for idx, neighbors in enumerate(adjacency):
                neighbor_list = sorted(neighbors)
                f.write(f"{len(neighbor_list)}\n")
                for nb in neighbor_list:
                    f.write(f"{idx} {nb}\n")

    def export_csv(self):
        if not self.graph.nodes:
            messagebox.showwarning("Export", "Graph is empty.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], title="Export CSV")
        if not path:
            return
        try:
            self.graph.to_csv(
                path,
                header_style=self.header_style_var.get(),
                start_label=(self.start_label_var.get().strip() or None),
                target_label=(self.target_label_var.get().strip() or None),
                include_weight=self.include_weight_var.get()
            )
            self.status(f"Exported CSV to {path}")
            messagebox.showinfo("Export", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def export_glasgow(self):
        if not self.graph.nodes:
            messagebox.showwarning("Export", "Graph is empty.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".lad", filetypes=[("LAD", "*.lad"), ("Text", "*.txt"), ("All files", "*.*")], title="Export LAD")
        if not path:
            return
        try:
            labels, _, adjacency = self._build_adjacency_sets()
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"{len(labels)}\n")
                for neighbors in adjacency:
                    neighbor_list = sorted(neighbors)
                    if neighbor_list:
                        f.write(f"{len(neighbor_list)} {' '.join(str(n) for n in neighbor_list)}\n")
                    else:
                        f.write("0\n")
            self.status(f"Exported LAD to {path}")
            messagebox.showinfo("Export", f"LAD file saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def export_vf3(self):
        if not self.graph.nodes:
            messagebox.showwarning("Export", "Graph is empty.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".grf", filetypes=[("GRF", "*.grf"), ("Text", "*.txt"), ("All files", "*.*")], title="Export GRF")
        if not path:
            return
        try:
            labels, _, adjacency = self._build_adjacency_sets()
            with open(path, 'w', encoding='utf-8') as f:
                f.write("# Number of nodes\n")
                f.write(f"{len(labels)}\n")
                for idx in range(len(labels)):
                    f.write(f"{idx} 1\n")
                f.write("\n")
                for idx, neighbors in enumerate(adjacency):
                    neighbor_list = sorted(neighbors)
                    f.write(f"{len(neighbor_list)}\n")
                    for nb in neighbor_list:
                        f.write(f"{idx} {nb}\n")
            self.status(f"Exported GRF to {path}")
            messagebox.showinfo("Export", f"GRF file saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")], title="Import CSV")
        self.import_status_var = self.import_status_csv
        if not path:
            self.import_status_var.set("Import cancelled.")
            return
        basename = os.path.basename(path)
        self.import_status_var.set(f"Importing \"{basename}\"...")
        self.status(f"Importing from {basename} ...")
        self.after(50, lambda: self._import_csv_from_path(path, self.import_status_var))

    def _import_csv_from_path(self, path, status_var=None):
        status_var = status_var or self.import_status_csv
        try:
            with open(path, newline='', encoding='utf-8') as f:
                raw_lines = f.readlines()
        except Exception as e:
            messagebox.showerror("Import failed", f"Could not read file:\n{e}")
            self._set_import_status(status_var, "Import failed while opening the file.")
            return

        metadata = {}
        idx = 0
        while idx < len(raw_lines) and not raw_lines[idx].strip():
            idx += 1
        if idx < len(raw_lines) and raw_lines[idx].lstrip().startswith('#'):
            metadata = self._parse_metadata_line(raw_lines[idx].lstrip()[1:])
            idx += 1
        data_lines = [line for line in raw_lines[idx:] if line.strip()]
        if not data_lines:
            messagebox.showwarning("Import", "CSV file has no data rows.")
            self._set_import_status(status_var, "No data rows found in the CSV.")
            return

        reader = csv.reader(data_lines)
        try:
            header = next(reader)
        except StopIteration:
            messagebox.showwarning("Import", "CSV file has no data rows.")
            self._set_import_status(status_var, "No data rows found in the CSV.")
            return
        header_lower = [h.strip().lower() for h in header]
        src_idx = self._find_header_index(header_lower, ("source", "src"))
        dst_idx = self._find_header_index(header_lower, ("target", "dst"))
        weight_idx = self._find_header_index(header_lower, ("weight", "w"))
        has_weight_column = weight_idx is not None
        data_rows = []
        if src_idx is None or dst_idx is None:
            data_rows.append(header)
            data_rows.extend(list(reader))
            src_idx, dst_idx = 0, 1
            weight_idx = 2 if len(header) > 2 else None
            has_weight_column = weight_idx is not None
        else:
            data_rows = list(reader)

        edges = []
        nodes = set()
        for row in data_rows:
            if not row or max(src_idx, dst_idx) >= len(row):
                continue
            u = row[src_idx].strip()
            v = row[dst_idx].strip()
            if not u or not v:
                continue
            weight = None
            if has_weight_column and weight_idx is not None and weight_idx < len(row):
                raw_weight = row[weight_idx].strip()
                if raw_weight == "":
                    weight = 1
                else:
                    try:
                        num = float(raw_weight)
                        weight = int(num) if num.is_integer() else num
                    except ValueError:
                        weight = raw_weight
            edges.append((u, v, weight))
            nodes.add(u)
            nodes.add(v)

        if not nodes:
            messagebox.showwarning("Import", "No valid edges found in CSV.")
            self._set_import_status(status_var, "Import failed: no valid edges in file.")
            return

        weighted = has_weight_column
        directed = False
        edge_set = {(u, v) for (u, v, _) in edges}
        for (u, v, _) in edges:
            if u != v and (v, u) in edge_set:
                directed = True
                break

        start_label = metadata.get('start', '')
        target_label = metadata.get('target', '')
        try:
            skipped = self._load_imported_graph(nodes, edges, weighted, directed, start_label, target_label)
        except ValueError as err:
            messagebox.showwarning("Import", str(err))
            self._set_import_status(status_var, str(err))
            return

        msg = f"Imported {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges"
        if skipped:
            msg += f" ({skipped} duplicates skipped)"
        self.status(msg)
        self._set_import_status(status_var, msg)
        messagebox.showinfo("Import complete", msg)

    def import_glasgow(self):
        path = filedialog.askopenfilename(filetypes=[("LAD", "*.lad"), ("Text", "*.txt"), ("All files", "*.*")], title="Import LAD")
        self.import_status_var = self.import_status_lad
        if not path:
            self.import_status_var.set("Import cancelled.")
            return
        basename = os.path.basename(path)
        self.import_status_var.set(f"Importing \"{basename}\"...")
        self.status(f"Importing from {basename} ...")
        self.after(50, lambda: self._import_glasgow_from_path(path, self.import_status_var))

    def _import_glasgow_from_path(self, path, status_var):
        try:
            with open(path, encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
        except Exception as e:
            messagebox.showerror("Import failed", f"Could not read file:\n{e}")
            self._set_import_status(status_var, "Import failed while opening the file.")
            return
        if not lines:
            messagebox.showwarning("Import", "LAD file is empty.")
            self._set_import_status(status_var, "Import failed: empty LAD file.")
            return
        try:
            node_count = int(lines[0])
        except ValueError:
            messagebox.showwarning("Import", "Invalid LAD file header.")
            self._set_import_status(status_var, "Import failed: invalid LAD header.")
            return
        adjacency_lines = lines[1:1+node_count]
        if len(adjacency_lines) < node_count:
            messagebox.showwarning("Import", "LAD file is missing adjacency rows.")
            self._set_import_status(status_var, "Import failed: incomplete LAD file.")
            return
        node_labels = [f"{i+1}" for i in range(node_count)]
        edges = []
        for idx, line in enumerate(adjacency_lines):
            parts = line.split()
            if not parts:
                continue
            try:
                degree = int(parts[0])
                neighbors = [int(x) for x in parts[1:]]
            except ValueError:
                continue
            if degree > len(neighbors):
                neighbors = neighbors[:degree]
            for nb in neighbors:
                if 0 <= nb < node_count and idx < nb:
                    edges.append((node_labels[idx], node_labels[nb], None))
        try:
            skipped = self._load_imported_graph(node_labels, edges, weighted=False, directed=False)
        except ValueError as err:
            messagebox.showwarning("Import", str(err))
            self._set_import_status(status_var, str(err))
            return
        msg = f"Imported {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges"
        if skipped:
            msg += f" ({skipped} duplicates skipped)"
        self.status(msg)
        self._set_import_status(status_var, msg)
        messagebox.showinfo("Import complete", msg)

    def import_vf3(self):
        path = filedialog.askopenfilename(filetypes=[("GRF", "*.grf"), ("Text", "*.txt"), ("All files", "*.*")], title="Import GRF")
        self.import_status_var = self.import_status_grf
        if not path:
            self.import_status_var.set("Import cancelled.")
            return
        basename = os.path.basename(path)
        self.import_status_var.set(f"Importing \"{basename}\"...")
        self.status(f"Importing from {basename} ...")
        self.after(50, lambda: self._import_vf3_from_path(path, self.import_status_var))

    def _import_vf3_from_path(self, path, status_var):
        try:
            with open(path, encoding='utf-8') as f:
                raw_lines = [line.rstrip() for line in f if line.strip()]
        except Exception as e:
            messagebox.showerror("Import failed", f"Could not read file:\n{e}")
            self._set_import_status(status_var, "Import failed while opening the file.")
            return
        idx = 0
        while idx < len(raw_lines) and raw_lines[idx].startswith('#'):
            idx += 1
        if idx >= len(raw_lines):
            messagebox.showwarning("Import", "GRF file missing node count.")
            self._set_import_status(status_var, "Import failed: invalid GRF header.")
            return
        try:
            node_count = int(raw_lines[idx].split()[0])
        except ValueError:
            messagebox.showwarning("Import", "GRF file has invalid node count.")
            self._set_import_status(status_var, "Import failed: invalid GRF node count.")
            return
        idx += 1
        nodes = []
        for _ in range(node_count):
            if idx >= len(raw_lines):
                break
            parts = raw_lines[idx].split()
            if parts:
                nodes.append(f"{int(parts[0]) + 1}")
            idx += 1
        if len(nodes) < node_count:
            nodes = [f"{i+1}" for i in range(node_count)]
        edges = []
        for node_id in range(node_count):
            if idx >= len(raw_lines):
                break
            try:
                degree = int(raw_lines[idx].split()[0])
            except ValueError:
                degree = 0
            idx += 1
            for _ in range(degree):
                if idx >= len(raw_lines):
                    break
                parts = raw_lines[idx].split()
                idx += 1
                if len(parts) < 2:
                    continue
                try:
                    src = int(parts[0])
                    dst = int(parts[1])
                except ValueError:
                    continue
                if 0 <= src < node_count and 0 <= dst < node_count:
                    edges.append((nodes[src], nodes[dst], None))
        try:
            skipped = self._load_imported_graph(nodes, edges, weighted=False, directed=True)
        except ValueError as err:
            messagebox.showwarning("Import", str(err))
            self._set_import_status(status_var, str(err))
            return
        msg = f"Imported {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges"
        if skipped:
            msg += f" ({skipped} duplicates skipped)"
        self.status(msg)
        self._set_import_status(status_var, msg)
        messagebox.showinfo("Import complete", msg)


def main():
    """Launch the GraphBuilderApp GUI."""
    app = GraphBuilderApp()
    app.mainloop()


if __name__ == "__main__":
    main()

