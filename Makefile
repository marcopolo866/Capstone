# Cross-platform build entrypoint for native benchmark binaries.
# This Makefile delegates to the existing platform-specific scripts so the
# exact solver build behavior stays consistent with CI and local workflows.

.DEFAULT_GOAL := build-local

.PHONY: build-all build-local build-local-sh build-local-ps1 build-runner clean submodules test help headless data-collection

BASH ?= bash
POWERSHELL ?= powershell
PYTHON ?= python
SUPPRESS_DIAGNOSTICS ?= 1
MANIFEST_DIR ?= data_collection
HEADLESS_ARGS ?=

ifeq ($(OS),Windows_NT)
DEFAULT_BACKEND := ps1
else
DEFAULT_BACKEND := sh
endif

BACKEND ?= $(DEFAULT_BACKEND)

build-local:
ifeq ($(BACKEND),ps1)
	@echo "==> Building native solvers via scripts/build-local.ps1"
	BUILD_LOCAL_SUPPRESS_DIAGNOSTICS="$(SUPPRESS_DIAGNOSTICS)" "$(PYTHON)" "./scripts/build-local.py" --backend ps1 --cmake-generator "$(CMAKE_GENERATOR)"
else ifeq ($(BACKEND),sh)
	@echo "==> Building native solvers via scripts/build-local.sh"
	BUILD_LOCAL_SUPPRESS_DIAGNOSTICS="$(SUPPRESS_DIAGNOSTICS)" "$(PYTHON)" "./scripts/build-local.py" --backend sh --cmake-generator "$(CMAKE_GENERATOR)"
else
	$(error Unsupported BACKEND '$(BACKEND)'. Use BACKEND=ps1 or BACKEND=sh)
endif

build-local-sh:
	@echo "==> Building native solvers via scripts/build-local.sh"
	BUILD_LOCAL_SUPPRESS_DIAGNOSTICS="$(SUPPRESS_DIAGNOSTICS)" "$(PYTHON)" "./scripts/build-local.py" --backend sh --cmake-generator "$(CMAKE_GENERATOR)"

build-local-ps1:
	@echo "==> Building native solvers via scripts/build-local.ps1"
	BUILD_LOCAL_SUPPRESS_DIAGNOSTICS="$(SUPPRESS_DIAGNOSTICS)" "$(PYTHON)" "./scripts/build-local.py" --backend ps1 --cmake-generator "$(CMAKE_GENERATOR)"

ifeq ($(OS),Windows_NT)
build-all: build-local build-runner

build-runner: build-local
	@echo "==> Installing desktop runner Python dependencies"
	"$(PYTHON)" -m pip install -r "./desktop_runner/requirements.txt"
	@echo "==> Packaging Windows desktop runner (.exe)"
	"$(PYTHON)" "./desktop_runner/build_runner.py"
else
build-all: build-local build-runner

build-runner: build-local
	@echo "==> Installing desktop runner Python dependencies"
	"$(PYTHON)" -m pip install -r "./desktop_runner/requirements.txt"
	@echo "==> Packaging desktop runner for this OS"
	"$(PYTHON)" "./desktop_runner/build_runner.py"
endif

submodules:
	@echo "==> Updating submodules"
	git submodule update --init --recursive

test:
	@echo "==> Running regression tests"
	python -m unittest discover -s tests -p "test_*.py" -v

headless:
	@echo "==> Running headless benchmark runner"
	"$(PYTHON)" "./scripts/benchmark-runner.py" $(HEADLESS_ARGS)

data-collection: build-local
	@echo "==> Running Data Collection manifests from $(MANIFEST_DIR)"
	"$(PYTHON)" "./scripts/benchmark-runner.py" --manifest-dir "$(MANIFEST_DIR)" --run $(HEADLESS_ARGS)

clean:
	@echo "==> Removing local build artifacts"
	"$(PYTHON)" "./scripts/clean-local-build.py"

help:
	@echo "Targets:"
	@echo "  make build-all                 Build local solvers and package desktop runner for this OS."
	@echo "  make build-local               Build all local/native solvers (default)."
	@echo "  make build-runner              Package desktop runner for this OS."
	@echo "  make headless                  Run the headless benchmark runner with HEADLESS_ARGS."
	@echo "  make data-collection           Build local solvers, then run all top-level manifests from MANIFEST_DIR."
	@echo "  make clean                     Remove local build artifacts."
	@echo "  make build-local BACKEND=sh    Force Bash backend (scripts/build-local.sh)."
	@echo "  make build-local BACKEND=ps1   Force PowerShell backend (scripts/build-local.ps1)."
	@echo "  make submodules                Initialize/update git submodules."
	@echo "  make test                      Run Python regression tests."
	@echo ""
	@echo "Options:"
	@echo "  CMAKE_GENERATOR=<name>         Forward generator to build script."
	@echo "  MANIFEST_DIR=<path>            Override the Data Collection manifest directory."
	@echo "  HEADLESS_ARGS=\"...\"            Pass raw arguments to scripts/benchmark-runner.py."
	@echo "  SUPPRESS_DIAGNOSTICS=1         Suppress compile warnings/notes (default)."
