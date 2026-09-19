cmake_minimum_required(VERSION 3.8)

project(sts3215_driver)

# ============================================================
# Compiler
# ============================================================

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(
        -Wall
        -Wextra
        -Wpedantic
    )
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


# ============================================================
# Dependencies
# ============================================================

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)


# ============================================================
# Executable
# ============================================================

add_executable(sts3215_node

    src/node.cpp
    src/serial.cpp
    src/sts3215.cpp

)


# ============================================================
# Include directories
# ============================================================

target_include_directories(sts3215_node
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)


# ============================================================
# ROS 2 dependencies
# ============================================================

ament_target_dependencies(sts3215_node

    rclcpp
    geometry_msgs

)


# ============================================================
# Install
# ============================================================

install(
    TARGETS sts3215_node

    DESTINATION
        lib/${PROJECT_NAME}
)


# ============================================================
# Package
# ============================================================

ament_package()