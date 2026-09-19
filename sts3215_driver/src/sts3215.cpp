#include "sts3215.hpp"

#include <algorithm>
#include <vector>
#include <stdexcept>


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
    if (id > 253 || data_size == 0 || data_size > 252) {
        throw std::invalid_argument("Invalid servo ID or register write size");
    }
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


    serial_.discardInput();
    serial_.write(
        packet.data(),
        packet.size()
    );
    const auto reply = readStatus(serial_.deadline());
    if (reply.id != id || !reply.data.empty()) {
        throw std::runtime_error("Unexpected WRITE acknowledgement");
    }
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
    stop(id);


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

    if (readRegisters(id, ADDR_MODE, 1).at(0) != MODE_WHEEL) {
        throw std::runtime_error("Wheel mode readback failed (check EEPROM lock)");
    }
    // Acceleration is controlled by the host; clear any previous servo ramp.
    const uint8_t acceleration = 0;
    writeRegister(id, 0x29, &acceleration, 1);


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

void STS3215::validateIds(const std::array<uint8_t, 2>& ids)
{
    if (ids[0] > 253 || ids[1] > 253 || ids[0] == ids[1]) {
        throw std::invalid_argument("Servo IDs must be distinct and in [0, 253]");
    }
}

void STS3215::sendPacket(
    uint8_t id, uint8_t instruction, const std::vector<uint8_t>& parameters)
{
    if (parameters.size() > 253) {
        throw std::invalid_argument("Packet too large");
    }
    std::vector<uint8_t> packet{
        HEADER, HEADER, id, static_cast<uint8_t>(parameters.size() + 2), instruction};
    packet.insert(packet.end(), parameters.begin(), parameters.end());
    packet.push_back(calculateChecksum(packet.data() + 2, packet.size() - 2));
    serial_.write(packet.data(), packet.size());
}

STS3215::Status STS3215::readStatus(SerialPort::Deadline until)
{
    // Search the header with a single deadline: noise cannot extend the timeout.
    unsigned headers = 0;
    uint8_t byte = 0;
    do {
        serial_.readExact(&byte, 1, until);
        headers = byte == HEADER ? headers + 1 : 0;
    } while (headers < 2);
    uint8_t id = HEADER;
    while (id == HEADER) {
        serial_.readExact(&id, 1, until);
    }
    uint8_t length = 0;
    serial_.readExact(&length, 1, until);
    if (id > 253 || length < 2 || length > 32) {
        throw std::runtime_error("Invalid servo status header/length");
    }
    std::vector<uint8_t> body(length);
    serial_.readExact(body.data(), body.size(), until);
    unsigned sum = id + length;
    for (uint8_t value : body) {
        sum += value;
    }
    if ((sum & 0xFF) != 0xFF) {
        throw std::runtime_error("Servo status checksum mismatch");
    }
    if (body.front() != 0) {
        throw std::runtime_error("Servo " + std::to_string(id) +
                                " reports error bits " + std::to_string(body.front()));
    }
    return {id, std::vector<uint8_t>(body.begin() + 1, body.end() - 1)};
}

std::vector<uint8_t> STS3215::readRegisters(uint8_t id, uint8_t address, uint8_t size)
{
    if (id > 253 || size == 0 || size > 30) {
        throw std::invalid_argument("Invalid register read");
    }
    serial_.discardInput();
    sendPacket(id, 0x02, {address, size});
    const auto reply = readStatus(serial_.deadline());
    if (reply.id != id || reply.data.size() != size) {
        throw std::runtime_error("Unexpected READ response ID/length");
    }
    return reply.data;
}

void STS3215::syncWriteSpeeds(
    const std::array<uint8_t, 2>& ids, const std::array<int16_t, 2>& speeds)
{
    validateIds(ids);
    std::vector<uint8_t> parameters{ADDR_GOAL_SPEED, 2};
    for (std::size_t i = 0; i < ids.size(); ++i) {
        const int speed = std::clamp<int>(speeds[i], -MAX_SPEED, MAX_SPEED);
        const uint16_t raw = speed < 0 ? static_cast<uint16_t>(-speed) | 0x8000 : speed;
        parameters.insert(parameters.end(), {
            ids[i], static_cast<uint8_t>(raw & 0xFF), static_cast<uint8_t>(raw >> 8)});
    }
    sendPacket(0xFE, 0x83, parameters);
}

std::array<STS3215::Feedback, 2> STS3215::syncReadFeedback(
    const std::array<uint8_t, 2>& ids)
{
    validateIds(ids);
    serial_.discardInput();
    sendPacket(0xFE, 0x82, {0x38, 8, ids[0], ids[1]});
    const auto until = serial_.deadline();
    std::array<Feedback, 2> feedback{};
    std::array<bool, 2> received{false, false};
    for (std::size_t count = 0; count < ids.size(); ++count) {
        const auto reply = readStatus(until);
        const auto found = std::find(ids.begin(), ids.end(), reply.id);
        if (found == ids.end() || reply.data.size() != 8) {
            throw std::runtime_error("Unexpected SYNC READ response ID/length");
        }
        const auto index = static_cast<std::size_t>(found - ids.begin());
        if (received[index]) {
            throw std::runtime_error("Duplicate SYNC READ response");
        }
        received[index] = true;
        const auto signedWord = [&reply](std::size_t offset) {
            const int raw = reply.data[offset] | (reply.data[offset + 1] << 8);
            return (raw & 0x8000) ? -(raw & 0x7FFF) : raw;
        };
        feedback[index] = {signedWord(0), signedWord(2), reply.data[6] * 0.1, reply.data[7]};
    }
    return feedback;
}
