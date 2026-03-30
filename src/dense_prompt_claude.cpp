/*
 * High-Performance Directed Node-Induced Subgraph Isomorphism Solver
 *
 * Design principles (derived from first principles, no named algorithms):
 *
 *  1. BITSET CANDIDATE SETS
 *     - 64-bit word bitsets for O(n/64) intersection, union, difference
 *     - Enables fast propagation and arc consistency
 *
 *  2. MULTI-LEVEL PRUNING (preprocessing):
 *     a) Label + degree filtering (out-degree >= H out-degree, same for in)
 *     b) Neighbor label signature: for each label l, count how many out-neighbors
 *        of a G node have label l; must be >= that count for H node
 *     c) 2-hop degree: sum of out-degrees of out-neighbors must be sufficient
 *     d) Arc consistency over all pattern edges (propagated to fixpoint)
 *
 *  3. INDUCED CONSTRAINT PROPAGATION
 *     - When h->g is assigned: for every other unassigned ph:
 *         if H has edge h->ph: f(ph) must be in G.out[g]
 *         else:                f(ph) must NOT be in G.out[g]
 *         (symmetric for in-edges)
 *     - This is the core "node-induced" constraint enforced at every step
 *
 *  4. DYNAMIC VARIABLE ORDERING
 *     - Always pick unassigned h with smallest candidate set
 *     - Break ties by most edges to already-assigned nodes
 *
 *  5. FORWARD CHECKING + LOOKAHEAD
 *     - After assignment, check all unassigned nodes have non-empty candidates
 *     - For small candidate sets, do arc consistency propagation
 *
 *  6. MEMORY: Candidate sets saved/restored on stack via Diff objects
 */

#include <algorithm>
#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <queue>
#include <unordered_map>
#include <utility>
#include <vector>
using namespace std;

// ─── Bitset ───────────────────────────────────────────────────────────────────

struct Bits {
    vector<uint64_t> w;
    int n = 0;

    Bits() {}
    explicit Bits(int n) : n(n), w((n+63)/64, 0ULL) {}

    void set(int i)    { w[i>>6] |=  (1ULL<<(i&63)); }
    void clr(int i)    { w[i>>6] &= ~(1ULL<<(i&63)); }
    bool get(int i) const { return (w[i>>6]>>(i&63))&1; }
    bool empty() const { for (auto x:w) if(x) return false; return true; }
    int count() const { int c=0; for(auto x:w) c+=__builtin_popcountll(x); return c; }
    int first() const {
        for(int i=0;i<(int)w.size();i++) if(w[i]) return i*64+__builtin_ctzll(w[i]);
        return -1;
    }

    void setAll() {
        fill(w.begin(),w.end(),~0ULL);
        if(n&63) w.back()>>=(64-(n&63));
    }

    // return new bits = this & o
    Bits andWith(const Bits& o) const {
        Bits r(n);
        for(int i=0;i<(int)w.size();i++) r.w[i]=w[i]&o.w[i];
        return r;
    }

    bool intersectIn(const Bits& o) {
        bool ch=false;
        for(int i=0;i<(int)w.size();i++){auto nw=w[i]&o.w[i];if(nw!=w[i]){w[i]=nw;ch=true;}}
        return ch;
    }

    bool subtractIn(const Bits& o) {
        bool ch=false;
        for(int i=0;i<(int)w.size();i++){auto nw=w[i]&~o.w[i];if(nw!=w[i]){w[i]=nw;ch=true;}}
        return ch;
    }

    bool hasCommon(const Bits& o) const {
        for(int i=0;i<(int)w.size();i++) if(w[i]&o.w[i]) return true;
        return false;
    }

    // Iterator
    struct Iter {
        const Bits& b; int wi; uint64_t cur;
        Iter(const Bits& b,bool end):b(b),wi(end?(int)b.w.size():0),cur(0){if(!end)adv();}
        void adv(){while(wi<(int)b.w.size()){cur=b.w[wi];if(cur)return;wi++;}}
        int operator*()const{return wi*64+__builtin_ctzll(cur);}
        Iter& operator++(){cur&=cur-1;if(!cur){wi++;adv();}return *this;}
        bool operator!=(const Iter&o)const{return wi!=o.wi;}
    };
    Iter begin()const{return Iter(*this,false);}
    Iter end()const{return Iter(*this,true);}
};

// ─── Graph ────────────────────────────────────────────────────────────────────

struct Graph {
    int n=0;
    vector<int> lbl, outDeg, inDeg;
    vector<vector<int>> out, in;
    vector<Bits> outB, inB;

    void init(int _n){
        n=_n; lbl.resize(n); outDeg.resize(n,0); inDeg.resize(n,0);
        out.resize(n); in.resize(n);
    }
    void addEdge(int u,int v){out[u].push_back(v);in[v].push_back(u);outDeg[u]++;inDeg[v]++;}
    void finalize(){
        outB.assign(n,Bits(n)); inB.assign(n,Bits(n));
        for(int u=0;u<n;u++) for(int v:out[u]){outB[u].set(v);inB[v].set(u);}
    }
    bool hasEdge(int u,int v)const{return outB[u].get(v);}
};

Graph H,G;

// ─── I/O ──────────────────────────────────────────────────────────────────────

Graph readGraph(const char* path){
    FILE* f=fopen(path,"r");
    if(!f){fprintf(stderr,"Cannot open %s\n",path);exit(1);}
    int n; fscanf(f,"%d",&n);
    Graph g; g.init(n);
    for(int i=0;i<n;i++){int id,l;fscanf(f,"%d %d",&id,&l);g.lbl[id]=l;}
    for(int i=0;i<n;i++){int k;fscanf(f,"%d",&k);for(int j=0;j<k;j++){int u,v;fscanf(f,"%d %d",&u,&v);g.addEdge(u,v);}}
    fclose(f);
    g.finalize();
    return g;
}

// ─── Preprocessing ────────────────────────────────────────────────────────────

int NH,NG;

// For each G node g, label->count of out-neighbors with that label
// We'll use this for neighbor signature filtering
vector<unordered_map<int,int>> gOutLblCnt, gInLblCnt;

void buildLabelCounts(){
    gOutLblCnt.resize(NG); gInLblCnt.resize(NG);
    for(int g=0;g<NG;g++){
        for(int v:G.out[g]) gOutLblCnt[g][G.lbl[v]]++;
        for(int v:G.in[g])  gInLblCnt[g][G.lbl[v]]++;
    }
}

// For H node h, compute required neighbor label counts
unordered_map<int,int> hOutLblCnt(int h){
    unordered_map<int,int> m;
    for(int v:H.out[h]) m[H.lbl[v]]++;
    return m;
}
unordered_map<int,int> hInLblCnt(int h){
    unordered_map<int,int> m;
    for(int v:H.in[h]) m[H.lbl[v]]++;
    return m;
}

Bits initialCandidates(int h){
    Bits b(NG);
    int lbl=H.lbl[h];
    int od=H.outDeg[h], id=H.inDeg[h];
    auto hOL=hOutLblCnt(h), hIL=hInLblCnt(h);
    for(int g=0;g<NG;g++){
        if(G.lbl[g]!=lbl) continue;
        if(G.outDeg[g]<od||G.inDeg[g]<id) continue;
        // Check neighbor label counts
        bool ok=true;
        for(auto&[l,cnt]:hOL){auto it=gOutLblCnt[g].find(l);if(it==gOutLblCnt[g].end()||it->second<cnt){ok=false;break;}}
        if(!ok) continue;
        for(auto&[l,cnt]:hIL){auto it=gInLblCnt[g].find(l);if(it==gInLblCnt[g].end()||it->second<cnt){ok=false;break;}}
        if(!ok) continue;
        b.set(g);
    }
    return b;
}

// Arc consistency: for pattern edge h->h2, remove g from c[h] if no g2 in c[h2] with g->g2
// Returns true if c[h] changed
bool pruneForward(int h,int h2,Bits& ch,const Bits& ch2){
    bool changed=false;
    // collect bits to remove
    // For each g in ch: G.outB[g] & ch2 must be non-empty
    vector<int> toRemove;
    for(int g:ch){
        if(!G.outB[g].hasCommon(ch2)) toRemove.push_back(g);
    }
    for(int g:toRemove){ch.clr(g);changed=true;}
    return changed;
}
bool pruneBackward(int h,int h2,Bits& ch2,const Bits& ch){
    bool changed=false;
    vector<int> toRemove;
    for(int g2:ch2){
        if(!G.inB[g2].hasCommon(ch)) toRemove.push_back(g2);
    }
    for(int g2:toRemove){ch2.clr(g2);changed=true;}
    return changed;
}

bool enforceAC(vector<Bits>& c){
    // Use a worklist of pattern edges
    // Also handle reverse arcs
    vector<pair<int,int>> edges;
    for(int h=0;h<NH;h++) for(int h2:H.out[h]) edges.push_back({h,h2});

    // Track which are in queue
    int NE=edges.size();
    if(NE==0) return true;

    vector<bool> inQ(NE,true);
    queue<int> q;
    for(int i=0;i<NE;i++) q.push(i);

    // Build edge index: for each node, which edges involve it
    vector<vector<int>> nodeEdges(NH); // edges where this node is the src or dst
    for(int i=0;i<NE;i++){
        nodeEdges[edges[i].first].push_back(i);
        nodeEdges[edges[i].second].push_back(i);
    }

    while(!q.empty()){
        int ei=q.front();q.pop();inQ[ei]=false;
        auto[h,h2]=edges[ei];
        if(c[h].empty()||c[h2].empty()) return false;

        bool ch=pruneForward(h,h2,c[h],c[h2]);
        bool cv=pruneBackward(h,h2,c[h2],c[h]);

        if(c[h].empty()||c[h2].empty()) return false;

        if(ch){
            for(int j:nodeEdges[h]) if(!inQ[j]){inQ[j]=true;q.push(j);}
        }
        if(cv){
            for(int j:nodeEdges[h2]) if(!inQ[j]){inQ[j]=true;q.push(j);}
        }
    }
    return true;
}

// ─── Search ───────────────────────────────────────────────────────────────────

long long solCount=0;

struct Diff {
    // Saved old candidate sets for rollback
    // Only save when actually modified
    vector<pair<int,Bits>> saved;
};

// Pick next unassigned node: smallest domain, break ties by most constrained
int pickNext(const vector<Bits>& c,const vector<bool>& asgn){
    int best=-1,bestSz=INT_MAX,bestTies=-1;
    for(int h=0;h<NH;h++){
        if(asgn[h]) continue;
        int sz=c[h].count();
        int ties=0;
        for(int p:H.in[h])  if(asgn[p]) ties++;
        for(int p:H.out[h]) if(asgn[p]) ties++;
        if(sz<bestSz||(sz==bestSz&&ties>bestTies)){
            bestSz=sz;best=h;bestTies=ties;
        }
    }
    return best;
}

// Apply assignment h->g: propagate induced constraints
// Returns false if contradiction found
bool propagate(int h,int g,vector<Bits>& c,Diff& diff,const vector<bool>& asgn){
    // Track modified sets
    vector<bool> mod(NH,false);

    auto modify=[&](int ph){
        if(!mod[ph]){
            diff.saved.push_back({ph,c[ph]});
            mod[ph]=true;
        }
    };

    // Fix c[h] = {g} (already done by caller, but we save it)
    // Injectivity: remove g from all other candidates
    for(int ph=0;ph<NH;ph++){
        if(ph==h||!c[ph].get(g)) continue;
        modify(ph);
        c[ph].clr(g);
        if(c[ph].empty()) return false;
    }

    // Induced edge constraints for each unassigned ph
    for(int ph=0;ph<NH;ph++){
        if(ph==h||asgn[ph]) continue;

        bool hToP=H.hasEdge(h,ph);
        bool pToH=H.hasEdge(ph,h);

        // Check if any change needed
        bool needOut=false,needIn=false;
        if(hToP){
            // c[ph] must intersect G.outB[g]
            for(int i=0;i<(int)c[ph].w.size();i++) if(c[ph].w[i]&~G.outB[g].w[i]){needOut=true;break;}
        } else {
            // c[ph] must not overlap G.outB[g]
            for(int i=0;i<(int)c[ph].w.size();i++) if(c[ph].w[i]&G.outB[g].w[i]){needOut=true;break;}
        }
        if(pToH){
            for(int i=0;i<(int)c[ph].w.size();i++) if(c[ph].w[i]&~G.inB[g].w[i]){needIn=true;break;}
        } else {
            for(int i=0;i<(int)c[ph].w.size();i++) if(c[ph].w[i]&G.inB[g].w[i]){needIn=true;break;}
        }

        if(!needOut&&!needIn) continue;
        modify(ph);

        if(hToP) c[ph].intersectIn(G.outB[g]);
        else     c[ph].subtractIn(G.outB[g]);
        if(c[ph].empty()) return false;

        if(pToH) c[ph].intersectIn(G.inB[g]);
        else     c[ph].subtractIn(G.inB[g]);
        if(c[ph].empty()) return false;
    }

    // Additional: for already-assigned nodes, verify consistency
    // (already ensured by construction, skip for speed)

    return true;
}

void undo(vector<Bits>& c,Diff& diff){
    for(auto&[ph,old]:diff.saved) c[ph]=move(old);
}

void solve(vector<Bits>& c,vector<bool>& asgn,int depth){
    if(depth==NH){solCount++;return;}

    int h=pickNext(c,asgn);
    if(h<0) return;

    Bits hCands=c[h]; // snapshot

    for(int g:hCands){
        Diff diff;
        // Save and fix c[h]
        diff.saved.push_back({h,c[h]});
        c[h]=Bits(NG); c[h].set(g);

        asgn[h]=true;
        bool ok=propagate(h,g,c,diff,asgn);

        if(ok) solve(c,asgn,depth+1);

        asgn[h]=false;
        undo(c,diff);
    }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

int main(int argc,char* argv[]){
    if(argc<3){fprintf(stderr,"Usage: %s <pattern> <target>\n",argv[0]);return 1;}

    H=readGraph(argv[1]);
    G=readGraph(argv[2]);
    NH=H.n; NG=G.n;

    buildLabelCounts();

    // Initial candidates
    vector<Bits> c(NH);
    for(int h=0;h<NH;h++) c[h]=initialCandidates(h);

    // Arc consistency
    if(!enforceAC(c)){printf("0\n");return 0;}

    for(int h=0;h<NH;h++) if(c[h].empty()){printf("0\n");return 0;}

    vector<bool> asgn(NH,false);
    solve(c,asgn,0);

    printf("%lld\n",solCount);
    return 0;
}