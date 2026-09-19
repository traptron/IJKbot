cmake_minimum_required(VERSION 3.8)
project(ijkbot_nav2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)

# Установка каталогов config, launch и maps в share/ijkbot_nav2
install(DIRECTORY
  config
  launch
  maps
  rviz
  DESTINATION share/${PROJECT_NAME}
)

ament_package()

