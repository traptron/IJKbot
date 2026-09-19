#ifndef STS3215_DIFF_DRIVE_NODE_HPP
#define STS3215_DIFF_DRIVE_NODE_HPP

#include "drive_math.hpp"
#include "serial.hpp"
#include "sts3215.hpp"

#include <array>
#include <chrono>
#include <memory>
#include <string>
#include <diagnostic_msgs/msg/diagnostic_array.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <rclcpp/rclcpp.hpp>
#include <tf2_ros/transform_broadcaster.h>

class DiffDriveNode : public rclcpp::Node
{
public:
    explicit DiffDriveNode(const rclcpp::NodeOptions& options = rclcpp::NodeOptions());
    ~DiffDriveNode() override;
    void stopHardware() noexcept;

private:
    using Clock = std::chrono::steady_clock;
    void command(const geometry_msgs::msg::Twist& message);
    void tick();
    void latchFault(const std::string& reason);
    void publishOdometry();
    void publishDiagnostics();

    bool mock_;
    bool fault_{false};
    bool have_command_{false};
    bool watchdog_active_{false};
    std::string fault_reason_;
    std::string odom_frame_;
    std::string base_frame_;
    bool publish_tf_;
    double wheel_diameter_;
    double separation_;
    double linear_limit_;
    double angular_limit_;
    double acceleration_;
    double deceleration_;
    double command_timeout_;
    double metres_per_tick_;
    double wheel_limit_;
    std::array<uint8_t, 2> ids_{};
    std::array<int64_t, 2> directions_{};
    std::array<double, 2> target_{};
    std::array<double, 2> applied_{};
    std::array<STS3215::Feedback, 2> feedback_{};
    ijkbot::Odometry odometry_;
    Clock::time_point last_command_;
    Clock::time_point last_tick_;
    Clock::time_point last_feedback_;
    std::unique_ptr<SerialPort> serial_;
    std::unique_ptr<STS3215> servo_;
    std::unique_ptr<tf2_ros::TransformBroadcaster> broadcaster_;
    rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr command_subscription_;
    rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odometry_publisher_;
    rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr diagnostics_publisher_;
    rclcpp::TimerBase::SharedPtr timer_;
    rclcpp::TimerBase::SharedPtr diagnostics_timer_;
};
#endif
