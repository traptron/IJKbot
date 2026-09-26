#include "diff_drive_node.hpp"

#include <cstdio>
#include <exception>

int main(int argc, char** argv)
{
    try {
        rclcpp::init(argc, argv);
        auto node = std::make_shared<DiffDriveNode>();
        rclcpp::spin(node);
        node.reset();
        rclcpp::shutdown();
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Driver startup failed: %s\n", error.what());
        rclcpp::shutdown();
        return 1;
    }
}
