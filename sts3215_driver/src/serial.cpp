
#include "serial.hpp"

#include <cerrno>
#include <fcntl.h>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <termios.h>
#include <unistd.h>


SerialPort::SerialPort(
    const std::string& device,
    int baudrate,
    int timeout_ms)
    : timeout_ms_(timeout_ms)
{
    if (timeout_ms <= 0) {
        throw std::invalid_argument("UART timeout must be positive");
    }
    fd_ = open(
        device.c_str(),
        O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC
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
    if (tcflush(fd_, TCIOFLUSH) != 0) {
        close(fd_);
        fd_ = -1;
        throw std::runtime_error("tcflush() failed");
    }
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
    const auto until = deadline();

    while (total_written < size)
    {
        waitReady(POLLOUT, until);
        ssize_t result = ::write(
            fd_,
            data + total_written,
            size - total_written
        );


        if (result < 0)
        {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
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
    // tcdrain может зависнуть: доставку подтверждает ответ сервопривода,
    // ограниченный общим deadline чтения. Sync Write подтверждения не имеет.
}

SerialPort::Deadline SerialPort::deadline() const
{
    return std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms_);
}

void SerialPort::waitReady(short events, Deadline until)
{
    while (true) {
        const auto remaining = until - std::chrono::steady_clock::now();
        if (remaining <= std::chrono::steady_clock::duration::zero()) {
            throw std::runtime_error("UART transaction timeout");
        }
        const auto milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(remaining);
        pollfd descriptor{fd_, events, 0};
        const int result = poll(&descriptor, 1, static_cast<int>(milliseconds.count()) + 1);
        if (result < 0 && errno == EINTR) {
            continue;
        }
        if (result < 0 || (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL))) {
            throw std::runtime_error("UART disconnected or poll failed");
        }
        if (result > 0 && (descriptor.revents & events)) {
            return;
        }
    }
}

void SerialPort::readExact(uint8_t* data, std::size_t size, Deadline until)
{
    std::size_t received = 0;
    while (received < size) {
        waitReady(POLLIN, until);
        const auto count = ::read(fd_, data + received, size - received);
        if (count < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        }
        if (count <= 0) {
            throw std::runtime_error("UART read failed");
        }
        received += static_cast<std::size_t>(count);
    }
}

void SerialPort::discardInput()
{
    if (tcflush(fd_, TCIFLUSH) != 0) {
        throw std::runtime_error("UART input flush failed");
    }
}
