cmake_minimum_required(VERSION 3.20)
project(LayoutAgent CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
add_compile_options(-Wall -Wextra)

# Sanitizers (off by default). Use a separate build directory:
#   cmake -S . -B build-asan -G Ninja -DCMAKE_BUILD_TYPE=Debug -DLAYOUTAGENT_SANITIZE=ON
#   ninja -C build-asan && ctest --test-dir build-asan --output-on-failure
# AddressSanitizer finds memory errors (out-of-range access, use after free, leaks).
# UndefinedBehaviorSanitizer finds undefined behavior such as signed integer overflow, which
# matters here because the geometry relies on int64_t arithmetic never overflowing.
# -fno-sanitize-recover makes the first UB report stop the program with a non-zero exit code,
# so ctest sees it as a failure (by default UBSan only prints a message and continues).
# This goes before the tests are added, so GoogleTest is built with the same flags.
option(LAYOUTAGENT_SANITIZE "Build with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
if(LAYOUTAGENT_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=undefined
                      -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()

# nlohmann/json (single header, in third_party/)
add_library(json INTERFACE)
target_include_directories(json INTERFACE ${CMAKE_SOURCE_DIR}/third_party)

# Main program
add_executable(layoutagent app/main.cpp)
target_link_libraries(layoutagent PRIVATE layoutagent_lib)

# Benchmark: naive spacing check against the grid (build it in a Release build, see the file)
add_executable(benchmark app/benchmark.cpp)
target_link_libraries(benchmark PRIVATE layoutagent_lib)

# clang-tidy: "ninja tidy" checks src/ and app/ with the rules in .clang-tidy (only if
# clang-tidy is installed). It reads build/compile_commands.json for the compiler flags.
find_program(CLANG_TIDY_EXE NAMES clang-tidy clang-tidy-18 clang-tidy-17 clang-tidy-16 clang-tidy-15)
if(CLANG_TIDY_EXE)
  file(GLOB TIDY_SOURCES CONFIGURE_DEPENDS ${CMAKE_SOURCE_DIR}/src/*.cpp ${CMAKE_SOURCE_DIR}/app/*.cpp)
  add_custom_target(tidy
    COMMAND ${CLANG_TIDY_EXE} -p ${CMAKE_BINARY_DIR} --quiet ${TIDY_SOURCES}
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    COMMENT "Running clang-tidy on src/ and app/"
    VERBATIM)
endif()

# GoogleTest (downloaded automatically by CMake)
include(FetchContent)
FetchContent_Declare(googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
FetchContent_MakeAvailable(googletest)

# Tests
enable_testing()
add_executable(hello_test tests/hello_test.cpp)
target_link_libraries(hello_test PRIVATE json GTest::gtest_main)

include(GoogleTest)
gtest_discover_tests(hello_test)

add_executable(test_rect tests/test_rect.cpp)
target_include_directories(test_rect PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(test_rect PRIVATE GTest::gtest_main)
gtest_discover_tests(test_rect)

add_executable(test_geometry tests/test_geometry.cpp)
target_include_directories(test_geometry PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(test_geometry PRIVATE GTest::gtest_main)
gtest_discover_tests(test_geometry)

add_executable(test_violation tests/test_violation.cpp)
target_include_directories(test_violation PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(test_violation PRIVATE GTest::gtest_main)
gtest_discover_tests(test_violation)

# Engine library: everything in src/ that has a .cpp file
add_library(layoutagent_lib src/layout.cpp src/checks.cpp src/io_json.cpp)
target_include_directories(layoutagent_lib PUBLIC ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(layoutagent_lib PRIVATE json)

add_executable(test_layout tests/test_layout.cpp)
target_link_libraries(test_layout PRIVATE layoutagent_lib GTest::gtest_main)
gtest_discover_tests(test_layout)

add_executable(test_checks tests/test_checks.cpp)
target_link_libraries(test_checks PRIVATE layoutagent_lib GTest::gtest_main)
gtest_discover_tests(test_checks)

add_executable(test_spacing_grid tests/test_spacing_grid.cpp)
target_link_libraries(test_spacing_grid PRIVATE layoutagent_lib GTest::gtest_main)
gtest_discover_tests(test_spacing_grid)

add_executable(test_io_json tests/test_io_json.cpp)
target_link_libraries(test_io_json PRIVATE layoutagent_lib json GTest::gtest_main)
gtest_discover_tests(test_io_json)

# Python tests for tools/gen_layout.py (standard-library unittest, no extra packages)
find_package(Python3 COMPONENTS Interpreter)
if(Python3_FOUND)
  add_test(NAME gen_layout_python_tests
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p test_gen_layout.py
           WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

  # End-to-end tests of the built command-line program (needs the layoutagent target built)
  add_test(NAME cli_e2e_python_tests
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p test_cli_e2e.py
           WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
  set_tests_properties(cli_e2e_python_tests PROPERTIES
                       ENVIRONMENT "LAYOUTAGENT_CLI=$<TARGET_FILE:layoutagent>")

  # Tests of the LLM tool layer in agent/tools.py (no network, no API key needed)
  add_test(NAME agent_tools_python_tests
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p test_agent_tools.py
           WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
  set_tests_properties(agent_tools_python_tests PROPERTIES
                       ENVIRONMENT "LAYOUTAGENT_CLI=$<TARGET_FILE:layoutagent>")

  # Tests of the LLM client (agent/llm.py), using a local fake HTTP server
  add_test(NAME agent_llm_python_tests
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p test_agent_llm.py
           WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

  # Tests of the evaluation scoring in eval/scoring.py (pure Python)
  add_test(NAME eval_scoring_python_tests
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p test_eval_scoring.py
           WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

  # Tests of the evaluation runner and eval/cases.json, using a scripted fake LLM
  add_test(NAME eval_runner_python_tests
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p test_eval_runner.py
           WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
  set_tests_properties(eval_runner_python_tests PROPERTIES
                       ENVIRONMENT "LAYOUTAGENT_CLI=$<TARGET_FILE:layoutagent>")

  # Tests of the agent loop and its terminal front end, using a scripted fake LLM
  add_test(NAME agent_loop_python_tests
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p test_agent_loop.py
           WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
  set_tests_properties(agent_loop_python_tests PROPERTIES
                       ENVIRONMENT "LAYOUTAGENT_CLI=$<TARGET_FILE:layoutagent>")
endif()
