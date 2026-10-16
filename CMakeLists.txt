cmake_minimum_required(VERSION 3.20)
project(LayoutAgent CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# nlohmann/json (single header, in third_party/)
add_library(json INTERFACE)
target_include_directories(json INTERFACE ${CMAKE_SOURCE_DIR}/third_party)

# Main program
add_executable(myapp app/main.cpp)
target_link_libraries(myapp PRIVATE json)

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
