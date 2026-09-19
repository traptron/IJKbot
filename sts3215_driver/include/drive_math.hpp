#ifndef STS3215_DRIVE_MATH_HPP
#define STS3215_DRIVE_MATH_HPP

#include <algorithm>
#include <array>
#include <cmath>

namespace ijkbot
{
constexpr double kPi = 3.14159265358979323846;
constexpr double kEncoderTicks = 4096.0;

inline std::array<double, 2> wheelSpeeds(
    double linear, double angular, double separation, double linear_limit,
    double angular_limit, double wheel_limit)
{
    linear = std::clamp(linear, -linear_limit, linear_limit);
    angular = std::clamp(angular, -angular_limit, angular_limit);
    std::array<double, 2> speeds{
        linear - angular * separation / 2.0, linear + angular * separation / 2.0};
    const double scale = std::max({1.0, std::abs(speeds[0]) / wheel_limit,
                                  std::abs(speeds[1]) / wheel_limit});
    for (auto& speed : speeds) {
        speed /= scale;
    }
    return speeds;
}

inline std::array<double, 2> ramp(
    const std::array<double, 2>& current, const std::array<double, 2>& target,
    double maximum_change)
{
    const double largest = std::max(std::abs(target[0] - current[0]),
                                    std::abs(target[1] - current[1]));
    const double scale = largest > maximum_change ? maximum_change / largest : 1.0;
    return {current[0] + (target[0] - current[0]) * scale,
            current[1] + (target[1] - current[1]) * scale};
}

inline int encoderDelta(int previous, int current)
{
    int delta = (current - previous) % 4096;
    if (delta > 2048) {
        delta -= 4096;
    } else if (delta < -2048) {
        delta += 4096;
    }
    return delta;
}

struct Odometry
{
    double x{0.0};
    double y{0.0};
    double yaw{0.0};
    double linear{0.0};
    double angular{0.0};

    void update(double left_distance, double right_distance, double separation, double dt)
    {
        const double distance = (left_distance + right_distance) / 2.0;
        const double angle = (right_distance - left_distance) / separation;
        const double half = angle / 2.0;
        const double chord = distance * (std::abs(half) < 1e-9 ? 1.0 : std::sin(half) / half);
        x += chord * std::cos(yaw + half);
        y += chord * std::sin(yaw + half);
        yaw = std::remainder(yaw + angle, 2.0 * kPi);
        linear = distance / dt;
        angular = angle / dt;
    }
};
}  // namespace ijkbot
#endif
