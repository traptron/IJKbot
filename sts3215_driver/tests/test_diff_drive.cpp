#include "diff_drive_node.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <memory>
#include <numeric>
#include <poll.h>
#include <pty.h>
#include <stdexcept>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>
#include <gtest/gtest.h>

class PtyEmulator
{
public:
    PtyEmulator()
    {
        if (openpty(&master_, &slave_, path_, nullptr, nullptr) != 0) {
            throw std::runtime_error("openpty failed");
        }
        running_ = true;
        thread_ = std::thread([this]() { run(); });
    }

    ~PtyEmulator()
    {
        running_ = false;
        if (thread_.joinable()) {
            thread_.join();
        }
        if (slave_ >= 0) {
            close(slave_);
        }
        if (master_ >= 0) {
            close(master_);
        }
    }

    const char* slavePath() const noexcept { return path_; }

    void closeMaster()
    {
        running_ = false;
        if (thread_.joinable()) {
            thread_.join();
        }
        if (master_ >= 0) {
            close(master_);
            master_ = -1;
        }
    }

    void injectGlitches(int count) noexcept
    {
        glitches_to_inject_.store(count);
    }

    void setPositions(uint16_t pos1, uint16_t pos2) noexcept
    {
        pos1_.store(pos1);
        pos2_.store(pos2);
    }

private:
    void sendReply(uint8_t id, const std::vector<uint8_t>& data, uint8_t error = 0, bool corrupt = false)
    {
        std::vector<uint8_t> packet{0xFF, 0xFF, id, static_cast<uint8_t>(data.size() + 2), error};
        packet.insert(packet.end(), data.begin(), data.end());
        unsigned sum = std::accumulate(packet.begin() + 2, packet.end(), 0U);
        packet.push_back(static_cast<uint8_t>(~sum) ^ (corrupt ? 1 : 0));
        const ssize_t written = ::write(master_, packet.data(), packet.size());
        (void)written;
    }

    bool readExact(uint8_t* buffer, std::size_t size)
    {
        std::size_t received = 0;
        while (running_ && received < size) {
            pollfd pfd{master_, POLLIN, 0};
            int ret = poll(&pfd, 1, 50);
            if (ret < 0) {
                return false;
            }
            if (ret == 0) {
                continue;
            }
            ssize_t n = ::read(master_, buffer + received, size - received);
            if (n <= 0) {
                return false;
            }
            received += static_cast<std::size_t>(n);
        }
        return received == size;
    }

    void run()
    {
        while (running_) {
            uint8_t byte = 0;
            if (!readExact(&byte, 1)) {
                break;
            }
            if (byte != 0xFF) {
                continue;
            }
            if (!readExact(&byte, 1) || byte != 0xFF) {
                continue;
            }
            uint8_t header[2];
            if (!readExact(header, 2)) {
                break;
            }
            uint8_t id = header[0];
            uint8_t length = header[1];
            if (length < 2) {
                continue;
            }
            std::vector<uint8_t> body(length);
            if (!readExact(body.data(), length)) {
                break;
            }
            uint8_t instruction = body[0];
            if (instruction == 0x83) {
                // syncWriteSpeeds - broadcast write, no reply needed
            } else if (instruction == 0x03) {
                // writeRegister - acknowledge with empty body
                sendReply(id, {});
            } else if (instruction == 0x02) {
                // readRegisters - return MODE_WHEEL = 1
                sendReply(id, {1});
            } else if (instruction == 0x82) {
                // syncReadFeedback
                if (glitches_to_inject_.load() > 0) {
                    glitches_to_inject_.fetch_sub(1);
                    // Send corrupt checksum on first servo response
                    sendReply(1, {0, 0, 0, 0, 0, 0, 120, 40}, 0, /*corrupt=*/true);
                } else {
                    const uint16_t p1 = pos1_.load();
                    const uint16_t p2 = pos2_.load();
                    sendReply(1, {static_cast<uint8_t>(p1 & 0xFF), static_cast<uint8_t>((p1 >> 8) & 0xFF), 0, 0, 0, 0, 120, 40});
                    sendReply(2, {static_cast<uint8_t>(p2 & 0xFF), static_cast<uint8_t>((p2 >> 8) & 0xFF), 0, 0, 0, 0, 120, 40});
                }
            }
        }
    }

    int master_{-1};
    int slave_{-1};
    char path_[128]{};
    std::atomic<bool> running_{false};
    std::atomic<int> glitches_to_inject_{0};
    std::atomic<uint16_t> pos1_{0};
    std::atomic<uint16_t> pos2_{0};
    std::thread thread_;
};

class DiffDriveTest : public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        if (!rclcpp::ok()) {
            rclcpp::init(0, nullptr);
        }
    }

    static void TearDownTestSuite()
    {
        if (rclcpp::ok()) {
            rclcpp::shutdown();
        }
    }
};

TEST_F(DiffDriveTest, ParameterValidatorAllowsUpTo100ms)
{
    // Valid: 30 ms (target safe value)
    {
        rclcpp::NodeOptions options;
        options.append_parameter_override("mock_hardware", true);
        options.append_parameter_override("serial_timeout_ms", 30);
        EXPECT_NO_THROW({
            DiffDriveNode node(options);
        });
    }

    // Valid: 100 ms (upper boundary)
    {
        rclcpp::NodeOptions options;
        options.append_parameter_override("mock_hardware", true);
        options.append_parameter_override("serial_timeout_ms", 100);
        EXPECT_NO_THROW({
            DiffDriveNode node(options);
        });
    }

    // Invalid: 0 ms
    {
        rclcpp::NodeOptions options;
        options.append_parameter_override("mock_hardware", true);
        options.append_parameter_override("serial_timeout_ms", 0);
        EXPECT_THROW({
            DiffDriveNode node(options);
        }, std::invalid_argument);
    }

    // Invalid: 101 ms
    {
        rclcpp::NodeOptions options;
        options.append_parameter_override("mock_hardware", true);
        options.append_parameter_override("serial_timeout_ms", 101);
        EXPECT_THROW({
            DiffDriveNode node(options);
        }, std::invalid_argument);
    }
}

TEST_F(DiffDriveTest, SingleUartNoiseIsFilteredAndExtrapolatesOdometry)
{
    PtyEmulator emulator;
    rclcpp::NodeOptions options;
    options.append_parameter_override("mock_hardware", false);
    options.append_parameter_override("serial_port", std::string(emulator.slavePath()));
    options.append_parameter_override("serial_timeout_ms", 30);

    DiffDriveNode node(options);
    EXPECT_FALSE(node.isFault());
    // Subscribe to odom topic to verify publication is not broken by glitches (D09)
    std::vector<nav_msgs::msg::Odometry::SharedPtr> odom_msgs;
    auto sub = node.create_subscription<nav_msgs::msg::Odometry>(
        "odom", 10, [&odom_msgs](nav_msgs::msg::Odometry::SharedPtr msg) {
            odom_msgs.push_back(msg);
        });

    // Command forward motion
    geometry_msgs::msg::Twist cmd;
    cmd.linear.x = 0.1;
    node.setCommandForTest(cmd);

    // Tick 1: Normal successful cycle (forward motion: left delta < 0, right delta > 0)
    emulator.setPositions(4086, 10);
    node.tickForTest();
    rclcpp::spin_some(node.get_node_base_interface());

    EXPECT_FALSE(node.isFault());
    EXPECT_EQ(node.errorStreak(), 0U);
    ASSERT_EQ(odom_msgs.size(), 1U);

    // Tick 2: Corrupted feedback packet (UART noise / CRC error)
    emulator.injectGlitches(1);
    node.tickForTest();
    rclcpp::spin_some(node.get_node_base_interface());

    // Streak incremented, node did NOT latch fault, and odometry was extrapolated and published
    EXPECT_EQ(node.errorStreak(), 1U);
    EXPECT_FALSE(node.isFault());
    EXPECT_GT(node.odometry().x, 0.0);
    ASSERT_EQ(odom_msgs.size(), 2U);
    EXPECT_GT(odom_msgs.back()->pose.pose.position.x, odom_msgs.front()->pose.pose.position.x);

    // Tick 3: Successful recovery
    emulator.setPositions(4066, 30);
    node.tickForTest();
    rclcpp::spin_some(node.get_node_base_interface());

    // Streak must reset to 0 after successful feedback read
    EXPECT_EQ(node.errorStreak(), 0U);
    EXPECT_FALSE(node.isFault());
    ASSERT_EQ(odom_msgs.size(), 3U);
    EXPECT_GT(odom_msgs.back()->pose.pose.position.x, odom_msgs[1]->pose.pose.position.x);
}

TEST_F(DiffDriveTest, IntermittentGlitchesUnderFiveDoNotLatchFault)
{
    PtyEmulator emulator;
    rclcpp::NodeOptions options;
    options.append_parameter_override("mock_hardware", false);
    options.append_parameter_override("serial_port", std::string(emulator.slavePath()));
    options.append_parameter_override("serial_timeout_ms", 30);

    DiffDriveNode node(options);
    EXPECT_FALSE(node.isFault());

    // 4 consecutive glitches
    emulator.injectGlitches(4);
    for (std::size_t i = 1; i <= 4; ++i) {
        node.tickForTest();
        EXPECT_EQ(node.errorStreak(), i);
        EXPECT_FALSE(node.isFault());
    }

    // 5th tick succeeds -> resets streak
    emulator.setPositions(50, 4046);
    node.tickForTest();

    EXPECT_EQ(node.errorStreak(), 0U);
    EXPECT_FALSE(node.isFault());
}

TEST_F(DiffDriveTest, FiveConsecutiveErrorsLatchFaultAndStopMotion)
{
    PtyEmulator emulator;
    rclcpp::NodeOptions options;
    options.append_parameter_override("mock_hardware", false);
    options.append_parameter_override("serial_port", std::string(emulator.slavePath()));
    options.append_parameter_override("serial_timeout_ms", 30);

    DiffDriveNode node(options);
    EXPECT_FALSE(node.isFault());

    // 5 consecutive glitches
    emulator.injectGlitches(5);
    for (std::size_t i = 1; i <= 4; ++i) {
        node.tickForTest();
        EXPECT_EQ(node.errorStreak(), i);
        EXPECT_FALSE(node.isFault());
    }

    // 5th consecutive glitch triggers latchFault
    node.tickForTest();

    EXPECT_EQ(node.errorStreak(), 5U);
    EXPECT_TRUE(node.isFault());
    EXPECT_NE(node.faultReason().find("UART feedback failed"), std::string::npos);
    EXPECT_NE(node.faultReason().find("5 retries"), std::string::npos);

    // Subsequent tick remains in fault
    node.tickForTest();
    EXPECT_TRUE(node.isFault());
}

TEST_F(DiffDriveTest, AlternatingNoiseUnderStreakThresholdMaintainsTracking)
{
    PtyEmulator emulator;
    rclcpp::NodeOptions options;
    options.append_parameter_override("mock_hardware", false);
    options.append_parameter_override("serial_port", std::string(emulator.slavePath()));
    options.append_parameter_override("serial_timeout_ms", 30);

    DiffDriveNode node(options);
    EXPECT_FALSE(node.isFault());

    geometry_msgs::msg::Twist cmd;
    cmd.linear.x = 0.1;
    node.setCommandForTest(cmd);

    // Stress test: 5 consecutive cycles of 4 glitches followed by 1 successful read.
    // The driver must never latch fault because errors never reach 5 consecutively.
    uint16_t p1 = 0;
    uint16_t p2 = 0;
    for (int cycle = 0; cycle < 5; ++cycle) {
        emulator.injectGlitches(4);
        for (std::size_t i = 1; i <= 4; ++i) {
            node.tickForTest();
            EXPECT_EQ(node.errorStreak(), i);
            EXPECT_FALSE(node.isFault());
        }

        // 5th tick succeeds and resets streak
        p1 = static_cast<uint16_t>((p1 - 40 + 4096) % 4096);
        p2 = static_cast<uint16_t>((p2 + 40) % 4096);
        emulator.setPositions(p1, p2);
        node.tickForTest();

        EXPECT_EQ(node.errorStreak(), 0U);
        EXPECT_FALSE(node.isFault());
    }
}

TEST_F(DiffDriveTest, DisconnectedUartIncrementsStreakOncePerTickAndFaultsAtFive)
{
    PtyEmulator emulator;
    rclcpp::NodeOptions options;
    options.append_parameter_override("mock_hardware", false);
    options.append_parameter_override("serial_port", std::string(emulator.slavePath()));
    options.append_parameter_override("serial_timeout_ms", 30);

    DiffDriveNode node(options);
    EXPECT_FALSE(node.isFault());

    // Fully close the master pty to simulate physical UART cable disconnection.
    // Both feedback read and speed write will fail in each tick.
    emulator.closeMaster();

    for (std::size_t i = 1; i <= 4; ++i) {
        node.tickForTest();
        // The error streak must increment by exactly 1 per tick (not 2 from both read+write failing)
        EXPECT_EQ(node.errorStreak(), i);
        EXPECT_FALSE(node.isFault());
    }

    // 5th tick: triggers latchFault
    node.tickForTest();
    EXPECT_EQ(node.errorStreak(), 5U);
    EXPECT_TRUE(node.isFault());
}

