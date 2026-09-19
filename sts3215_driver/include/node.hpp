#ifndef STS3215_NODE_HPP
#define STS3215_NODE_HPP

#include "serial.hpp"
#include "sts3215.hpp"

#include <cstdint>
#include <rclcpp/rclcpp.hpp>


class STS3215Node : public rclcpp::Node
{
public:
    STS3215Node();

    void runTerminalTest();


private:
    static constexpr uint8_t SERVO_ID = 1;

    SerialPort serial_;
    STS3215 servo_;
};


#endif