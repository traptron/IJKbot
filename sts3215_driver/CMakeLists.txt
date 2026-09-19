cmake_minimum_required(VERSION 3.10)

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
find_package(nav_msgs REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(rcl_interfaces REQUIRED)
find_package(tf2_ros REQUIRED)


# ============================================================
# Executable
# ============================================================

add_library(sts3215_hardware
    src/serial.cpp
    src/sts3215.cpp
)
add_library(sts3215_drive src/diff_drive_node.cpp)
add_executable(diff_drive_node src/diff_drive_main.cpp)


# ============================================================
# Include directories
# ============================================================

target_include_directories(sts3215_hardware
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_link_libraries(sts3215_drive sts3215_hardware)
target_link_libraries(diff_drive_node sts3215_drive)


# ============================================================
# ROS 2 dependencies
# ============================================================

ament_target_dependencies(sts3215_drive

    rclcpp
    geometry_msgs
    nav_msgs
    diagnostic_msgs
    rcl_interfaces
    tf2_ros

)


# ============================================================
# Install
# ============================================================

install(
    TARGETS diff_drive_node

    DESTINATION
        lib/${PROJECT_NAME}
)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
    find_package(ament_cmake_gtest REQUIRED)
    find_package(ament_cmake_pytest REQUIRED)
    ament_add_gtest(test_drive_math tests/test_drive_math.cpp)
    target_include_directories(test_drive_math PRIVATE include)
    ament_add_gtest(test_protocol tests/test_protocol.cpp)
    target_link_libraries(test_protocol sts3215_hardware util)
    ament_add_pytest_test(test_driver_integration tests/test_driver_integration.py
        TIMEOUT 45
        ENV "DRIVER_EXECUTABLE=$<TARGET_FILE:diff_drive_node>"
                   "ROS_DOMAIN_ID=177" "ROS_LOCALHOST_ONLY=1")
endif()


# ============================================================
# Package
# ============================================================

ament_package()
