#include "diff_drive_node.hpp"

#include <functional>
#include <stdexcept>
#include <termios.h>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <rcl_interfaces/msg/parameter_descriptor.hpp>

DiffDriveNode::DiffDriveNode(const rclcpp::NodeOptions& options)
    : Node("diff_drive_node", options)
{
    rcl_interfaces::msg::ParameterDescriptor descriptor;
    descriptor.read_only = true;
    const auto parameter = [this, &descriptor](const std::string& name, auto default_value) {
        return declare_parameter(name, default_value, descriptor);
    };
    mock_ = parameter("mock_hardware", true);
    const auto device = parameter("serial_port", std::string("/dev/ttySTS"));
    const auto baudrate = parameter("baudrate", 1000000);
    const auto timeout_ms = parameter("serial_timeout_ms", 30);
    const auto left_id = parameter("left_wheel_id", 1);
    const auto right_id = parameter("right_wheel_id", 2);
    directions_ = {parameter("left_wheel_direction", -1), parameter("right_wheel_direction", 1)};
    wheel_diameter_ = parameter("wheel_diameter", 0.075);
    separation_ = parameter("wheel_separation", 0.225);
    linear_limit_ = parameter("max_linear_velocity", 0.25);
    angular_limit_ = parameter("max_angular_velocity", 2.0);
    acceleration_ = parameter("wheel_acceleration", 0.5);
    deceleration_ = parameter("watchdog_deceleration", 1.0);
    command_timeout_ = parameter("cmd_vel_timeout", 0.2);
    odom_frame_ = parameter("odom_frame", std::string("odom"));
    base_frame_ = parameter("base_frame", std::string("base_footprint"));
    publish_tf_ = parameter("publish_tf", true);

    for (double value : {wheel_diameter_, separation_, linear_limit_, angular_limit_,
                         acceleration_, deceleration_, command_timeout_}) {
        if (!std::isfinite(value) || value <= 0.0) {
            throw std::invalid_argument("Geometry, limits and timeouts must be finite and positive");
        }
    }
    if (left_id < 0 || left_id > 253 || right_id < 0 || right_id > 253 || left_id == right_id ||
        (directions_[0] != 1 && directions_[0] != -1) ||
        (directions_[1] != 1 && directions_[1] != -1) ||
        wheel_diameter_ < 0.001 || wheel_diameter_ > 1.0 ||
        separation_ < 0.001 || separation_ > 2.0 || angular_limit_ > 2.0 ||
        linear_limit_ > 0.25 || command_timeout_ > 0.2 || baudrate != 1000000 ||
        timeout_ms < 1 || timeout_ms > 100 || odom_frame_.empty() || base_frame_.empty() ||
        odom_frame_ == base_frame_ || odom_frame_.front() == '/' || base_frame_.front() == '/') {
        throw std::invalid_argument("Invalid drive parameters: check IDs, directions, frames and safety limits");
    }
    ids_ = {static_cast<uint8_t>(left_id), static_cast<uint8_t>(right_id)};
    metres_per_tick_ = ijkbot::kPi * wheel_diameter_ / ijkbot::kEncoderTicks;
    wheel_limit_ = std::min(0.25, metres_per_tick_ * STS3215::MAX_SPEED);
    odometry_publisher_ = create_publisher<nav_msgs::msg::Odometry>("odom", 10);
    diagnostics_publisher_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>("diagnostics", 10);
    broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);
    auto qos = rclcpp::QoS(rclcpp::KeepLast(1));
    qos.lifespan(rclcpp::Duration::from_seconds(command_timeout_));
    command_subscription_ = create_subscription<geometry_msgs::msg::Twist>(
        "cmd_vel", qos, [this](geometry_msgs::msg::Twist::ConstSharedPtr message) {command(*message);});

    if (!mock_) {
        try {
            serial_ = std::make_unique<SerialPort>(device, B1000000, static_cast<int>(timeout_ms));
            servo_ = std::make_unique<STS3215>(*serial_);
            servo_->syncWriteSpeeds(ids_, {0, 0});
            for (uint8_t id : ids_) {
                servo_->enableWheelMode(id);
            }
            feedback_ = servo_->syncReadFeedback(ids_);
        } catch (const std::exception& error) {
            latchFault(error.what());
        }
    }
    last_tick_ = last_feedback_ = Clock::now();
    timer_ = create_wall_timer(std::chrono::milliseconds(20), [this]() {tick();});
    diagnostics_timer_ = create_wall_timer(std::chrono::seconds(1), [this]() {publishDiagnostics();});
    RCLCPP_INFO(get_logger(),
        "Drive %s: left=%u right=%u, wheel diameter=%.3f m, separation=%.3f m, fault=%s",
        mock_ ? "MOCK (no UART)" : "HARDWARE", ids_[0], ids_[1], wheel_diameter_, separation_,
        fault_ ? "yes" : "no");
    publishDiagnostics();
}

DiffDriveNode::~DiffDriveNode()
{
    stopHardware();
}

void DiffDriveNode::stopHardware() noexcept
{
    if (!servo_) {
        return;
    }
    try {
        servo_->syncWriteSpeeds(ids_, {0, 0});
    } catch (const std::exception& error) {
        RCLCPP_ERROR(get_logger(), "Could not send stop: %s", error.what());
    }
    for (uint8_t id : ids_) {
        try {
            servo_->setTorque(id, false);
        } catch (const std::exception& error) {
            RCLCPP_ERROR(get_logger(), "Could not disable servo %u: %s", id, error.what());
        }
    }
}

void DiffDriveNode::latchFault(const std::string& reason)
{
    fault_ = true;
    fault_reason_ = reason;
    target_ = applied_ = {0.0, 0.0};
    RCLCPP_ERROR(get_logger(), "Drive fault; motion locked until restart: %s", reason.c_str());
    stopHardware();
    publishDiagnostics();
}

void DiffDriveNode::command(const geometry_msgs::msg::Twist& message)
{
    if (fault_) {
        return;
    }
    for (double value : {message.linear.x, message.linear.y, message.linear.z,
                         message.angular.x, message.angular.y, message.angular.z}) {
        if (!std::isfinite(value)) {
            latchFault("Non-finite cmd_vel");
            return;
        }
    }
    target_ = ijkbot::wheelSpeeds(message.linear.x, message.angular.z, separation_,
                                linear_limit_, angular_limit_, wheel_limit_);
    if (!have_command_ || watchdog_active_) {
        RCLCPP_INFO(get_logger(), "cmd_vel received; motion control active");
    }
    have_command_ = true;
    watchdog_active_ = false;
    last_command_ = Clock::now();
}

void DiffDriveNode::tick()
{
    const auto current = Clock::now();
    const double dt = std::chrono::duration<double>(current - last_tick_).count();
    last_tick_ = current;
    if (fault_) {
        // Continue best-effort zero commands, but never resume motion automatically.
        if (servo_) {
            try {
                servo_->syncWriteSpeeds(ids_, {0, 0});
            } catch (const std::exception&) {
                // The original error is retained in diagnostics; avoid 50 Hz error spam.
            }
        }
        return;
    }
    // Мягкое ограничение dt для стабильности дифференциальной кинематики без аварийных падений
    const double safe_dt = std::clamp(dt, 0.001, 0.2);

    // 1. Опрос энкодеров и расчет одометрии
    bool tick_had_error = false;
    if (mock_) {
        odometry_.update(applied_[0] * safe_dt, applied_[1] * safe_dt, separation_, safe_dt);
    } else {
        try {
            const auto feedback = servo_->syncReadFeedback(ids_);
            const auto sample_time = Clock::now();
            const double sample_dt = std::clamp(
                std::chrono::duration<double>(sample_time - last_feedback_).count(),
                0.001, 0.2);

            std::array<double, 2> distances{};
            for (std::size_t i = 0; i < 2; ++i) {
                int delta = ijkbot::encoderDelta(feedback_[i].position, feedback[i].position);
                // Защита от одиночных аномальных выбросов энкодера без падения ноды
                const int max_plausible = static_cast<int>(STS3215::MAX_SPEED * sample_dt * 2.0 + 100.0);
                if (std::abs(delta) > max_plausible) {
                    delta = std::clamp(delta, -max_plausible, max_plausible);
                }
                distances[i] = delta * metres_per_tick_ * directions_[i];
            }
            odometry_.update(distances[0], distances[1], separation_, sample_dt);
            feedback_ = feedback;
            last_feedback_ = sample_time;
        } catch (const std::exception& error) {
            tick_had_error = true;
            try {
                if (serial_) {
                    serial_->discardInput();
                }
            } catch (const std::exception& flush_error) {
                RCLCPP_WARN_THROTTLE(
                    get_logger(), *get_clock(), 1000,
                    "Failed to discard UART input: %s", flush_error.what());
            }
            ++error_streak_;
            if (error_streak_ >= kMaxErrorStreak) {
                latchFault(std::string("UART feedback failed after ") +
                           std::to_string(error_streak_) + " retries: " + error.what());
                return;
            }
            RCLCPP_WARN_THROTTLE(
                get_logger(), *get_clock(), 1000,
                "UART dropped feedback packet (%zu/%zu): %s",
                error_streak_, kMaxErrorStreak, error.what());

            // Кратковременная экстраполяция одометрии по предыдущей скорости, чтобы не рвать TF
            const double left_dist = applied_[0] * safe_dt;
            const double right_dist = applied_[1] * safe_dt;
            odometry_.update(left_dist, right_dist, separation_, safe_dt);

            // Продвигаем позицию энкодеров на экстраполированное смещение,
            // чтобы при следующем успешном чтении не было двойного учета пути
            for (std::size_t i = 0; i < 2; ++i) {
                const int delta_ticks = static_cast<int>(std::lround(
                    (i == 0 ? left_dist : right_dist) / (metres_per_tick_ * directions_[i])));
                int new_pos = (static_cast<int>(feedback_[i].position) + delta_ticks) % 4096;
                if (new_pos < 0) {
                    new_pos += 4096;
                }
                feedback_[i].position = static_cast<uint16_t>(new_pos);
            }
            last_feedback_ = Clock::now();
        }
    }

    // 2. Управление скоростью моторов (выполняется ВСЕГДА, чтобы колеса не зависали)
    const bool expired = !have_command_ ||
        std::chrono::duration<double>(Clock::now() - last_command_).count() >= command_timeout_;
    if (expired && have_command_ && !watchdog_active_) {
        watchdog_active_ = true;
        RCLCPP_WARN(get_logger(), "cmd_vel timeout: ramping both wheels to zero");
    }
    const std::array<double, 2> desired = expired ? std::array<double, 2>{0.0, 0.0} : target_;
    applied_ = ijkbot::ramp(applied_, desired, (expired ? deceleration_ : acceleration_) * safe_dt);

    if (!mock_) {
        try {
            std::array<int16_t, 2> raw{};
            for (std::size_t i = 0; i < 2; ++i) {
                raw[i] = static_cast<int16_t>(std::lround(applied_[i] / metres_per_tick_ * directions_[i]));
            }
            servo_->syncWriteSpeeds(ids_, raw);
        } catch (const std::exception& error) {
            try {
                if (serial_) {
                    serial_->discardInput();
                }
            } catch (const std::exception& flush_error) {
                RCLCPP_WARN_THROTTLE(
                    get_logger(), *get_clock(), 1000,
                    "Failed to discard UART input: %s", flush_error.what());
            }
            if (!tick_had_error) {
                tick_had_error = true;
                ++error_streak_;
            }
            if (error_streak_ >= kMaxErrorStreak) {
                latchFault(std::string("Speed command failed after ") +
                           std::to_string(error_streak_) + " retries: " + error.what());
                return;
            }
            RCLCPP_WARN_THROTTLE(
                get_logger(), *get_clock(), 1000,
                "UART dropped speed command packet (%zu/%zu): %s",
                error_streak_, kMaxErrorStreak, error.what());
        }
    }

    if (!mock_ && !tick_had_error) {
        error_streak_ = 0;
    }

    publishOdometry();
}

void DiffDriveNode::publishOdometry()
{
    nav_msgs::msg::Odometry message;
    message.header.stamp = now();
    message.header.frame_id = odom_frame_;
    message.child_frame_id = base_frame_;
    message.pose.pose.position.x = odometry_.x;
    message.pose.pose.position.y = odometry_.y;
    message.pose.pose.orientation.z = std::sin(odometry_.yaw / 2.0);
    message.pose.pose.orientation.w = std::cos(odometry_.yaw / 2.0);
    message.twist.twist.linear.x = odometry_.linear;
    message.twist.twist.angular.z = odometry_.angular;
    // Initial estimates, to be calibrated on the real floor. Unobserved axes are uncertain.
    for (std::size_t index : {0U, 7U, 35U}) {
        message.pose.covariance[index] = 0.01;
        message.twist.covariance[index] = 0.02;
    }
    for (std::size_t index : {14U, 21U, 28U}) {
        message.pose.covariance[index] = 1e6;
        message.twist.covariance[index] = 1e6;
    }
    odometry_publisher_->publish(message);
    if (publish_tf_) {
        geometry_msgs::msg::TransformStamped transform;
        transform.header = message.header;
        transform.child_frame_id = base_frame_;
        transform.transform.translation.x = odometry_.x;
        transform.transform.translation.y = odometry_.y;
        transform.transform.rotation = message.pose.pose.orientation;
        broadcaster_->sendTransform(transform);
    }
}

void DiffDriveNode::publishDiagnostics()
{
    diagnostic_msgs::msg::DiagnosticArray message;
    message.header.stamp = now();
    diagnostic_msgs::msg::DiagnosticStatus status;
    status.name = "sts3215_drive";
    status.hardware_id = mock_ ? "mock" : "sts3215";
    status.level = fault_ ? diagnostic_msgs::msg::DiagnosticStatus::ERROR :
        (watchdog_active_ ? diagnostic_msgs::msg::DiagnosticStatus::WARN :
         diagnostic_msgs::msg::DiagnosticStatus::OK);
    status.message = fault_ ? fault_reason_ :
        (watchdog_active_ ? "cmd_vel timeout" : (mock_ ? "Mock hardware" : "Drive ready"));
    if (!mock_ && !fault_) {
        for (std::size_t i = 0; i < 2; ++i) {
            const std::string prefix = "servo_" + std::to_string(ids_[i]);
            const auto add = [&status, &prefix](const std::string& key, auto value) {
                diagnostic_msgs::msg::KeyValue item;
                item.key = prefix + key;
                item.value = std::to_string(value);
                status.values.push_back(item);
            };
            add("/voltage_v", feedback_[i].voltage);
            add("/temperature_c", feedback_[i].temperature);
            add("/speed_ticks_s", feedback_[i].speed);
        }
    }
    message.status.push_back(status);
    diagnostics_publisher_->publish(message);
}
