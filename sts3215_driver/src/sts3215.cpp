#include "sts3215.hpp"

#include <algorithm>
#include <vector>


STS3215::STS3215(SerialPort& serial)
    : serial_(serial)
{
}


uint8_t STS3215::calculateChecksum(
    const uint8_t* data,
    std::size_t size)
{
    uint16_t sum = 0;

    for (std::size_t i = 0; i < size; ++i)
    {
        sum += data[i];
    }

    return static_cast<uint8_t>(~sum);
}


void STS3215::writeRegister(
    uint8_t id,
    uint8_t address,
    const uint8_t* data,
    std::size_t data_size)
{
    /*
     * Packet:
     *
     * FF FF
     * ID
     * LENGTH
     * 03              WRITE
     * ADDRESS
     * DATA...
     * CHECKSUM
     */

    const std::size_t packet_size =
        7 + data_size;

    std::vector<uint8_t> packet(packet_size);

    packet[0] = HEADER;
    packet[1] = HEADER;

    packet[2] = id;

    /*
     * parameters:
     * ADDRESS + DATA
     *
     * LENGTH = parameters + 2
     */
    packet[3] =
        static_cast<uint8_t>(data_size + 3);

    packet[4] = INST_WRITE;
    packet[5] = address;


    for (std::size_t i = 0; i < data_size; ++i)
    {
        packet[6 + i] = data[i];
    }


    /*
     * Checksum считается:
     *
     * ID + LENGTH + INSTRUCTION + PARAMETERS
     */

    packet[packet_size - 1] =
        calculateChecksum(
            &packet[2],
            packet_size - 3
        );


    serial_.write(
        packet.data(),
        packet.size()
    );
}


void STS3215::setTorque(
    uint8_t id,
    bool enabled)
{
    const uint8_t value =
        enabled ? 1 : 0;

    writeRegister(
        id,
        ADDR_TORQUE_ENABLE,
        &value,
        1
    );
}


void STS3215::enableWheelMode(uint8_t id)
{
    /*
     * Отключаем torque перед изменением режима.
     */
    setTorque(id, false);


    /*
     * Mode = 1
     *
     * Wheel / constant-speed mode.
     */
    const uint8_t mode = MODE_WHEEL;

    writeRegister(
        id,
        ADDR_MODE,
        &mode,
        1
    );


    /*
     * Включаем torque обратно.
     */
    setTorque(id, true);
}


void STS3215::setSpeed(
    uint8_t id,
    int16_t speed)
{
    speed = std::clamp<int16_t>(
        speed,
        -MAX_SPEED,
        MAX_SPEED
    );


    uint16_t raw_speed;

    if (speed < 0)
    {
        raw_speed =
            static_cast<uint16_t>(-speed)
            | 0x8000;
    }
    else
    {
        raw_speed =
            static_cast<uint16_t>(speed);
    }


    uint8_t data[2];

    data[0] =
        static_cast<uint8_t>(
            raw_speed & 0xFF
        );

    data[1] =
        static_cast<uint8_t>(
            (raw_speed >> 8) & 0xFF
        );


    writeRegister(
        id,
        ADDR_GOAL_SPEED,
        data,
        2
    );
}


void STS3215::stop(uint8_t id)
{
    setSpeed(id, 0);
}