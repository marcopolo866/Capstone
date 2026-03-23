# Cross-platform build entrypoint for native benchmark binaries.
# This Makefile delegates to the existing platform-specific scripts so the
# exact solver build behavior stays consistent with CI and local workflows.

.DEFAULT_GOAL := build-local

.PHONY: build-all build-local build-local-sh build-local-ps1 build-runner clean submodules test help

BASH ?= bash
POWERSHELL ?= powershell
PYTHON ?= python

ifeq ($(OS),Windows_NT)
DEFAULT_BACKEND := ps1
else
DEFAULT_BACKEND := sh
endif

BACKEND ?= $(DEFAULT_BACKEND)

build-local:
ifeq ($(BACKEND),ps1)
	@echo "==> Building native solvers via scripts/build-local.ps1"
	"$(PYTHON)" "./scripts/build-local.py" --backend ps1 --cmake-generator "$(CMAKE_GENERATOR)"
else ifeq ($(BACKEND),sh)
	@echo "==> Building native solvers via scripts/build-local.sh"
	"$(PYTHON)" "./scripts/build-local.py" --backend sh --cmake-generator "$(CMAKE_GENERATOR)"
else
	$(error Unsupported BACKEND '$(BACKEND)'. Use BACKEND=ps1 or BACKEND=sh)
endif

build-local-sh:
	@echo "==> Building native solvers via scripts/build-local.sh"
	"$(PYTHON)" "./scripts/build-local.py" --backend sh --cmake-generator "$(CMAKE_GENERATOR)"

build-local-ps1:
	@echo "==> Building native solvers via scripts/build-local.ps1"
	"$(PYTHON)" "./scripts/build-local.py" --backend ps1 --cmake-generator "$(CMAKE_GENERATOR)"

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

clean:
	@echo "==> Removing local build artifacts"
	"$(PYTHON)" "./scripts/clean-local-build.py"

help:
	@echo "Targets:"
	@echo "  make build-all                 Build local solvers and package desktop runner for this OS."
	@echo "  make build-local               Build all local/native solvers (default)."
	@echo "  make build-runner              Package desktop runner for this OS."
	@echo "  make clean                     Remove local build artifacts."
	@echo "  make build-local BACKEND=sh    Force Bash backend (scripts/build-local.sh)."
	@echo "  make build-local BACKEND=ps1   Force PowerShell backend (scripts/build-local.ps1)."
	@echo "  make submodules                Initialize/update git submodules."
	@echo "  make test                      Run Python regression tests."
	@echo ""
	@echo "Options:"
	@echo "  CMAKE_GENERATOR=<name>         Forward generator to build script."
