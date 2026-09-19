#include "serial.hpp"
#include "sts3215.hpp"

#include <array>
#include <chrono>
#include <future>
#include <memory>
#include <numeric>
#include <poll.h>
#include <pty.h>
#include <stdexcept>
#include <termios.h>
#include <thread>
#include <unistd.h>
#include <vector>
#include <gtest/gtest.h>

class ProtocolTest : public testing::Test
{
protected:
    void SetUp() override
    {
        int slave;
        char path[128];
        ASSERT_EQ(openpty(&master_, &slave, path, nullptr, nullptr), 0);
        serial_ = std::make_unique<SerialPort>(path, B1000000, 100);
        close(slave);
        servo_ = std::make_unique<STS3215>(*serial_);
    }

    void TearDown() override
    {
        servo_.reset();
        serial_.reset();
        close(master_);
    }

    uint8_t byte()
    {
        pollfd descriptor{master_, POLLIN, 0};
        if (poll(&descriptor, 1, 500) <= 0) {
            throw std::runtime_error("Emulator timed out waiting for request");
        }
        uint8_t value = 0;
        if (::read(master_, &value, 1) != 1) {
            throw std::runtime_error("Emulator read failed");
        }
        return value;
    }

    std::vector<uint8_t> request()
    {
        std::vector<uint8_t> packet;
        for (int i = 0; i < 4; ++i) {
            packet.push_back(byte());
        }
        const int length = packet[3];
        for (int i = 0; i < length; ++i) {
            packet.push_back(byte());
        }
        EXPECT_EQ(packet[0], 0xFF);
        EXPECT_EQ(packet[1], 0xFF);
        EXPECT_EQ(std::accumulate(packet.begin() + 2, packet.end(), 0) & 0xFF, 0xFF);
        return packet;
    }

    void reply(uint8_t id, const std::vector<uint8_t>& data, uint8_t error = 0,
               bool corrupt = false, bool fragmented = false)
    {
        std::vector<uint8_t> packet{0xFF, 0xFF, id, static_cast<uint8_t>(data.size() + 2), error};
        packet.insert(packet.end(), data.begin(), data.end());
        const unsigned sum = std::accumulate(packet.begin() + 2, packet.end(), 0U);
        packet.push_back(static_cast<uint8_t>(~sum) ^ (corrupt ? 1 : 0));
        if (fragmented) {
            for (uint8_t value : packet) {
                EXPECT_EQ(::write(master_, &value, 1), 1);
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
        } else {
            EXPECT_EQ(::write(master_, packet.data(), packet.size()),
                      static_cast<ssize_t>(packet.size()));
        }
    }

    int master_{-1};
    std::unique_ptr<SerialPort> serial_;
    std::unique_ptr<STS3215> servo_;
};

TEST_F(ProtocolTest, SyncWriteBothDirections)
{
    servo_->syncWriteSpeeds({1, 2}, {1000, -1000});
    const auto packet = request();
    const std::vector<uint8_t> expected{
        0xFF, 0xFF, 0xFE, 10, 0x83, 0x2E, 2, 1, 0xE8, 3, 2, 0xE8, 0x83};
    EXPECT_EQ(std::vector<uint8_t>(packet.begin(), packet.end() - 1), expected);
}

TEST_F(ProtocolTest, SyncReadReversedResponsesAndFragmentedBytes)
{
    auto emulator = std::async(std::launch::async, [this]() {
        const auto packet = request();
        EXPECT_EQ(packet[4], 0x82);
        EXPECT_EQ(packet[5], 0x38);
        EXPECT_EQ(packet[6], 8);
        const uint8_t noise[]{0x12, 0xFF, 0x01};
        EXPECT_EQ(::write(master_, noise, sizeof(noise)), 3);
        reply(2, {0xFE, 0x0F, 0xE8, 0x83, 0, 0, 120, 42}, 0, false, true);
        reply(1, {10, 0, 0xE8, 3, 0, 0, 119, 40});
    });
    const auto result = servo_->syncReadFeedback({1, 2});
    emulator.get();
    EXPECT_EQ(result[0].position, 10);
    EXPECT_EQ(result[1].position, 4094);
    EXPECT_EQ(result[0].speed, 1000);
    EXPECT_EQ(result[1].speed, -1000);
    EXPECT_DOUBLE_EQ(result[1].voltage, 12.0);
    EXPECT_EQ(result[1].temperature, 42);
}

TEST_F(ProtocolTest, RejectsBadChecksumAndServoError)
{
    for (bool corrupt : {true, false}) {
        auto emulator = std::async(std::launch::async, [this, corrupt]() {
            request();
            reply(1, {}, corrupt ? 0 : 4, corrupt);
        });
        EXPECT_THROW(servo_->setTorque(1, false), std::runtime_error);
        emulator.get();
    }
}

TEST_F(ProtocolTest, RejectsWrongIdAndDuplicateFeedback)
{
    auto wrong_id = std::async(std::launch::async, [this]() {
        request();
        reply(2, {1});
    });
    EXPECT_THROW(servo_->readRegisters(1, 0x21, 1), std::runtime_error);
    wrong_id.get();
    auto duplicate = std::async(std::launch::async, [this]() {
        request();
        reply(1, std::vector<uint8_t>(8));
        reply(1, std::vector<uint8_t>(8));
    });
    EXPECT_THROW(servo_->syncReadFeedback({1, 2}), std::runtime_error);
    duplicate.get();
}

TEST_F(ProtocolTest, RejectsMalformedLengthAndTruncatedFrame)
{
    auto malformed = std::async(std::launch::async, [this]() {
        request();
        const uint8_t bytes[]{0xFF, 0xFF, 1, 255};
        EXPECT_EQ(::write(master_, bytes, sizeof(bytes)), 4);
    });
    EXPECT_THROW(servo_->readRegisters(1, 0x21, 1), std::runtime_error);
    malformed.get();
    auto truncated = std::async(std::launch::async, [this]() {
        request();
        const uint8_t bytes[]{0xFF, 0xFF, 1, 3, 0};
        EXPECT_EQ(::write(master_, bytes, sizeof(bytes)), 5);
    });
    EXPECT_THROW(servo_->readRegisters(1, 0x21, 1), std::runtime_error);
    truncated.get();
}

TEST_F(ProtocolTest, MissingReplyTimesOut)
{
    const auto start = std::chrono::steady_clock::now();
    EXPECT_THROW(servo_->syncReadFeedback({1, 2}), std::runtime_error);
    const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    EXPECT_GE(elapsed, 0.09);
    EXPECT_LT(elapsed, 0.5);
}

TEST_F(ProtocolTest, WheelModeClearsSpeedBeforeEnablingTorqueAndChecksReadback)
{
    auto emulator = std::async(std::launch::async, [this]() {
        const std::array<uint8_t, 6> registers{0x28, 0x2E, 0x21, 0x21, 0x29, 0x28};
        for (std::size_t i = 0; i < registers.size(); ++i) {
            const auto packet = request();
            EXPECT_EQ(packet[5], registers[i]);
            if (i == 0 || i == 1 || i == 4) {
                EXPECT_EQ(packet[6], 0);
            }
            if (i == 3) {
                EXPECT_EQ(packet[4], 0x02);
                reply(1, {1});
            } else {
                reply(1, {});
            }
        }
    });
    EXPECT_NO_THROW(servo_->enableWheelMode(1));
    emulator.get();
}

TEST_F(ProtocolTest, DuplicateIdsFailBeforeSending)
{
    EXPECT_THROW(servo_->syncWriteSpeeds({1, 1}, {0, 0}), std::invalid_argument);
}
