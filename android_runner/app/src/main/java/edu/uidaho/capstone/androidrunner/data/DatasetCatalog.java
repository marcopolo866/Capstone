package edu.uidaho.capstone.androidrunner.data;

import edu.uidaho.capstone.androidrunner.model.BenchmarkModels.DatasetSpec;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class DatasetCatalog {
    private DatasetCatalog() {
    }

    public static List<DatasetSpec> all() {
        List<DatasetSpec> rows = new ArrayList<>();
        rows.add(new DatasetSpec(
                "subgraph_sip_full",
                "SIP Full Archive",
                "subgraph",
                "SIP Benchmarks (Solnon)",
                "https://perso.citi-lab.fr/csolnon/SIP.html",
                "TGZ archive of subgraph benchmark suites",
                "Large benchmark archive containing multiple subgraph isomorphism suites.",
                27882629L,
                "http://perso.citi-lab.fr/csolnon/newSIPbenchmarks.tgz",
                "subgraph/subgraph_sip_full/raw/newSIPbenchmarks.tgz"
        ));
        rows.add(new DatasetSpec(
                "subgraph_mivia_arg",
                "MIVIA ARG Database",
                "subgraph",
                "MIVIA",
                "https://mivia.unisa.it/datasets/graph-database/arg-database/",
                "ZIP archive",
                "Large ARG benchmark collection; representative pairs are converted on demand on desktop.",
                418262348L,
                "https://mivia.unisa.it/database/graphsdb.zip",
                "subgraph/subgraph_mivia_arg/raw/graphsdb.zip"
        ));
        rows.add(new DatasetSpec(
                "subgraph_practical_bigraphs",
                "Practical Bigraphs (Zenodo)",
                "subgraph",
                "Zenodo",
                "https://zenodo.org/records/4597074",
                "TAR.XZ archive",
                "Practical Bigraphs benchmark archive with representative non-induced subgraph pairs.",
                14312140L,
                "https://zenodo.org/records/4597074/files/instances.tar.xz?download=1",
                "subgraph/subgraph_practical_bigraphs/raw/instances.tar.xz"
        ));
        rows.add(new DatasetSpec(
                "shortest_dimacs_usa_road_d",
                "DIMACS USA-road-d",
                "shortest_path",
                "DIMACS Challenge 9",
                "https://www.diag.uniroma1.it/challenge9/download.shtml",
                "DIMACS .gr.gz",
                "Full USA road network from DIMACS challenge data.",
                351265214L,
                "https://www.diag.uniroma1.it/challenge9/data/USA-road-d/USA-road-d.USA.gr.gz",
                "shortest_path/shortest_dimacs_usa_road_d/raw/USA-road-d.USA.gr.gz"
        ));
        rows.add(new DatasetSpec(
                "shortest_snap_roadnet_ca",
                "SNAP roadNet-CA",
                "shortest_path",
                "SNAP",
                "https://snap.stanford.edu/data/roadNet-CA.html",
                "Edge-list .txt.gz",
                "California road network graph from SNAP.",
                17892860L,
                "https://snap.stanford.edu/data/roadNet-CA.txt.gz",
                "shortest_path/shortest_snap_roadnet_ca/raw/roadNet-CA.txt.gz"
        ));
        rows.add(new DatasetSpec(
                "shortest_snap_roadnet_tx",
                "SNAP roadNet-TX",
                "shortest_path",
                "SNAP",
                "https://snap.stanford.edu/data/roadNet-TX.html",
                "Edge-list .txt.gz",
                "Texas road network graph from SNAP.",
                12442024L,
                "https://snap.stanford.edu/data/roadNet-TX.txt.gz",
                "shortest_path/shortest_snap_roadnet_tx/raw/roadNet-TX.txt.gz"
        ));
        rows.add(new DatasetSpec(
                "shortest_snap_wiki_talk",
                "SNAP Wiki-Talk",
                "shortest_path",
                "SNAP",
                "https://snap.stanford.edu/data/wiki-Talk.html",
                "Edge-list .txt.gz",
                "Wikipedia user talk network from SNAP.",
                16947922L,
                "https://snap.stanford.edu/data/wiki-Talk.txt.gz",
                "shortest_path/shortest_snap_wiki_talk/raw/wiki-Talk.txt.gz"
        ));
        rows.add(new DatasetSpec(
                "shortest_snap_livejournal",
                "SNAP LiveJournal",
                "shortest_path",
                "SNAP",
                "https://snap.stanford.edu/data/com-LiveJournal.html",
                "Edge-list .txt.gz",
                "Large LiveJournal social graph from SNAP.",
                124262769L,
                "https://snap.stanford.edu/data/bigdata/communities/com-lj.ungraph.txt.gz",
                "shortest_path/shortest_snap_livejournal/raw/com-lj.ungraph.txt.gz"
        ));
        return Collections.unmodifiableList(rows);
    }
}
