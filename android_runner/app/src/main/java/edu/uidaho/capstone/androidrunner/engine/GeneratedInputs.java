package edu.uidaho.capstone.androidrunner.engine;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

public final class GeneratedInputs {
    public File dijkstraFile;
    public File vfPattern;
    public File vfTarget;
    public File ladPattern;
    public File ladTarget;
    public String ladFormat = "vertex-labelled-lad";
    public final List<int[]> targetEdges = new ArrayList<>();
    public final List<int[]> patternEdges = new ArrayList<>();
    public final List<Integer> solutionNodes = new ArrayList<>();
    public final List<Integer> shortestPathNodes = new ArrayList<>();
    public final List<int[]> shortestPathEdges = new ArrayList<>();
    public String shortestFamily = "";
    public int shortestStartNode = -1;
    public int shortestTargetNode = -1;
    public int shortestViaNode = -1;
    public long shortestPathWeight = -1L;
    public boolean shortestPathReachable = false;
    public int targetNodeCount;
    public int patternNodeCount;
    public int n;
    public int k;
    public double density;
    public long seed;
    public int pointIndex;
    public int iterationIndex;
}
