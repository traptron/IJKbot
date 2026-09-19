#ifndef STS3215_HPP
#define STS3215_HPP

#include "serial.hpp"

#include <cstddef>
#include <cstdint>

class STS3215
{
public:
    static constexpr int16_t MAX_SPEED = 3400;

    explicit STS3215(SerialPort& serial);

    void enableWheelMode(uint8_t id);

    void setTorque(
        uint8_t id,
        bool enabled
    );

    void setSpeed(
        uint8_t id,
        int16_t speed
    );

    void stop(uint8_t id);

private:
    SerialPort& serial_;

    static constexpr uint8_t HEADER = 0xFF;

    static constexpr uint8_t INST_WRITE = 0x03;

    static constexpr uint8_t ADDR_MODE          = 0x21;
    static constexpr uint8_t ADDR_TORQUE_ENABLE = 0x28;
    static constexpr uint8_t ADDR_GOAL_SPEED    = 0x2E;

    static constexpr uint8_t MODE_WHEEL = 0x01;

    void writeRegister(
        uint8_t id,
        uint8_t address,
        const uint8_t* data,
        std::size_t data_size
    );

    static uint8_t calculateChecksum(
        const uint8_t* data,
        std::size_t size
    );
};

#endif