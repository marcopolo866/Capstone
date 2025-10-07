# Use a base image with modern C++ tools
FROM ubuntu:22.04

# Install essentials
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    wget \
    libgmp-dev \
    g++-11 \
    clang-14

# Set default compiler
ENV CXX=g++-11

# Set up a working directory
WORKDIR /app