# K7a: llama.cpp JNI bridge.
#
# The llama.cpp sources come from the git submodule external/llama.cpp
# (pinned to a release tag; the workflow prints tag + commit). Only the
# core llama + ggml libraries are built: no examples, no tests, no
# server, no curl, no OpenMP (ggml manages its own threads).
#
# arm64-v8a is compiled for ARMv8.2-A with dotprod and without i8mm
# (the Cortex-A78 target has no i8mm). x86_64 is baseline and exists
# only so the debug build can run on the emulator.
cmake_minimum_required(VERSION 3.22)
project(llama_jni LANGUAGES C CXX)

set(LLAMA_CPP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../external/llama.cpp")
if (NOT EXISTS "${LLAMA_CPP_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "llama.cpp submodule is missing at ${LLAMA_CPP_DIR}. "
        "Run: git submodule update --init --recursive")
endif()

set(LLAMA_BUILD_TESTS     OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES  OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS     OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL            OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON    OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP           OFF CACHE BOOL "" FORCE)
set(GGML_CCACHE           OFF CACHE BOOL "" FORCE)

if (ANDROID)
    if (ANDROID_ABI STREQUAL "arm64-v8a")
        # ARMv8.2-A + dotprod, no i8mm (Cortex-A78 target CPU has no i8mm).
        set(GGML_CPU_ARM_ARCH "armv8.2-a+dotprod" CACHE STRING "" FORCE)
        message(STATUS "K7a: arm64-v8a CPU backend -march=armv8.2-a+dotprod")
    elseif (ANDROID_ABI STREQUAL "x86_64")
        # Emulator-only debug build: keep the baseline instruction set.
        message(STATUS "K7a: x86_64 CPU backend (baseline, emulator debug builds)")
    endif ()
endif ()

add_subdirectory("${LLAMA_CPP_DIR}" llama-cpp-build EXCLUDE_FROM_ALL)

add_library(llama_jni SHARED llama_jni.cpp)
target_compile_features(llama_jni PRIVATE cxx_std_17)
target_link_libraries(llama_jni PRIVATE llama)
