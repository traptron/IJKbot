#ifndef SERIAL_HPP
#define SERIAL_HPP

#include <cstddef>
#include <cstdint>
#include <chrono>
#include <string>

class SerialPort
{
public:
    SerialPort(
        const std::string& device,
        int baudrate,
        int timeout_ms = 8
    );

    ~SerialPort();

    // Файловый дескриптор нельзя безопасно копировать
    SerialPort(const SerialPort&) = delete;
    SerialPort& operator=(const SerialPort&) = delete;

    bool isOpen() const;

    void write(
        const uint8_t* data,
        std::size_t size
    );

    using Deadline = std::chrono::steady_clock::time_point;
    Deadline deadline() const;
    void readExact(uint8_t* data, std::size_t size, Deadline deadline);
    void discardInput();

private:
    int fd_ = -1;
    int timeout_ms_;
    void waitReady(short events, Deadline deadline);
};

#endif
