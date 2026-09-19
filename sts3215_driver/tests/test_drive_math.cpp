#include "drive_math.hpp"

#include <gtest/gtest.h>

TEST(DriveMath, StraightAndRotationUseMeasuredTrack)
{
    const auto straight = ijkbot::wheelSpeeds(0.1, 0.0, 0.225, 0.25, 2.0, 0.25);
    EXPECT_DOUBLE_EQ(straight[0], 0.1);
    EXPECT_DOUBLE_EQ(straight[1], 0.1);
    const auto rotation = ijkbot::wheelSpeeds(0.0, 1.0, 0.225, 0.25, 2.0, 0.25);
    EXPECT_DOUBLE_EQ(rotation[0], -0.1125);
    EXPECT_DOUBLE_EQ(rotation[1], 0.1125);
}

TEST(DriveMath, SaturationPreservesWheelRatio)
{
    const auto speeds = ijkbot::wheelSpeeds(0.2, 1.0, 0.225, 0.25, 2.0, 0.19);
    EXPECT_DOUBLE_EQ(speeds[1], 0.19);
    EXPECT_NEAR(speeds[0] / speeds[1], 0.0875 / 0.3125, 1e-12);
    const auto reverse = ijkbot::wheelSpeeds(-100.0, 0.0, 0.225, 0.25, 2.0, 0.19);
    EXPECT_DOUBLE_EQ(reverse[0], -0.19);
}

TEST(DriveMath, BrakingIsBoundedAndReachesZero)
{
    std::array<double, 2> speed{0.19, -0.1};
    for (int i = 0; i < 10; ++i) {
        const auto next = ijkbot::ramp(speed, {0.0, 0.0}, 0.02);
        EXPECT_LE(std::abs(next[0] - speed[0]), 0.02000000001);
        EXPECT_GE(next[0], 0.0);
        EXPECT_LE(next[1], 0.0);
        speed = next;
    }
    EXPECT_DOUBLE_EQ(speed[0], 0.0);
    EXPECT_DOUBLE_EQ(speed[1], 0.0);
}

TEST(DriveMath, EncoderWrapsInBothDirections)
{
    EXPECT_EQ(ijkbot::encoderDelta(4090, 10), 16);
    EXPECT_EQ(ijkbot::encoderDelta(10, 4090), -16);
    EXPECT_EQ(ijkbot::encoderDelta(1, -5), -6);
    EXPECT_EQ(ijkbot::encoderDelta(32760, 2), 10);
}

TEST(DriveMath, StraightReverseRotationAndArc)
{
    ijkbot::Odometry pose;
    pose.update(1.0, 1.0, 0.225, 2.0);
    EXPECT_DOUBLE_EQ(pose.x, 1.0);
    EXPECT_DOUBLE_EQ(pose.y, 0.0);
    EXPECT_DOUBLE_EQ(pose.linear, 0.5);
    pose.update(-1.0, -1.0, 0.225, 2.0);
    EXPECT_NEAR(pose.x, 0.0, 1e-12);
    pose.update(-0.1125, 0.1125, 0.225, 1.0);
    EXPECT_NEAR(pose.yaw, 1.0, 1e-12);
    EXPECT_NEAR(pose.x, 0.0, 1e-12);
    ijkbot::Odometry arc;
    arc.update((1.0 - 0.225 / 2) * ijkbot::kPi / 2,
               (1.0 + 0.225 / 2) * ijkbot::kPi / 2, 0.225, 1.0);
    EXPECT_NEAR(arc.x, 1.0, 1e-12);
    EXPECT_NEAR(arc.y, 1.0, 1e-12);
}
