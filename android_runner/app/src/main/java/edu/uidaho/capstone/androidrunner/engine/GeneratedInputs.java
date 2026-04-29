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
    public int targetNodeCount;
    public int patternNodeCount;
    public long seed;
    public int pointIndex;
    public int iterationIndex;
}
