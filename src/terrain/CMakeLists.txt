cmake_minimum_required(VERSION 3.16)
project(terrain)

find_package(ament_cmake REQUIRED)
find_package(nav2_costmap_2d REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(pluginlib REQUIRED)
find_package(rclcpp REQUIRED)

add_library(bridge_layer SHARED src/bridge_layer.cpp src/floor_voxel_layer.cpp)
target_compile_features(bridge_layer PRIVATE cxx_std_17)
target_compile_options(bridge_layer PRIVATE -Wall -Wextra -Wpedantic)
ament_target_dependencies(bridge_layer nav2_costmap_2d nav_msgs pluginlib rclcpp)
target_link_libraries(bridge_layer nav2_costmap_2d::layers)
pluginlib_export_plugin_description_file(nav2_costmap_2d plugins.xml)
install(TARGETS bridge_layer LIBRARY DESTINATION lib)

install(PROGRAMS scripts/bridge_guard.py scripts/bridge_snapshot.py scripts/cloud_preview.py
  scripts/mapping_depth_filter.py scripts/navigation_depth.py
  DESTINATION lib/${PROJECT_NAME})
install(FILES scripts/surface.py DESTINATION lib/${PROJECT_NAME})
ament_package()
