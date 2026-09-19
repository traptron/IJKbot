
#include "serial.hpp"

#include <cerrno>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <termios.h>
#include <unistd.h>


SerialPort::SerialPort(
    const std::string& device,
    int baudrate)
{
    fd_ = open(
        device.c_str(),
        O_RDWR | O_NOCTTY
    );

    if (fd_ < 0)
    {
        throw std::runtime_error(
            "Cannot open serial port " + device
        );
    }


    struct termios tty{};

    if (tcgetattr(fd_, &tty) != 0)
    {
        close(fd_);
        fd_ = -1;

        throw std::runtime_error(
            "tcgetattr() failed"
        );
    }


    // Baudrate
    if (cfsetispeed(&tty, baudrate) != 0 ||
        cfsetospeed(&tty, baudrate) != 0)
    {
        close(fd_);
        fd_ = -1;

        throw std::runtime_error(
            "Cannot set baudrate"
        );
    }


    // 8 data bits
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;

    // No parity
    tty.c_cflag &= ~PARENB;

    // 1 stop bit
    tty.c_cflag &= ~CSTOPB;

    // No hardware flow control
    tty.c_cflag &= ~CRTSCTS;

    // Enable receiver
    tty.c_cflag |= CREAD | CLOCAL;


    // Raw input
    tty.c_iflag &= ~(
        IXON |
        IXOFF |
        IXANY |
        IGNBRK |
        BRKINT |
        PARMRK |
        ISTRIP |
        INLCR |
        IGNCR |
        ICRNL
    );


    // Raw output
    tty.c_oflag &= ~OPOST;


    // Raw local mode
    tty.c_lflag &= ~(
        ECHO |
        ECHONL |
        ICANON |
        ISIG |
        IEXTEN
    );


    // Non-blocking read configuration
    tty.c_cc[VMIN] = 0;
    tty.c_cc[VTIME] = 0;


    if (tcsetattr(fd_, TCSANOW, &tty) != 0)
    {
        close(fd_);
        fd_ = -1;

        throw std::runtime_error(
            "tcsetattr() failed"
        );
    }


    // Очистить старые данные UART
    tcflush(fd_, TCIOFLUSH);
}


SerialPort::~SerialPort()
{
    if (fd_ >= 0)
    {
        close(fd_);
        fd_ = -1;
    }
}


bool SerialPort::isOpen() const
{
    return fd_ >= 0;
}


void SerialPort::write(
    const uint8_t* data,
    std::size_t size)
{
    if (fd_ < 0)
    {
        throw std::runtime_error(
            "Serial port is not open"
        );
    }


    std::size_t total_written = 0;

    while (total_written < size)
    {
        ssize_t result = ::write(
            fd_,
            data + total_written,
            size - total_written
        );


        if (result < 0)
        {
            if (errno == EINTR)
            {
                continue;
            }

            throw std::runtime_error(
                "Serial write failed"
            );
        }


        if (result == 0)
        {
            throw std::runtime_error(
                "Serial write returned 0"
            );
        }


        total_written +=
            static_cast<std::size_t>(result);
    }


    // Дождаться физической передачи данных UART
    if (tcdrain(fd_) != 0)
    {
        throw std::runtime_error(
            "tcdrain() failed"
        );
    }
}