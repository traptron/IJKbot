#ifndef SERIAL_HPP
#define SERIAL_HPP

#include <cstddef>
#include <cstdint>
#include <string>

class SerialPort
{
public:
    SerialPort(
        const std::string& device,
        int baudrate
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

private:
    int fd_ = -1;
};

#endif