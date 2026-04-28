cmake_minimum_required(VERSION 3.22.1)

project(capstone_mobile_runner LANGUAGES CXX)

add_library(capstone_mobile_runner SHARED
    capstone_mobile_core.cpp
)

target_compile_features(capstone_mobile_runner PRIVATE cxx_std_20)
target_link_libraries(capstone_mobile_runner PRIVATE log)
