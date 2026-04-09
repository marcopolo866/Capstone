cmake_minimum_required(VERSION 3.20)

project(capstone_graph_bench LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(CAPSTONE_BUILD_SOLVERS "Build baseline and discovered solver binaries." ON)
option(CAPSTONE_BUILD_TESTS "Build correctness and property tests." ON)
option(CAPSTONE_ENABLE_WARNINGS "Enable common warning flags for local builds." ON)

if(CAPSTONE_ENABLE_WARNINGS)
  if(MSVC)
    add_compile_options(/W4)
  else()
    add_compile_options(-Wall -Wextra -Wpedantic)
  endif()
endif()

if(CAPSTONE_BUILD_SOLVERS)
  add_executable(capstone_dijkstra_baseline baselines/dijkstra_main.cpp)
  target_include_directories(capstone_dijkstra_baseline PRIVATE baselines/nyaan-library)

  add_executable(capstone_dial_baseline baselines/dial_main.cpp)
  target_include_directories(capstone_dial_baseline PRIVATE baselines/cxxgraph/include)

  add_executable(capstone_sp_via_baseline baselines/via_dijkstra_main.cpp)

  add_executable(capstone_sp_via_dial baselines/via_dial_main.cpp)
  target_include_directories(capstone_sp_via_dial PRIVATE baselines/cxxgraph/include)

  file(GLOB CAPSTONE_DISCOVERED_SOLVER_SOURCES CONFIGURE_DEPENDS "${CMAKE_SOURCE_DIR}/src/*.cpp")
  foreach(source_file IN LISTS CAPSTONE_DISCOVERED_SOLVER_SOURCES)
    get_filename_component(source_name "${source_file}" NAME_WE)
    string(MAKE_C_IDENTIFIER "${source_name}" target_suffix)
    set(target_name "capstone_${target_suffix}")
    add_executable("${target_name}" "${source_file}")
  endforeach()
endif()

if(CAPSTONE_BUILD_TESTS)
  enable_testing()

  add_executable(capstone_graph_oracle_tests tests/cpp/graph_oracle_tests.cpp)
  add_test(NAME capstone_graph_oracle_tests COMMAND capstone_graph_oracle_tests)

  find_package(Python3 COMPONENTS Interpreter QUIET)
  if(Python3_Interpreter_FOUND)
    add_test(
      NAME capstone_python_regression
      COMMAND "${Python3_EXECUTABLE}" -m unittest discover -s tests -p "test_*.py" -v
    )
    set_tests_properties(capstone_python_regression PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
  endif()
endif()
