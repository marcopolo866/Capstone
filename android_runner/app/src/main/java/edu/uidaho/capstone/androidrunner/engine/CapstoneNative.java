package edu.uidaho.capstone.androidrunner.engine;

final class CapstoneNative {
    static {
        System.loadLibrary("capstone_mobile_runner");
    }

    private CapstoneNative() {
    }

    static native String runSolver(
            String variantId,
            String family,
            String inputA,
            String inputB,
            String ladFormat
    );
}
