# Use Ubuntu as base
FROM ubuntu:22.04

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install all dependencies in one layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    jq \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Pre-create common directories
RUN mkdir -p baselines data outputs

# Set git to trust any directory (for GitHub Actions)
RUN git config --global --add safe.directory '*'

# Default command
CMD ["/bin/bash"]