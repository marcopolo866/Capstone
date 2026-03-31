/*
 * High-performance node-induced directed subgraph isomorphism solver.
 *
 * Algorithm (derived from first principles):
 *
 * 1. MATCHING ORDER
 *    Greedy order that maximises early constraint propagation.
 *    Start with the highest-degree pattern node.  At each subsequent step,
 *    pick the unplaced node with the most edges to already-placed nodes
 *    (ties: total degree).  This keeps candidate sets small from the
 *    first levels of the search tree.
 *
 * 2. CANDIDATE COMPUTATION (neighbourhood filtering)
 *    The candidate set for pattern node p at depth d is built by:
 *      (a) Starting from the label-filtered G-node bitset.
 *      (b) Intersecting with succ_bs[f(q)] for each already-placed q with q->p in H.
 *      (c) Intersecting with pred_bs[f(q)] for each already-placed q with p->q in H.
 *    This implicitly enforces edge preservation for the prefix.
 *
 * 3. NODE-INDUCED CONSISTENCY
 *    After selecting candidate t for p, verify for every already-placed (q, f(q)):
 *      - (p,q) not in H  =>  (t,f(q)) not in G
 *      - (q,p) not in H  =>  (f(q),t) not in G
 *    (The positive direction is guaranteed by step 2.)
 *
 * 4. FORWARD CHECKING
 *    After placing p->t, recompute candidate sets for all remaining positions.
 *    Prune if any candidate set is empty.
 *
 * 5. DATA STRUCTURES
 *    Adjacency: sorted vectors + per-node uint64_t bitsets.
 *    Hot-path state: C arrays on the call stack (no heap during search).
 *
 * Compilation:  g++ -O2 -std=c++17 -o solver solver.cpp
 * Usage:        ./solver <pattern_file> <target_file>
 */

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <unordered_map>
#include <vector>
using namespace std;

// Maximum sizes
static const int MAX_H   = 105;
static const int MAX_G   = 10001;
static const int WORDS   = (MAX_G + 63) / 64;   // 157

// ─────────────────────────── Bitset row ──────────────────────────────────

struct Bitset {
    vector<uint64_t> data;
    int n = 0;
    void init(int sz) { n = sz; data.assign((sz+63)/64, 0ULL); }
    void set(int i)   { data[i>>6] |=  (1ULL<<(i&63)); }
    bool test(int i) const { return (data[i>>6]>>(i&63))&1; }
};

// ─────────────────────────── Graph ───────────────────────────────────────

struct Graph {
    int n = 0;
    vector<int>         label;
    vector<vector<int>> succ, pred;
    vector<Bitset>      succ_bs, pred_bs;

    void read(const char* path) {
        FILE* f = fopen(path,"r");
        if (!f) { fprintf(stderr,"Cannot open %s\n",path); exit(1); }
        if (fscanf(f,"%d",&n) != 1) { fclose(f); return; }
        label.resize(n); succ.resize(n); pred.resize(n);
        succ_bs.resize(n); pred_bs.resize(n);
        for (int i=0;i<n;i++) { succ_bs[i].init(n); pred_bs[i].init(n); }
        for (int i=0;i<n;i++) { int id; fscanf(f,"%d %d",&id,&label[i]); }
        for (int i=0;i<n;i++) {
            int k; fscanf(f,"%d",&k);
            for (int j=0;j<k;j++) {
                int u,v; fscanf(f,"%d %d",&u,&v);
                succ[u].push_back(v); pred[v].push_back(u);
                succ_bs[u].set(v); pred_bs[v].set(u);
            }
        }
        fclose(f);
        for (int i=0;i<n;i++) { sort(succ[i].begin(),succ[i].end()); sort(pred[i].begin(),pred[i].end()); }
    }
    bool has_edge(int u,int v) const { return succ_bs[u].test(v); }
    int  out_deg(int i) const { return (int)succ[i].size(); }
    int  in_deg(int i)  const { return (int)pred[i].size(); }
};

// ─────────────────────────── Solver globals ───────────────────────────────

static const Graph* gH;
static const Graph* gG;
static int H_n, G_n, G_words;

static int order[MAX_H];           // order[pos] = h-node
static int order_pos[MAX_H];       // order_pos[h-node] = pos

// For each position pos, lists of already-placed h-nodes connected to order[pos]
// pred_of[pos]: q placed before pos with q -> order[pos] in H => f(t) must be succ of f(q)
// succ_of[pos]: q placed before pos with order[pos] -> q in H => f(t) must be pred of f(q)
static vector<int> pred_of[MAX_H];
static vector<int> succ_of[MAX_H];

// Label bitsets: label_bs[lbl] = G_words-word bitset of G-nodes with that label
static unordered_map<int, vector<uint64_t>> label_bs;

static long long  solve_count;
static bool       used_g[MAX_G];
static int        mapping[MAX_H];  // h-node -> g-node, -1 if unset

// ─── Build matching order ────────────────────────────────────────────────

static void build_order() {
    bool placed[MAX_H] = {};
    int  score[MAX_H]  = {};
    int  tdeg[MAX_H];
    for (int i=0;i<H_n;i++) tdeg[i] = gH->out_deg(i)+gH->in_deg(i);

    int best = 0;
    for (int i=1;i<H_n;i++) if (tdeg[i]>tdeg[best]) best=i;

    for (int pos=0;pos<H_n;pos++) {
        int p;
        if (pos==0) { p=best; }
        else {
            p=-1;
            for (int i=0;i<H_n;i++) {
                if (placed[i]) continue;
                if (p==-1 || score[i]>score[p] || (score[i]==score[p] && tdeg[i]>tdeg[p])) p=i;
            }
        }
        order[pos]=p; order_pos[p]=pos; placed[p]=true;

        for (int nb:gH->succ[p]) if (!placed[nb]) score[nb]++;
        for (int nb:gH->pred[p]) if (!placed[nb]) score[nb]++;

        // Constraints from nodes ALREADY placed (before pos) that are adjacent to p
        for (int nb:gH->pred[p])   // nb->p in H
            if (placed[nb] && nb!=p) pred_of[pos].push_back(nb);
        for (int nb:gH->succ[p])   // p->nb in H
            if (placed[nb] && nb!=p) succ_of[pos].push_back(nb);
    }
}

// ─── Precompute label sets ────────────────────────────────────────────────

static void build_label_sets() {
    set<int> hlbls(gH->label.begin(), gH->label.end());
    for (int lbl : hlbls) {
        auto& bv = label_bs[lbl];
        bv.assign(G_words, 0ULL);
        for (int v=0;v<G_n;v++)
            if (gG->label[v]==lbl) bv[v>>6] |= (1ULL<<(v&63));
    }
}

// ─── Forward checking ────────────────────────────────────────────────────
// Check that all positions >= start_pos have non-empty candidate sets.
// `used_bs`: bitset of currently-used G-nodes (for injectivity).

static bool forward_check(int start_pos, const uint64_t* used_bs) {
    // We compute each candidate set freshly; no need to store it.
    uint64_t cand[WORDS];
    for (int pos = start_pos; pos < H_n; pos++) {
        int p   = order[pos];
        int lbl = gH->label[p];

        auto it = label_bs.find(lbl);
        if (it == label_bs.end()) return false;
        memcpy(cand, it->second.data(), (size_t)G_words*8);

        // Intersect with neighbour constraints from placed nodes (pos < start_pos)
        for (int q : pred_of[pos]) {
            if (order_pos[q] >= start_pos) continue; // not yet placed at this call depth
            const uint64_t* nb = gG->succ_bs[mapping[q]].data.data();
            for (int w=0;w<G_words;w++) cand[w] &= nb[w];
        }
        for (int q : succ_of[pos]) {
            if (order_pos[q] >= start_pos) continue;
            const uint64_t* nb = gG->pred_bs[mapping[q]].data.data();
            for (int w=0;w<G_words;w++) cand[w] &= nb[w];
        }

        // Remove used G-nodes
        for (int w=0;w<G_words;w++) cand[w] &= ~used_bs[w];

        // Check non-empty
        bool any = false;
        for (int w=0;w<G_words;w++) if (cand[w]) { any=true; break; }
        if (!any) return false;
    }
    return true;
}

// ─── Main recursive search ────────────────────────────────────────────────

static void dfs(int pos) {
    if (pos == H_n) { solve_count++; return; }

    int p        = order[pos];
    int lbl      = gH->label[p];
    int need_out = gH->out_deg(p);
    int need_in  = gH->in_deg(p);

    // Build candidate bitset
    uint64_t cand[WORDS];
    {
        auto it = label_bs.find(lbl);
        if (it == label_bs.end()) return;
        memcpy(cand, it->second.data(), (size_t)G_words*8);
    }
    for (int q : pred_of[pos]) {
        const uint64_t* nb = gG->succ_bs[mapping[q]].data.data();
        for (int w=0;w<G_words;w++) cand[w] &= nb[w];
    }
    for (int q : succ_of[pos]) {
        const uint64_t* nb = gG->pred_bs[mapping[q]].data.data();
        for (int w=0;w<G_words;w++) cand[w] &= nb[w];
    }

    // Build used_bs for forward checking
    uint64_t used_bs[WORDS] = {};
    for (int v=0;v<G_n;v++)
        if (used_g[v]) used_bs[v>>6] |= (1ULL<<(v&63));

    // Enumerate candidates
    for (int w=0;w<G_words;w++) {
        uint64_t word = cand[w];
        while (word) {
            int bit = __builtin_ctzll(word); word &= word-1;
            int t = w*64+bit;
            if (t >= G_n) break;

            // Quick degree filter
            if (gG->out_deg(t) < need_out) continue;
            if (gG->in_deg(t)  < need_in)  continue;

            // Injectivity
            if (used_g[t]) continue;

            // Node-induced constraint: check all already-placed pairs
            bool ok = true;
            for (int i=0; i<pos && ok; i++) {
                int q  = order[i];
                int fq = mapping[q];
                bool h_pq = gH->has_edge(p,q);
                bool h_qp = gH->has_edge(q,p);
                bool g_tf = gG->has_edge(t,fq);
                bool g_ft = gG->has_edge(fq,t);
                if (h_pq && !g_tf) { ok=false; break; }
                if (h_qp && !g_ft) { ok=false; break; }
                if (!h_pq && g_tf) { ok=false; break; }
                if (!h_qp && g_ft) { ok=false; break; }
            }
            if (!ok) continue;

            // Place
            mapping[p] = t; used_g[t] = true;
            used_bs[t>>6] |= (1ULL<<(t&63));

            // Forward checking before recursing
            bool fwd = (pos+1 >= H_n) || forward_check(pos+1, used_bs);
            if (fwd) dfs(pos+1);

            // Unplace
            mapping[p] = -1; used_g[t] = false;
            used_bs[t>>6] &= ~(1ULL<<(t&63));
        }
    }
}

// ─── Main ────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    if (argc < 3) { fprintf(stderr,"Usage: %s <pattern> <target>\n",argv[0]); return 1; }

    Graph H, G;
    H.read(argv[1]); G.read(argv[2]);

    gH = &H; gG = &G;
    H_n = H.n; G_n = G.n;
    G_words = (G_n+63)/64;

    if (H_n == 0) { printf("1\n"); return 0; }

    build_label_sets();
    build_order();

    fill(mapping, mapping+H_n, -1);
    fill(used_g, used_g+G_n, false);
    solve_count = 0;

    dfs(0);

    printf("%lld\n", solve_count);
    return 0;
}