# shellcheck shell=bash
# Entrypoint wrapper. Source chunks in order to preserve variable/function scope and behavior.
. .github/scripts/run-algorithm-step.d/01-init-inputs-and-conversion.sh
. .github/scripts/run-algorithm-step.d/02-progress-reporting.sh
. .github/scripts/run-algorithm-step.d/03-benchmark-and-metrics-helpers.sh
. .github/scripts/run-algorithm-step.d/04-main-dispatch-and-output.sh
